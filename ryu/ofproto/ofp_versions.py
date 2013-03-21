# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2013 Isaku Yamahata <yamahata at valinux co jp>
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

OFP_VERSION_TO_STRING = {
    0x01: '1.0',
    0x02: '1.1',
    0x03: '1.2',
    0x04: '1.3',
}


def ofp_version_string(ofp_version):
    version_string = OFP_VERSION_TO_STRING.get(ofp_version, None)
    if not version_string:
        return 'Unknown version of wire protocol 0x%02x' % ofp_version
    return 'OpenFlow version %s (wire protocol 0x%02x)' % (version_string,
                                                           ofp_version)
