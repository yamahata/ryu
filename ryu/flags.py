# Copyright (C) 2011, 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011, 2013 Isaku Yamahata <yamahata at valinux co jp>
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
"""
global flags
"""

from oslo.config import cfg


# module does CONF.register_cli_options() on load
def _register_cli_options(module_name):
    try:
        __import__(module_name)
    except ImportError:
        pass


_register_cli_options('ryu.app.quantum_adapter')
_register_cli_options('ryu.app.wsgi')
_register_cli_options('ryu.log')
_register_cli_options('ryu.topology.switches')
# Add modules that call CONF.register_cli_options()


# global options
CONF = cfg.CONF
# nothing yet
# CONF.register_cli_options(...)
# CONF.register_options(...)
