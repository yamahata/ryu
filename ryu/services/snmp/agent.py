# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2013 Isaku Yamahata <yamahata at private email ne jp>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# to watch traps
# snmptrapd -C -Lo -f --authCommunity='log traps' \
# --createUser='-e 0x8000000001020304 ryu-snmp-user MD5 authkey1 DES privkey1'\
# --authuser='log ryu-snmp-user authPriv'
#
# to get informations
# snmpwalk -v 3 -u ryu-snmp-user -e 0x8000000001020304 \
# -l authPriv -a MD5 -A authkey1 -x DES -X privkey1 127.0.0.1 enterprise

import os.path

from oslo.config import cfg
from pyasn1.compat.octets import null
from pysnmp.entity import config
from pysnmp.entity import engine
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.entity.rfc3413 import context
from pysnmp.entity.rfc3413 import ntforg
from pysnmp.entity.rfc3413.oneliner import mibvar
from pysnmp.carrier.asynsock.dgram import udp
from pysnmp.proto.api import v2c
from pysnmp.smi import builder
from pysnmp.smi import view


from ryu.base import app_manager
from ryu.controller import handler
from ryu.lib import dpid as dpid_lib
from ryu.lib import hub
from ryu.topology import event as topo_event


CONF = cfg.CONF
CONF.register_opts([
    cfg.StrOpt('snmp-host', default='',
               help='snmp IP address to get request'),
    cfg.IntOpt('snmp-port', default=161,
               help='snmp port to get request'),
    cfg.StrOpt('snmp-target-host', default='127.0.0.1',
               help='snmptrap target host ip address to send trap'),
    cfg.IntOpt('snmp-target-port', default=162,
               help='snmptrap port to send trap'),

    cfg.StrOpt('snmp-notification-target', default='ryu-notification',
               help='snmptrap target name'),

    cfg.MultiStrOpt('mib-dir', default=[],
                    help='directories to load MIBs'),
])


from pysnmp import debug
debug.setLogger(debug.Debug('all'))


class SNMPAgent(app_manager.RyuApp):
    _DEFAULT_ENGINE_ID = '8000000001020304'
    _DEFAULT_V3_USER = 'ryu-snmp-user'
    _DEFAULT_SECURITY_NAME = 'ryu-creds'
    _DEFAULT_NMS = 'ryu-nms'
    # 'noAuthNoPriv', 'authNoPrive', 'authPriv'
    _DEFAULT_SECURITY_LEVEL = 'authPriv'
    _DEFAULT_AUTH = config.usmHMACMD5AuthProtocol       # 'SHA', 'MD5'
    _DEFAULT_AUTH_KEY = 'authkey1'
    _DEFAULT_PRIV = config.usmDESPrivProtocol           # 'DES', 'AES'
    _DEFAULT_PRIV_KEY = 'privkey1'

    _NOTIFICATION_NAME = 'ryu-notification'
    _PARAMS_NAME = 'my-filter'
    _TRANSPORT_TAG = 'all-my-managers'

    def __init__(self, *args, **kwargs):
        super(SNMPAgent, self).__init__(*args, **kwargs)
        snmp_engine = engine.SnmpEngine(
            v2c.OctetString(hexValue=self._DEFAULT_ENGINE_ID))
        self._snmp_engine = snmp_engine

        # TODO authProtocol, authKey, privProtocol, privKey, contextEngineId
        config.addV3User(snmp_engine, self._DEFAULT_V3_USER,
                         self._DEFAULT_AUTH, self._DEFAULT_AUTH_KEY,
                         self._DEFAULT_PRIV, self._DEFAULT_PRIV_KEY)
        config.addTargetParams(snmp_engine,
                               self._DEFAULT_SECURITY_NAME,
                               self._DEFAULT_V3_USER,
                               self._DEFAULT_SECURITY_LEVEL)
        udp_domain_name_target = udp.domainName + (1, )
        config.addSocketTransport(
            snmp_engine, udp_domain_name_target,
            udp.UdpTransport().openClientMode())
        config.addTargetAddr(snmp_engine,
                             self._DEFAULT_NMS,
                             udp_domain_name_target,
                             (CONF.snmp_target_host, CONF.snmp_target_port),
                             self._DEFAULT_SECURITY_NAME,
                             tagList=self._TRANSPORT_TAG)
        config.addNotificationTarget(snmp_engine,
                                     self._NOTIFICATION_NAME,
                                     self._PARAMS_NAME,
                                     self._TRANSPORT_TAG,
                                     'trap')
        config.addContext(snmp_engine, '')
        # Allow NOTIFY access to Agent's MIB by this SNMP model
        config.addVacmUser(snmp_engine, 3,  # SNMPv3
                           self._DEFAULT_V3_USER, self._DEFAULT_SECURITY_LEVEL,
                           (), (), (1, 3, 6))
        snmp_context = context.SnmpContext(snmp_engine)
        self._snmp_context = snmp_context
        self._ntf_org = ntforg.NotificationOriginator(snmp_context)

        # command responder
        config.addSocketTransport(
            snmp_engine, udp.domainName + (2, ),
            udp.UdpTransport().openServerMode((CONF.snmp_host,
                                               CONF.snmp_port)))
        mib_builder = self._snmp_context.getMibInstrum().getMibBuilder()
        self._mib_builder = mib_builder

        mib_sources = list(mib_builder.getMibSources())
        dirname = os.path.dirname(__file__)
        mib_sources.append(builder.DirMibSource(os.path.join(dirname, 'mibs')))
        mib_sources.append(builder.DirMibSource(os.path.join(
            dirname, 'mibs', 'instances')))
        # mib_sources.append(builder.DirMibSource('.'))
        mib_sources.extend([builder.DirMibSource(CONF.mib_dir)
                            for mib_dir in CONF.mib_dir])
        mib_builder.setMibSources(*mib_sources)

        cmdrsp.GetCommandResponder(snmp_engine, snmp_context)
        cmdrsp.NextCommandResponder(snmp_engine, snmp_context)
        cmdrsp.BulkCommandResponder(snmp_engine, snmp_context)
        cmdrsp.SetCommandResponder(snmp_engine, snmp_context)

        # for MIB resolution
        mib_view_controller = view.MibViewController(mib_builder)
        self._mib_view_controller = mib_view_controller

        # RYU-MIB
        mib_builder.loadModules('RYU-MIB')
        mib_builder.loadModules('__RYU-MIB')

        # view
        sys_name = mibvar.MibVariable('SNMPv2-MIB', 'sysName', 0)
        sys_name.resolveWithMib(mib_view_controller)
        config.addVacmUser(snmp_engine, 3, self._DEFAULT_V3_USER,
                           self._DEFAULT_SECURITY_LEVEL,
                           sys_name)
        ryu_mib = mibvar.MibVariable('RYU-MIB', 'ryuMIB')
        ryu_mib.resolveWithMib(mib_view_controller)
        config.addVacmUser(snmp_engine, 3, self._DEFAULT_V3_USER,
                           self._DEFAULT_SECURITY_LEVEL,
                           ryu_mib)

    def start(self):
        self.threads.append(hub.spawn(self._loop))
        super(SNMPAgent, self).start()
        sys_name = mibvar.MibVariable('SNMPv2-MIB', 'sysName', 0)
        sys_name.resolveWithMib(self._mib_view_controller)
        self.send_trap(None, ('SNMPv2-MIB', 'coldStart'),
                       ((sys_name, v2c.OctetString('Ryu-SNMP-agent')), ))

    def _loop(self):
        self._snmp_engine.transportDispatcher.jobStarted(1)
        try:
            self._snmp_engine.transportDispatcher.runDispatcher()
        except:
            self._snmp_engine.transportDispatcher.closeDispatcher()
            raise

    def send_trap(self, target, name, var_binds=(), cb_fun=None, cb_ctx=None,
                  context_name=null, instance_index=None):
        print var_binds
        if target is None:
            target = self._NOTIFICATION_NAME
        error_indication = self._ntf_org.sendNotification(
            self._snmp_engine, target, name, var_binds, cb_fun, cb_ctx,
            context_name, instance_index)

    def _refresh_mib(self):
        self._snmp_context.getMibInstrum()._MibInstrumController__indexMib()

    @staticmethod
    def _dp_instance_symbol(symbol, instance_index):
        #return symbol + '_' + ''.join('%02x' % i for i in instance_index)
        return symbol + '_' + '_'.join('%d' % i for i in instance_index)

    @handler.set_ev_cls(topo_event.EventSwitchEnter)
    def switch_enter_handler(self, ev):
        dpid_buf = dpid_lib.dpid_to_buf(ev.switch.dp.id)
        mib_builder = self._mib_builder
        (MibScalar,
         MibScalarInstance) = mib_builder.importSymbols('SNMPv2-SMI',
                                                        'MibScalar',
                                                        'MibScalarInstance')
        (datapathEntry,
         dpIndex,
         dpID,
         dpNBuffers,
         dpNTables,
         dpAuxiliaryID,
         dpCapabilities,
         dpRowStatus,
         datapathConnected) = mib_builder.importSymbols('RYU-MIB',
                                                        'datapathEntry',
                                                        'dpIndex',
                                                        'dpID',
                                                        'dpNBuffers',
                                                        'dpNTables',
                                                        'dpAuxiliaryID',
                                                        'dpCapabilities',
                                                        'dpRowStatus',
                                                        'datapathConnected')

        instance_index = datapathEntry.getInstIdFromIndices(dpid_buf)
        dpIndex_ = MibScalarInstance(dpIndex.name, instance_index,
                                     dpIndex.syntax.clone(dpid_buf))
        dpID_ = MibScalarInstance(dpID.name, instance_index,
                                  dpID.syntax.clone(dpid_buf))
        dpNBuffers_ = MibScalarInstance(dpNBuffers.name, instance_index,
                                        dpNBuffers.syntax.clone(0))
        dpNTables_ = MibScalarInstance(dpNTables.name, instance_index,
                                       dpNTables.syntax.clone(0))
        dpAuxiliaryID_ = MibScalarInstance(dpAuxiliaryID.name, instance_index,
                                           dpAuxiliaryID.syntax.clone(0))
        dpCapabilities_ = MibScalarInstance(dpCapabilities.name,
                                            instance_index,
                                            dpCapabilities.syntax.clone(0))
        dpRowStatus_ = MibScalarInstance(dpRowStatus.name, instance_index,
                                         dpRowStatus.syntax.clone())

        dp_dict = dict((self._dp_instance_symbol(name, instance_index), i)
                       for name, i in (
                           ('dpIndex', dpIndex_),
                           ('dpID', dpID_),
                           ('dpNBuffers', dpNBuffers_),
                           ('dpNTables', dpNTables_),
                           ('dpAuxiliaryID', dpAuxiliaryID_),
                           ('dpCapabilities', dpCapabilities_),
                           ('dpRowStatus', dpRowStatus_)))
        mib_builder.exportSymbols('__RYU-MIB', **dp_dict)

        # without this, pysnmp.entity.rfc3413.ntforg.sendNotification()
        # fails to find the object.
        self._refresh_mib()

        self.send_trap(None, ('RYU-MIB', 'datapathConnected'),
                       instance_index=instance_index)

    @handler.set_ev_cls(topo_event.EventSwitchLeave)
    def switch_leave_handler(self, ev):
        dpid_buf = dpid_lib.dpid_to_buf(ev.switch.dp.id)
        mib_builder = self._mib_builder
        (datapathEntry,
         dpID,
         datapathDisconnected
         ) = mib_builder.importSymbols('RYU-MIB',
                                       'datapathEntry',
                                       'dpID',
                                       'datapathDisconnected')

        instance_index = datapathEntry.getInstIdFromIndices(dpid_buf)
        # TODO: check if instance exists. If not, populate first
        self.send_trap(None, ('RYU-MIB', 'datapathDisconnected'),
                       instance_index=instance_index)

        dp_symbols = ('dpIndex', 'dpID', 'dpNBuffers', 'dpNTables',
                      'dpAuxiliaryID', 'dpCapabilities', 'dpRowStatus')
        dp_symbols = [self._dp_instance_symbol(symbol, instance_index)
                      for symbol in dp_symbols]
        mib_builder.unexportSymbols('__RYU-MIB', *dp_symbols)
        # self._refresh_mib()
