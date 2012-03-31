# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2012 Isaku Yamahata <yamahata at valinux co jp>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
from collections import defaultdict

from ryu import exception as ryu_exc
from ryu.app.rest_nw_id import NW_ID_VPORT_GRE
from ryu.app.rest_nw_id import RESERVED_NETWORK_IDS
from ryu.controller import dispatcher
from ryu.controller import dpset
from ryu.controller import event
from ryu.controller import handler
from ryu.controller import handler_utils
from ryu.controller import network
from ryu.controller import ofp_event
from ryu.controller import tunnels
from ryu.ofproto import nx_match
from ryu.lib import mac


LOG = logging.getLogger(__name__)


# Those events are higher level events than events of network tenant,
# tunnel ports as the race conditions are masked.
# Add event is generated only when all necessary informations are gathered,
# Del event is generated when any one of the informations are deleted.
#
# Example: ports for VMs
# there is a race condition between ofp port add/del event and
# register network_id for the port.


class EventTunnelKeyDel(event.EventBase):
    def __init__(self, tunnel_key):
        super(EventTunnelKeyDel, self).__init__()
        self.tunnel_key = tunnel_key


class EventPortBase(event.EventBase):
    def __init__(self, dpid, port_no):
        super(EventPortBase, self).__init__()
        self.dpid = dpid
        self.port_no = port_no


class EventVMPort(EventPortBase):
    def __init__(self, network_id, tunnel_key,
                 dpid, port_no, mac_address, add_del):
        super(EventVMPort, self).__init__(dpid, port_no)
        self.network_id = network_id
        self.tunnel_key = tunnel_key
        self.mac_address = mac_address
        self.add_del = add_del

    def __str__(self):
        return ('EventVMPort<dpid %x port_no %d '
                'network_id %s tunnel_key %s mac %s add_del %s>' %
                (self.dpid, self.port_no,
                 self.network_id, self.tunnel_key, self.mac_address,
                 self.add_del))


class EventTunnelPort(EventPortBase):
    def __init__(self, dpid, port_no, remote_dpid, add_del):
        super(EventTunnelPort, self).__init__(dpid, port_no)
        self.remote_dpid = remote_dpid
        self.add_del = add_del

    def __str__(self):
        return ('EventTunnelPort<dpid %x port_no %d remote_dpid %x '
                'add_del %s>' %
                (self.dpid, self.port_no, self.remote_dpid, self.add_del))


QUEUE_NAME_PORT_SET_EV = 'port_set_event'
DISPATCHER_NAME_PORT_SET_EV = 'port_set_event'
PORT_SET_EV_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_PORT_SET_EV)


def _link_is_up(dpset_, dp, port_no):
    try:
        state = dpset_.get_port_state(dp.id, port_no)
        return not (state & dp.ofproto.OFPPS_LINK_DOWN)
    except ryu_exc.PortNotFound:
        return False


class PortSet(object):
    def __init__(self, **kwargs):
        super(PortSet, self).__init__()
        self.nw = kwargs['network']
        self.tunnels = kwargs['tunnels']
        self.dpset = kwargs['dpset']
        self.ev_q = dispatcher.EventQueue(QUEUE_NAME_PORT_SET_EV,
                                          PORT_SET_EV_DISPATCHER)

    def _check_link_state(self, dp, port_no, add_del):
        if add_del:
            # When adding port, the link should be UP.
            return _link_is_up(self.dpset, dp, port_no)
        else:
            # When deleting port, the link status isn't cared.
            return True

    # Tunnel port
    # of connecting: self.dpids by (dpid, port_no)
    #    datapath: connected: EventDP event
    #    port status: UP: port add/delete/modify event
    # remote dpid: self.tunnels by (dpid, port_no): tunnel port add/del even
    def _tunnel_port_handler(self, dpid, port_no, add_del):
        dp = self.dpset.get(dpid)
        if dp is None:
            return
        if not self._check_link_state(dp, port_no, add_del):
            return
        try:
            remote_dpid = self.tunnels.get_remote_dpid(dpid, port_no)
        except ryu_exc.PortNotFound:
            return

        self.ev_q.queue(EventTunnelPort(dpid, port_no, remote_dpid, add_del))

    # VM port
    # of connection: self.dpids by (dpid, port_no)
    #    datapath: connected: EventDP event
    #    port status: UP: Port add/delete/modify event
    # network_id: self.nw by (dpid, port_no): network port add/del event
    # mac_address: self.nw by (dpid, port_no): mac address add/del event
    # tunnel key: from self.tunnels by network_id: tunnel key add/del event
    def _vm_port_handler(self, dpid, port_no,
                         network_id, mac_address, add_del):
        if network_id in RESERVED_NETWORK_IDS:
            return
        if mac_address is None:
            return
        dp = self.dpset.get(dpid)
        if dp is None:
            return
        if not self._check_link_state(dp, port_no, add_del):
            return
        try:
            tunnel_key = self.tunnels.get_key(network_id)
        except ryu_exc.TunnelKeyNotFound:
            return

        self.ev_q.queue(EventVMPort(network_id, tunnel_key, dpid,
                                    port_no, mac_address, add_del))

    def _vm_port_mac_handler(self, dpid, port_no, network_id, add_del):
        try:
            mac_address = self.nw.get_mac(dpid, port_no)
        except ryu_exc.PortNotFound:
            return
        self._vm_port_handler(dpid, port_no, network_id, mac_address,
                              add_del)

    def _port_handler(self, dpid, port_no, add_del):
        """
        :type add_del: bool
        :param add_del: True for add, False for del
        """
        try:
            port = self.nw.get_port(dpid, port_no)
        except ryu_exc.PortNotFound:
            return

        if port.network_id is None:
            return

        if port.network_id == NW_ID_VPORT_GRE:
            self._tunnel_port_handler(dpid, port_no, add_del)
            return

        self._vm_port_handler(dpid, port_no, port.network_id,
                              port.mac_address, add_del)

    def _tunnel_key_del(self, tunnel_key):
        self.ev_q.queue(EventTunnelKeyDel(tunnel_key))

    # nw: network del
    #           port add/del (vm/tunnel port)
    #           mac address add/del(only vm port)
    # tunnels: tunnel key add/del
    #          tunnel port add/del
    # dpset: eventdp
    #        port add/delete/modify

    @handler.set_ev_cls(network.EventNetworkDel,
                        network.NETWORK_TENANT_EV_DISPATCHER)
    def network_del_handler(self, ev):
        network_id = ev.network_id
        if network_id in RESERVED_NETWORK_IDS:
            return
        try:
            tunnel_key = self.tunnels.get_key(network_id)
        except ryu_exc.TunnelKeyNotFound:
            return
        for (dpid, port_no) in self.nw.list_ports(network_id):
            self._vm_port_mac_handler(dpid, port_no, network_id, False)
        self._tunnel_key_del(tunnel_key)

    @handler.set_ev_cls(network.EventNetworkPort,
                        network.NETWORK_TENANT_EV_DISPATCHER)
    def network_port_handler(self, ev):
        self._vm_port_mac_handler(ev.dpid, ev.port_no, ev.network_id,
                                   ev.add_del)

    @handler.set_ev_cls(network.EventMacAddress,
                        network.NETWORK_TENANT_EV_DISPATCHER)
    def network_mac_address_handler(self, ev):
        self._vm_port_handler(ev.dpid, ev.port_no, ev.network_id,
                              ev.mac_address, ev.add_del)

    @handler.set_ev_cls(tunnels.EventTunnelKeyAdd,
                        tunnels.TUNNEL_EV_DISPATCHER)
    def tunnel_key_add_handler(self, ev):
        for (dpid, port_no) in self.nw.list_ports(ev.network_id):
            self._vm_port_mac_handler(dpid, port_no, ev.network_id, True)

    @handler.set_ev_cls(tunnels.EventTunnelKeyDel,
                        tunnels.TUNNEL_EV_DISPATCHER)
    def tunnel_key_del_handler(self, ev):
        network_id = ev.network_id
        for (dpid, port_no) in self.nw.list_ports(network_id):
            self._vm_port_mac_handler(dpid, port_no, network_id, False)
        if self.nw.has_networks(network_id):
            self._tunnel_key_del(ev.tunnel_key)

    @handler.set_ev_cls(tunnels.EventTunnelPort, tunnels.TUNNEL_EV_DISPATCHER)
    def tunnel_port_handler(self, ev):
        self._port_handler(ev.dpid, ev.port_no, ev.add_del)

    @handler.set_ev_cls(dpset.EventDP, dpset.DPSET_EV_DISPATCHER)
    def dp_handler(self, ev):
        if not ev.enter_leave:
            # TODO:XXX
            # What to do on datapath disconnection?
            LOG.debug('dp disconnection ev:%s', ev)

        dpid = ev.dp.id
        for port in self.nw.get_ports(dpid):
            self._port_handler(dpid, port.port_no, ev.enter_leave)

    @handler.set_ev_cls(dpset.EventPortAdd, dpset.DPSET_EV_DISPATCHER)
    def port_add_handler(self, ev):
        self._port_handler(ev.dp.id, ev.port.port_no, True)

    @handler.set_ev_cls(dpset.EventPortDelete, dpset.DPSET_EV_DISPATCHER)
    def port_del_handler(self, ev):
        self._port_handler(ev.dp.id, ev.port.port_no, False)

    @handler.set_ev_cls(dpset.EventPortModify, dpset.DPSET_EV_DISPATCHER)
    def port_modify_handler(self, ev):
        # We don't know LINK status has been changed.
        # So VM/TUNNEL port event can be triggered many times.
        dp = ev.dp
        port = ev.port
        self._port_handler(dp.id, port.port_no,
                           not (port.state & dp.ofproto.OFPPS_LINK_DOWN))


class PortSetDebug(object):
    """app for debug class PortSet"""
    def __init__(self, *_args, **kwargs):
        super(PortSetDebug, self).__init__()
        self.nw = kwargs['network']
        self.dpset = kwargs['dpset']
        self.tunnels = kwargs['tunnels']
        self.port_set = PortSet(**kwargs)
        handler.register_instance(self.port_set)

    @handler.set_ev_cls(EventTunnelKeyDel, PORT_SET_EV_DISPATCHER)
    def tunnel_key_del_handler(self, ev):
        LOG.debug('tunnel_key_del ev %s', ev)

    @handler.set_ev_cls(EventVMPort, PORT_SET_EV_DISPATCHER)
    def vm_port_handler(self, ev):
        LOG.debug('vm_port ev %s', ev)

    @handler.set_ev_cls(EventTunnelPort, PORT_SET_EV_DISPATCHER)
    def tunnel_port_handler(self, ev):
        LOG.debug('tunnel_port ev %s', ev)


class GRETunnel(object):
    """app for L2/L3 with gre tunneling"""

    TABLE_DEFAULT_PRPIRITY = 32768  # = ofproto.OFP_DEFAULT_PRIORITY

    SRC_TABLE = 0
    TUNNEL_OUT_TABLE = 1
    LOCAL_OUT_TABLE = 2

    SRC_PRI_MAC = TABLE_DEFAULT_PRPIRITY
    SRC_PRI_DROP = TABLE_DEFAULT_PRPIRITY / 2
    SRC_PRI_TUNNEL_PASS = TABLE_DEFAULT_PRPIRITY
    SRC_PRI_TUNNEL_DROP = TABLE_DEFAULT_PRPIRITY / 2

    TUNNEL_OUT_PRI_MAC = TABLE_DEFAULT_PRPIRITY
    TUNNEL_OUT_PRI_BROADCAST = TABLE_DEFAULT_PRPIRITY / 2
    TUNNEL_OUT_PRI_PASS = TABLE_DEFAULT_PRPIRITY / 4
    TUNNEL_OUT_PRI_DROP = TABLE_DEFAULT_PRPIRITY / 8

    LOCAL_OUT_PRI_MAC = TABLE_DEFAULT_PRPIRITY
    LOCAL_OUT_PRI_BROADCAST = TABLE_DEFAULT_PRPIRITY / 2
    LOCAL_OUT_PRI_DROP = TABLE_DEFAULT_PRPIRITY / 4

    def __init__(self, *_args, **kwargs):
        super(GRETunnel, self).__init__()
        self.nw = kwargs['network']
        self.dpset = kwargs['dpset']
        self.tunnels = kwargs['tunnels']

        self.port_set = PortSet(**kwargs)
        handler.register_instance(self.port_set)

        handler.register_cls_object(
            handler_utils.ConfigHookDeleteAllFlowsHandler)
        handler.register_cls_object(
            handler_utils.ConfigHookOFPSetConfigHandler)

    # TODO: track active vm/tunnel ports

    @handler.set_ev_cls(dpset.EventDP, dpset.DPSET_EV_DISPATCHER)
    def dp_handler(self, ev):
        if not ev.enter_leave:
            return

        # enable nicira extension
        # TODO:XXX error handling
        dp = ev.dp
        dp.send_nxt_set_flow_format(dp.ofproto.NXFF_NXM)
        flow_mod_table_id = dp.ofproto_parser.NXTFlowModTableId(dp, 1)
        dp.send_msg(flow_mod_table_id)
        dp.send_barrier()

    @staticmethod
    def _make_command(table, command):
        return table << 8 | command

    def send_flow_mod(self, dp, rule, table, command, priority, actions):
        command = self._make_command(table, command)
        dp.send_flow_mod(rule=rule, cookie=0, command=command, idle_timeout=0,
                         hard_timeout=0, priority=priority, actions=actions)

    def send_flow_del(self, dp, rule, table, command, priority, out_port):
        command = self._make_command(table, command)
        dp.send_flow_mod(rule=rule, cookie=0, command=command, idle_timeout=0,
                         hard_timeout=0, priority=priority, out_port=out_port)

    def _list_tunnel_port(self, dp, remote_dpids):
        dpid = dp.id
        tunnel_ports = []
        for other_dpid in remote_dpids:
            if other_dpid == dpid:
                continue
            other_dp = self.dpset.get(other_dpid)
            if other_dp is None:
                continue
            try:
                port_no = self.tunnels.get_port(dpid, other_dpid)
            except ryu_exc.PortNotFound:
                continue
            if not self._link_is_up(dp, port_no):
                continue
            tunnel_ports.append(port_no)

        return tunnel_ports

    def _link_is_up(self, dp, port_no):
        return _link_is_up(self.dpset, dp, port_no)

    def _vm_port_add(self, ev):
        dpid = ev.dpid
        dp = self.dpset.get(dpid)
        assert dp is not None
        ofproto = dp.ofproto
        ofproto_parser = dp.ofproto_parser
        mac_address = ev.mac_address
        network_id = ev.network_id
        tunnel_key = ev.tunnel_key
        remote_dpids = self.nw.get_dpids(network_id)
        remote_dpids.remove(dpid)

        # LOCAL_OUT_TABLE: unicast
        rule = nx_match.ClsRule()
        rule.set_tun_id(tunnel_key)
        rule.set_dl_dst(mac_address)
        actions = [ofproto_parser.OFPActionOutput(ev.port_no)]
        self.send_flow_mod(dp, rule, self.LOCAL_OUT_TABLE, ofproto.OFPFC_ADD,
                           self.LOCAL_OUT_PRI_MAC, actions)

        # LOCAL_OUT_TABLE: broad cast
        rule = nx_match.ClsRule()
        rule.set_tun_id(tunnel_key)
        rule.set_dl_dst(mac.BROADCAST)

        actions = []
        for port in self.nw.get_ports(dpid):
            if (port.network_id != network_id or port.mac_address is None):
                continue
            if not self._link_is_up(dp, port.port_no):
                continue
            actions.append(ofproto_parser.OFPActionOutput(port.port_no))

        first_instance = (len(actions) == 1)
        assert actions
        if first_instance:
            command = ofproto.OFPFC_ADD
        else:
            command = ofproto.OFPFC_MODIFY_STRICT
        self.send_flow_mod(dp, rule, self.LOCAL_OUT_TABLE, command,
                           self.LOCAL_OUT_PRI_BROADCAST, actions)

        # LOCAL_OUT_TABLE: multicast TODO:XXX

        # LOCAL_OUT_TABLE: catch-all drop
        if first_instance:
            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            self.send_flow_mod(dp, rule, self.LOCAL_OUT_TABLE,
                               ofproto.OFPFC_ADD, self.LOCAL_OUT_PRI_DROP, [])

        # TUNNEL_OUT_TABLE: unicast
        for remote_dpid in remote_dpids:
            remote_dp = self.dpset.get(remote_dpid)
            if remote_dp is None:
                continue
            try:
                tunnel_port_no = self.tunnels.get_port(dpid, remote_dpid)
            except ryu_exc.PortNotFound:
                continue
            if not self._link_is_up(dp, tunnel_port_no):
                continue

            for port in self.nw.get_ports(remote_dpid):
                if port.network_id != network_id or port.mac_address is None:
                    continue
                if not self._link_is_up(remote_dp, port.port_no):
                    continue
                rule = nx_match.ClsRule()
                rule.set_tun_id(tunnel_key)
                rule.set_dl_dst(port.mac_address)
                output = ofproto_parser.OFPActionOutput(tunnel_port_no)
                resubmit_table = ofproto_parser.NXActionResubmitTable(
                    in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
                actions = [output, resubmit_table]
                self.send_flow_mod(dp, rule, self.TUNNEL_OUT_TABLE,
                                   ofproto.OFPFC_ADD, self.TUNNEL_OUT_PRI_MAC,
                                   actions)

            if first_instance:
                rule = nx_match.ClsRule()
                rule.set_in_port(tunnel_port_no)
                rule.set_tun_id(tunnel_key)
                resubmit_table = ofproto_parser.NXActionResubmitTable(
                    in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
                actions = [resubmit_table]
                self.send_flow_mod(dp, rule, self.SRC_TABLE,
                                   ofproto.OFPFC_ADD, self.SRC_PRI_TUNNEL_PASS,
                                   actions)

        if first_instance:
            # TUNNEL_OUT_TABLE: catch-all drop(resubmit to LOCAL_OUT_TABLE)
            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            resubmit_table = ofproto_parser.NXActionResubmitTable(
                in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
            actions = [resubmit_table]
            self.send_flow_mod(dp, rule, self.TUNNEL_OUT_TABLE,
                               ofproto.OFPFC_ADD,
                               self.TUNNEL_OUT_PRI_PASS, actions)

            # TUNNEL_OUT_TABLE: broadcast
            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            rule.set_dl_dst(mac.BROADCAST)
            actions = [ofproto_parser.OFPActionOutput(tunnel_port_no)
                       for tunnel_port_no
                       in self._list_tunnel_port(dp, remote_dpids)]
            resubmit_table = ofproto_parser.NXActionResubmitTable(
                in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
            actions.append(resubmit_table)
            self.send_flow_mod(dp, rule, self.TUNNEL_OUT_TABLE,
                               ofproto.OFPFC_ADD,
                               self.TUNNEL_OUT_PRI_BROADCAST, actions)

        # TUNNEL_OUT_TABLE: multicast TODO:XXX

        # SRC_TABLE:
        dp.send_barrier()
        rule = nx_match.ClsRule()
        rule.set_in_port(ev.port_no)
        rule.set_dl_src(mac_address)
        set_tunnel = ofproto_parser.NXActionSetTunnel(tunnel_key)
        resubmit_table = ofproto_parser.NXActionResubmitTable(
            in_port=ofproto.OFPP_IN_PORT, table=self.TUNNEL_OUT_TABLE)
        actions = [set_tunnel, resubmit_table]
        self.send_flow_mod(dp, rule, self.SRC_TABLE, ofproto.OFPFC_ADD,
                           self.SRC_PRI_MAC, actions)

        rule = nx_match.ClsRule()
        rule.set_in_port(ev.port_no)
        self.send_flow_mod(dp, rule, self.SRC_TABLE, ofproto.OFPFC_ADD,
                           self.SRC_PRI_DROP, [])

        # remote dp
        for remote_dpid in remote_dpids:
            remote_dp = self.dpset.get(remote_dpid)
            if remote_dp is None:
                continue
            try:
                tunnel_port_no = self.tunnels.get_port(remote_dpid, dpid)
            except ryu_exc.PortNotFound:
                continue
            if not self._link_is_up(remote_dp, tunnel_port_no):
                continue

            remote_ofproto = remote_dp.ofproto
            remote_ofproto_parser = remote_dp.ofproto_parser

            # TUNNEL_OUT_TABLE: unicast
            rule = nx_match.ClsRule()
            rule.set_tun_id(ev.tunnel_key)
            rule.set_dl_dst(mac_address)
            output = remote_ofproto_parser.OFPActionOutput(tunnel_port_no)
            resubmit_table = remote_ofproto_parser.NXActionResubmitTable(
                in_port=remote_ofproto.OFPP_IN_PORT,
                table=self.LOCAL_OUT_TABLE)
            actions = [output, resubmit_table]
            self.send_flow_mod(remote_dp, rule, self.TUNNEL_OUT_TABLE,
                               remote_ofproto.OFPFC_ADD,
                               self.TUNNEL_OUT_PRI_MAC, actions)

            if first_instance:
                # SRC_TABLE:
                rule = nx_match.ClsRule()
                rule.set_in_port(tunnel_port_no)
                rule.set_tun_id(ev.tunnel_key)
                resubmit_table = remote_ofproto_parser.NXActionResubmitTable(
                    in_port=remote_ofproto.OFPP_IN_PORT,
                    table=self.LOCAL_OUT_TABLE)
                actions = [resubmit_table]
                self.send_flow_mod(remote_dp, rule, self.SRC_TABLE,
                                   remote_ofproto.OFPFC_ADD,
                                   self.SRC_PRI_TUNNEL_PASS, actions)
            else:
                continue

            # TUNNEL_OUT_TABLE: broadcast
            rule = nx_match.ClsRule()
            rule.set_tun_id(ev.tunnel_key)
            rule.set_dl_dst(mac.BROADCAST)
            tunnel_ports = self._list_tunnel_port(remote_dp, remote_dpids)
            tunnel_ports.append(tunnel_port_no)
            actions = [remote_ofproto_parser.OFPActionOutput(port_no)
                       for port_no in tunnel_ports]
            if len(actions) == 1:
                command = remote_dp.ofproto.OFPFC_ADD
            else:
                command = remote_dp.ofproto.OFPFC_MODIFY_STRICT
            resubmit_table = remote_ofproto_parser.NXActionResubmitTable(
                in_port=remote_ofproto.OFPP_IN_PORT,
                table=self.LOCAL_OUT_TABLE)
            actions.append(resubmit_table)
            self.send_flow_mod(remote_dp, rule, self.TUNNEL_OUT_TABLE,
                               command, self.TUNNEL_OUT_PRI_BROADCAST, actions)

            # TUNNEL_PORT_TABLE: multicast TODO:XXX

    def _vm_port_del(self, ev):
        # TODO:XXX
        dpid = ev.dpid
        dp = self.dpset.get(dpid)
        assert dp is not None
        ofproto = dp.ofproto
        ofproto_parser = dp.ofproto_parser
        mac_address = ev.mac_address
        network_id = ev.network_id
        tunnel_key = ev.tunnel_key

        local_ports = []
        for port in self.nw.get_ports(dpid):
            if port.port_no == ev.port_no:
                continue
            if (port.network_id != network_id or port.mac_address is None):
                continue
            if not self._link_is_up(dp, port.port_no):
                continue
            local_ports.append(port.port_no)

        last_instance = not local_ports

        # SRC_TABLE
        rule = nx_match.ClsRule()
        rule.set_in_port(ev.port_no)
        self.send_flow_mod(dp, rule, self.SRC_TABLE, ofproto.OFPFC_DELETE,
                           ofproto.OFP_DEFAULT_PRIORITY,
                           [])  # priority is ignored

        if last_instance:
            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            self.send_flow_mod(dp, rule, self.SRC_TABLE,
                               ofproto.OFPFC_DELETE,
                               self.SRC_PRI_TUNNEL_DROP,
                               [])  # priority is ignored

            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            self.send_flow_mod(dp, rule, self.TUNNEL_OUT_TABLE,
                               ofproto.OFPFC_DELETE,
                               ofproto.OFP_DEFAULT_PRIORITY,
                               [])  # priority is ignored

            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            self.send_flow_mod(dp, rule, self.LOCAL_OUT_TABLE,
                               ofproto.OFPFC_DELETE,
                               ofproto.OFP_DEFAULT_PRIORITY,
                               [])  # priority is ignored
        else:
            # LOCAL_OUT_TABLE: unicast
            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            rule.set_dl_src(mac_address)
            self.send_flow_del(dp, rule, self.LOCAL_OUT_TABLE,
                               ofproto.OFPFC_DELETE_STRICT,
                               self.LOCAL_OUT_PRI_MAC, ev.port_no)

            # LOCAL_OUT_TABLE: broadcast
            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            rule.set_dl_dst(mac.BROADCAST)
            actions = [ofproto_parser.OFPActionOutput(port_no)
                       for port_no in local_ports]
            self.send_flow_mod(dp, rule, self.LOCAL_OUT_TABLE,
                               ofproto.OFPFC_MODIFY_STRICT,
                               self.LOCAL_OUT_PRI_BROADCAST, actions)

            # LOCAL_OUT_TABLE: multicast TODO:XXX

        # remote dp
        remote_dpids = self.nw.get_dpids(ev.network_id)
        remote_dpids.remove(dpid)
        for remote_dpid in remote_dpids:
            remote_dp = self.dpset.get(remote_dpid)
            if remote_dp is None:
                continue
            try:
                tunnel_port_no = self.tunnels.get_port(remote_dpid, dpid)
            except ryu_exc.PortNotFound:
                continue
            if not self._link_is_up(remote_dp, tunnel_port_no):
                continue

            remote_ofproto = remote_dp.ofproto
            remote_ofproto_parser = remote_dp.ofproto_parser

            if last_instance:
                rule = nx_match.ClsRule()
                rule.set_in_port(tunnel_port_no)
                rule.set_tun_id(tunnel_key)
                self.send_flow_del(remote_dp, rule, self.SRC_TABLE,
                                   remote_ofproto.OFPFC_DELETE_STRICT,
                                   remote_ofproto.OFP_DEFAULT_PRIORITY, [])

                rule = nx_match.ClsRule()
                rule.set_tun_id(tunnel_key)
                rule.set_dl_dst(mac.BROADCAST)
                tunnel_ports = self._list_tunnel_port(remote_dp,
                                                      remote_dpids)
                # broadcast
                tunnel_ports.remove(tunnel_port_no)
                actions = [remote_ofproto_parser.OFPActionOutput(port_no)
                           for port_no in tunnel_ports]
                if not actions:
                    command = remote_dp.ofproto.OFPFC_DELETE_STRICT
                else:
                    command = remote_dp.ofproto.OFPFC_MODIFY_STRICT
                    resubmit_table = \
                        remote_ofproto_parser.NXActionResubmitTable(
                        in_port=remote_ofproto.OFPP_IN_PORT,
                        table=self.LOCAL_OUT_TABLE)
                    actions.append(resubmit_table)
                remote_dp.send_flow_mod(remote_dp, rule, self.TUNNEL_OUT_TABLE,
                                        command, self.TUNNEL_OUT_PRI_BROADCAST,
                                        actions)

            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            rule.set_dl_dst(mac_address)
            self.send_flow_del(remote_dp, rule, self.TUNNEL_OUT_TABLE,
                               remote_ofproto.OFPFC_DELETE_STRICT,
                               self.TUNNEL_OUT_PRI_MAC, tunnel_port_no)

            # TODO:XXX multicast

    def _get_vm_ports(self, dpid):
        ports = defaultdict(list)
        for port in self.nw.get_ports(dpid):
            if port.network_id in RESERVED_NETWORK_IDS:
                continue
            ports[port.network_id].append(port)
        return ports

    def _tunnel_port_add(self, ev):
        dpid = ev.dpid
        dp = self.dpset.get(dpid)
        ofproto = dp.ofproto
        ofproto_parser = dp.ofproto_parser
        remote_dpid = ev.remote_dpid

        local_ports = self._get_vm_ports(dpid)
        remote_ports = self._get_vm_ports(remote_dpid)

        # ingress flow from this tunnel port: remote -> tunnel port
        # SRC_TABLE: drop if unknown tunnel_key
        rule = nx_match.ClsRule()
        rule.set_in_port(ev.port_no)
        self.send_flow_mod(dp, rule, self.SRC_TABLE, ofproto.OFPFC_ADD,
                           self.SRC_PRI_TUNNEL_DROP, [])

        # SRC_TABLE: pass if known tunnel_key
        for network_id in local_ports:
            try:
                tunnel_key = self.tunnels.get_key(network_id)
            except ryu_exc.TunnelKeyNotFound:
                continue
            if network_id not in remote_ports:
                continue

            rule = nx_match.ClsRule()
            rule.set_in_port(ev.port_no)
            rule.set_tun_id(tunnel_key)
            resubmit_table = ofproto_parser.NXActionResubmitTable(
                in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
            actions = [resubmit_table]
            self.send_flow_mod(dp, rule, self.SRC_TABLE, ofproto.OFPFC_ADD,
                               self.SRC_PRI_TUNNEL_PASS, actions)

        # egress flow into this tunnel port: vm port -> tunnel port -> remote
        for network_id in local_ports:
            try:
                tunnel_key = self.tunnels.get_key(network_id)
            except ryu_exc.TunnelKeyNotFound:
                continue
            ports = remote_ports.get(network_id)
            if ports is None:
                continue

            # TUNNEL_OUT_TABLE: unicast
            for port in ports:
                if port.mac_address is None:
                    continue
                rule = nx_match.ClsRule()
                rule.set_tun_id(tunnel_key)
                rule.set_dl_dst(port.mac_address)
                output = ofproto_parser.OFPActionOutput(ev.port_no)
                resubmit_table = ofproto_parser.NXActionResubmitTable(
                    in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
                actions = [output, resubmit_table]
                self.send_flow_mod(dp, rule, self.TUNNEL_OUT_TABLE,
                                   ofproto.OFPFC_ADD, self.TUNNEL_OUT_PRI_MAC,
                                   actions)

            # TUNNEL_OUT_TABLE: broadcast
            remote_dpids = self.nw.get_dpids(ev.network_id)
            remote_dpids.remove(dpid)

            rule = nx_match.ClsRule()
            rule.set_tun_id(tunnel_key)
            rule.set_dl_dst(mac.BROADCAST)
            tunnel_ports = self._list_tunnel_port(dp, remote_dpids)
            tunnel_ports.append(ev.port_no)
            actions = [ofproto_parser.OFPActionOutput(port_no)
                       for port_no in tunnel_ports]
            resubmit_table = ofproto_parser.NXActionResubmitTable(
                    in_port=ofproto.OFPP_IN_PORT, table=self.LOCAL_OUT_TABLE)
            actions.append(resubmit_table)
            if len(tunnel_ports) == 1:
                command = ofproto.OFPFC_ADD
            else:
                command = ofproto.OFPFC_MODIFY_STRICT
            self.send_flow_mod(dp, rule, self.TUNNEL_OUT_TABLE,
                               command, self.TUNNEL_OUT_PRI_BROADCAST, actions)

            # TUNNEL_OUT_TABLE: multicast TODO:XXX

    def _tunnel_port_del(self, ev):
        # TODO:XXX there is no way to delete tunnel port at this moment.
        LOG.debug('tunnel port deletion. %s TODO!', ev)

    @handler.set_ev_cls(EventTunnelKeyDel, PORT_SET_EV_DISPATCHER)
    def tunnel_key_del_handler(self, ev):
        LOG.debug('tunnel_key_del ev %s', ev)

    @handler.set_ev_cls(EventVMPort, PORT_SET_EV_DISPATCHER)
    def vm_port_handler(self, ev):
        LOG.debug('vm_port ev %s', ev)
        if ev.add_del:
            self._vm_port_add(ev)
        else:
            self._vm_port_del(ev)

    @handler.set_ev_cls(EventTunnelPort, PORT_SET_EV_DISPATCHER)
    def tunnel_port_handler(self, ev):
        LOG.debug('tunnel_port ev %s', ev)
        if ev.add_del:
            self._tunnel_port_add(ev)
        else:
            self._tunnel_port_del(ev)

    @handler.set_ev_cls(ofp_event.EventOFPPacketIn, handler.MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        # for debug
        msg = ev.msg
        LOG.debug('packet in ev %s msg %s', ev, ev.msg)
        if msg.buffer_id != 0xffffffff:  # TODO:XXX use constant instead of -1
            msg.datapath.send_packet_out(msg.buffer_id, msg.in_port, [])
