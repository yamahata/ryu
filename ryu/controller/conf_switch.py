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

import logging

from ryu.controller import (dispatcher,
                            event)
from ryu.lib.dpid import dpid_to_str


LOG = logging.getLogger(__name__)


QUEUE_NAME_CONF_SWITCH_EV = 'conf_switch'
DISPATCHER_NAME_CONF_SWTICH_EV = 'conf_switch_handler'
CONF_SWITCH_EV_DISPATCHER = dispatcher.EventDispatcher(
    DISPATCHER_NAME_CONF_SWTICH_EV)


class EventConfSwitchDelDPID(event.EventBase):
    def __init__(self, dpid):
        super(EventConfSwitchDelDPID, self).__init__()
        self.dpid = dpid

    def __str__(self):
        return 'EventConfSwitchDelDPID<%s>' % dpid_to_str(self.dpid)


class EventConfSwitchSet(event.EventBase):
    def __init__(self, dpid, key, value):
        super(EventConfSwitchSet, self).__init__()
        self.dpid = dpid
        self.key = key
        self.value = value

    def __str__(self):
        return 'EventConfSwitchSet<%s, %s, %s>' % (
            dpid_to_str(self.dpid), self.key, self.value)


class EventConfSwitchDel(event.EventBase):
    def __init__(self, dpid, key):
        super(EventConfSwitchDel, self).__init__()
        self.dpid = dpid
        self.key = key

    def __str__(self):
        return 'EventConfSwitchDel<%s, %s>' % (dpid_to_str(self.dpid),
                                               self.key)


class ConfSwitchSet(object):
    def __init__(self):
        super(ConfSwitchSet, self).__init__()
        self.ev_q = dispatcher.EventQueue(QUEUE_NAME_CONF_SWITCH_EV,
                                          CONF_SWITCH_EV_DISPATCHER)
        self.confs = {}

    def dpids(self):
        return self.confs.keys()

    def del_dpid(self, dpid):
        self.ev_q.queue(EventConfSwitchDelDPID(dpid))
        del self.confs[dpid]

    def keys(self, dpid):
        return self.confs[dpid].keys()

    def set_key(self, dpid, key, value):
        conf = self.confs.setdefault(dpid, {})
        conf[key] = value
        self.ev_q.queue(EventConfSwitchSet(dpid, key, value))

    def get_key(self, dpid, key):
        return self.confs[dpid][key]

    def del_key(self, dpid, key):
        self.ev_q.queue(EventConfSwitchDel(dpid, key))
        del self.confs[dpid][key]

    # methods for TunnelUpdater
    def __contains__(self, (dpid, key)):
        """(dpid, key) in <ConfSwitchSet instance>"""
        return dpid in self.confs and key in self.confs[dpid]

    def find_dpid(self, key, value):
        for dpid, conf in self.confs.items():
            if key in conf:
                if conf[key] == value:
                    return dpid

        return None
