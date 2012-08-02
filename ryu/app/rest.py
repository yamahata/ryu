# Copyright (C) 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2012 Isaku Yamahata <yamahata at private email ne jp>
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

import json
from webob import Response

from ryu.app.wsgi import ControllerBase, WSGIApplication
from ryu.base import app_manager
from ryu.controller import network
from ryu.exception import NetworkNotFound, NetworkAlreadyExist
from ryu.exception import PortNotFound, PortAlreadyExist
from ryu.exception import MacAddressAlreadyExist
from ryu.lib import mac as mac_lib


## TODO:XXX
## define db interface and store those information into db

# REST API

# get the list of networks
# GET /v1.0/networks/
#
# register a new network.
# Fail if the network is already registered.
# POST /v1.0/networks/{network-id}
#
# update a new network.
# Success as nop even if the network is already registered.
#
# PUT /v1.0/networks/{network-id}
#
# remove a network
# DELETE /v1.0/networks/{network-id}
#
# get the list of sets of dpid and port
# GET /v1.0/networks/{network-id}/
#
# register a new set of dpid and port
# Fail if the port is already registered.
# POST /v1.0/networks/{network-id}/{dpid}_{port-id}
#
# update a new set of dpid and port
# Success as nop even if same port already registered
# PUT /v1.0/networks/{network-id}/{dpid}_{port-id}
#
# remove a set of dpid and port
# DELETE /v1.0/networks/{network-id}/{dpid}_{port-id}
#
# get the list of mac addresses of dpid and port
# GET /v1.0/networks/{network-id}/{dpid}_{port-id}/macs/
#
# register a new mac address for dpid and port
# Fail if mac address is already registered or the mac address is used
# for other ports of the same network-id
# POST /v1.0/networks/{network-id}/{dpid}_{port-id}/macs/{mac}
#
# update a new mac address for dpid and port
# Success as nop even if same mac address is already registered.
# For now, changing mac address is not allows as it fails.
# PUT /v1.0/networks/{network-id}/{dpid}_{port-id}/macs/{mac}
#
# For now DELETE /v1.0/networks/{network-id}/{dpid}_{port-id}/macs/{mac}
# is not supported. mac address is released when port is deleted.
#

class NetworkController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(NetworkController, self).__init__(req, link, data, **config)
        self.nw = data

    def create(self, req, network_id, **_kwargs):
        try:
            self.nw.create_network(network_id)
        except NetworkAlreadyExist:
            return Response(status=409)
        else:
            return Response(status=200)

    def update(self, req, network_id, **_kwargs):
        self.nw.update_network(network_id)
        return Response(status=200)

    def lists(self, req, **_kwargs):
        body = json.dumps(self.nw.list_networks())
        return Response(content_type='application/json', body=body)

    def delete(self, req, network_id, **_kwargs):
        try:
            self.nw.remove_network(network_id)
        except NetworkNotFound:
            return Response(status=404)

        return Response(status=200)


class PortController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(PortController, self).__init__(req, link, data, **config)
        self.nw = data

    def create(self, req, network_id, dpid, port_id, **_kwargs):
        try:
            self.nw.create_port(network_id, int(dpid, 16), int(port_id))
        except NetworkNotFound:
            return Response(status=404)
        except PortAlreadyExist:
            return Response(status=409)

        return Response(status=200)

    def update(self, req, network_id, dpid, port_id, **_kwargs):
        try:
            self.nw.update_port(network_id, int(dpid, 16), int(port_id))
        except NetworkNotFound:
            return Response(status=404)

        return Response(status=200)

    def lists(self, req, network_id, **_kwargs):
        try:
            body = json.dumps(self.nw.list_ports(network_id))
        except NetworkNotFound:
            return Response(status=404)

        return Response(content_type='application/json', body=body)

    def delete(self, req, network_id, dpid, port_id, **_kwargs):
        try:
            self.nw.remove_port(network_id, int(dpid, 16), int(port_id))
        except (NetworkNotFound, PortNotFound):
            return Response(status=404)

        return Response(status=200)


class MacController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(MacController, self).__init__(req, link, data, **config)
        self.nw = data

    def create(self, _req, network_id, dpid, port_id, mac_addr, **_kwargs):
        mac = mac_lib.haddr_to_bin(mac_addr)
        try:
            self.nw.create_mac(network_id, int(dpid, 16), int(port_id), mac)
        except PortNotFound:
            return Response(status=404)
        except MacAddressAlreadyExist:
            return Response(status=409)

        return Response(status=200)

    def update(self, _req, network_id, dpid, port_id, mac_addr, **_kwargs):
        mac = mac_lib.haddr_to_bin(mac_addr)
        try:
            self.nw.update_mac(network_id, int(dpid, 16), int(port_id), mac)
        except PortNotFound:
            return Response(status=404)

        return Response(status=200)

    def lists(self, _req, network_id, dpid, port_id, **_kwargs):
        try:
            body = json.dumps([mac_lib.haddr_to_str(mac_addr) for mac_addr in
                               self.nw.list_mac(int(dpid, 16), int(port_id))])
        except PortNotFound:
            return Response(status=404)

        return Response(content_type='application/json', body=body)


class restapi(app_manager.RyuApp):
    _CONTEXTS = {
        'network': network.Network,
        'wsgi': WSGIApplication
    }

    def __init__(self, *args, **kwargs):
        super(restapi, self).__init__(*args, **kwargs)
        self.nw = kwargs['network']
        wsgi = kwargs['wsgi']
        mapper = wsgi.mapper

        wsgi.registory['NetworkController'] = self.nw
        uri = '/v1.0/networks'
        mapper.connect('networks', uri,
                       controller=NetworkController, action='lists',
                       conditions=dict(method=['GET', 'HEAD']))

        uri += '/{network_id}'
        mapper.connect('networks', uri,
                       controller=NetworkController, action='create',
                       conditions=dict(method=['POST']))

        mapper.connect('networks', uri,
                       controller=NetworkController, action='update',
                       conditions=dict(method=['PUT']))

        mapper.connect('networks', uri,
                       controller=NetworkController, action='delete',
                       conditions=dict(method=['DELETE']))

        wsgi.registory['PortController'] = self.nw
        mapper.connect('networks', uri,
                       controller=PortController, action='lists',
                       conditions=dict(method=['GET']))

        uri += '/{dpid}_{port_id}'
        mapper.connect('ports', uri,
                       controller=PortController, action='create',
                       conditions=dict(method=['POST']))
        mapper.connect('ports', uri,
                       controller=PortController, action='update',
                       conditions=dict(method=['PUT']))

        mapper.connect('ports', uri,
                       controller=PortController, action='delete',
                       conditions=dict(method=['DELETE']))

        wsgi.registory['MacController'] = self.nw
        uri += '/macs'
        mapper.connect('macs', uri,
                       controller=MacController, action='lists',
                       conditions=dict(method=['GET']))

        uri += '/{mac_addr}'
        mapper.connect('macs', uri,
                       controller=MacController, action='create',
                       conditions=dict(method=['POST']))

        mapper.connect('macs', uri,
                       controller=MacController, action='update',
                       conditions=dict(method=['PUT']))
