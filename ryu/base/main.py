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


from ryu.lib import hub


_EARLY_INITED = False


def early_init():
    global _EARLY_INITED
    if _EARLY_INITED:
        return
    _EARLY_INITED = True

    hub.patch()

    # TODO:
    #   Right now, we have our own patched copy of ovs python bindings
    #   Once our modification is upstreamed and widely deployed,
    #   use it
    #
    # NOTE: this modifies sys.path and thus affects the following imports.
    # eg. oslo.config.cfg.
    import ryu.contrib

    import logging
    from ryu import log
    log.early_init_log(logging.DEBUG)


_INITIED = False


def init():
    global _INITIED
    if _INITIED:
        return
    _INITIED = True

    from oslo.config import cfg
    CONF = cfg.CONF
    CONF.register_cli_opts([
        cfg.MultiStrOpt('app', positional=True, default=[],
                        help='application module name to run'),
        cfg.BoolOpt('cgitb', default=False,
                    help='enable cgitb for more comprehensive traceback'),
    ])

    import ryu.flags    # to load common options
    from ryu import version
    CONF(project='ryu', version='ryu-manager %s' % version)

    from ryu import log
    log.init_log()
    if CONF.cgitb:
        import cgitb
        cgitb.enable(format='text')


def main(app_lists, run_of_controller=True):
    init()

    from oslo.config import cfg
    app_lists.extend(cfg.CONF.app)

    from ryu.base.app_manager import AppManager
    app_mgr = AppManager()
    app_mgr.load_apps(app_lists)
    contexts = app_mgr.create_contexts()
    app_mgr.instantiate_apps(**contexts)

    services = []

    if run_of_controller:
        from ryu.controller import controller
        ctlr = controller.OpenFlowController()
        thr = hub.spawn(ctlr)
        services.append(thr)

    from ryu.app import wsgi
    webapp = wsgi.start_service(app_mgr)
    if webapp:
        thr = hub.spawn(webapp)
        services.append(thr)

    try:
        app_mgr.joinall()
        hub.joinall(services)
    finally:
        app_mgr.close()
