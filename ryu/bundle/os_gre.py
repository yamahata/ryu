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

from ryu.base import main as ryu_main
ryu_main.early_init()

from ryu.base import app_manager


class OpenStackGRETunnel(app_manager.RyuBundle):
    APPS = [
        'ryu.controller.ofp_handler',
        'ryu.app.gre_tunnel.GRETunnel',
        'ryu.app.tunnel_port_updater.TunnelPortUpdater',
        'ryu.app.quantum_adapter.QuantumAdapter',
        'ryu.app.rest.RestAPI',
        'ryu.app.rest_conf_switch.ConfSwitchAPI',
        'ryu.app.rest_tunnel.TunnelAPI',
        'ryu.app.rest_quantum.QuantumIfaceAPI',
    ]


if __name__ == '__main__':
    ryu_main.main([OpenStackGRETunnel], True)
