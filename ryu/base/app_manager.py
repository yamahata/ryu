# Copyright (C) 2011, 2012 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2011 Isaku Yamahata <yamahata at valinux co jp>
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

import inspect
import itertools
import logging
import traceback

from ryu import utils
from ryu.controller.handler import register_instance
from ryu.controller import event
from ryu.controller.event import EventRequestBase, EventReplyBase
from ryu.lib import hub

LOG = logging.getLogger('ryu.base.app_manager')

SERVICE_BRICKS = {}


def _load_cls(parent_clses, name):
    try:
        mod = utils.import_module(name)
    except ImportError:
        try:
            cls = utils.import_class(name)
        except ImportError, e:
            LOG.debug('ImportError %s %s', e, traceback.format_exc())
            return None
        if not issubclass(cls, parent_clses):
            return None
        return cls

    clses = inspect.getmembers(
        mod, lambda cls: (inspect.isclass(cls) and
                          issubclass(cls, parent_clses)))
    if clses:
        return clses[0][1]
    return None


def _load_bundle_cls(name):
    return _load_cls(RyuBundle, name)


def _load_app_cls(name):
    return _load_cls(RyuApp, name)


def lookup_service_brick(name):
    return SERVICE_BRICKS.get(name)


def register_app(app):
    assert isinstance(app, RyuApp)
    assert not app.name in SERVICE_BRICKS
    SERVICE_BRICKS[app.name] = app
    register_instance(app)


def unregister_app(app):
    SERVICE_BRICKS.pop(app.name)


class RyuApp(object):
    """
    Base class for Ryu network application
    """
    _CONTEXTS = {}
    _EVENTS = []  # list of events to be generated in app

    @classmethod
    def context_iteritems(cls):
        """
        Return iterator over the (key, contxt class) of application context
        """
        return cls._CONTEXTS.iteritems()

    def __init__(self, *_args, **_kwargs):
        super(RyuApp, self).__init__()
        self.name = self.__class__.__name__
        self.event_handlers = {}        # ev_cls -> handlers:list
        self.observers = {}     # ev_cls -> observer-name -> states:set
        self.threads = []
        self.events = hub.Queue(128)
        self.replies = hub.Queue()
        self.logger = logging.getLogger(self.name)

        # prevent accidental creation of instances of this class outside RyuApp
        class _EventThreadStop(event.EventBase):
            pass
        self._event_stop = _EventThreadStop()
        self.is_active = True

    def start(self):
        """
        Hook that is called after startup initialization is done.
        """
        self.threads.append(hub.spawn(self._event_loop))

    def stop(self):
        self.is_active = False
        self._send_event(self._event_stop)
        hub.joinall(self.threads)

    def joinall(self):
        hub.joinall(self.threads)

    def register_handler(self, ev_cls, handler):
        assert callable(handler)
        self.event_handlers.setdefault(ev_cls, [])
        self.event_handlers[ev_cls].append(handler)

    def register_observer(self, ev_cls, name, states=None):
        states = states or set()
        ev_cls_observers = self.observers.setdefault(ev_cls, {})
        ev_cls_observers.setdefault(name, set()).update(states)

    def unregister_observer(self, ev_cls, name):
        observers = self.observers.get(ev_cls, {})
        observers.pop(name)

    def unregister_observer_all_event(self, name):
        for observers in self.observers.values():
            observers.pop(name, None)

    def get_handlers(self, ev, state=None):
        handlers = self.event_handlers.get(ev.__class__, [])
        if state is None:
            return handlers

        return [handler for handler in handlers
                if not handler.dispatchers or state in handler.dispatchers]

    def get_observers(self, ev, state):
        observers = []
        for k, v in self.observers.get(ev.__class__, {}).iteritems():
            if not state or not v or state in v:
                observers.append(k)

        return observers

    def send_reply(self, rep):
        assert isinstance(rep, EventReplyBase)
        SERVICE_BRICKS[rep.dst].replies.put(rep)

    def send_request(self, req):
        assert isinstance(req, EventRequestBase)
        req.sync = True
        self.send_event(req.dst, req)
        # going to sleep for the reply
        return self.replies.get()

    def _event_loop(self):
        while self.is_active or not self.events.empty():
            ev, state = self.events.get()
            if ev == self._event_stop:
                continue
            handlers = self.get_handlers(ev, state)
            for handler in handlers:
                handler(ev)

    def _send_event(self, ev, state):
        self.events.put((ev, state))

    def send_event(self, name, ev, state=None):
        if name in SERVICE_BRICKS:
            if isinstance(ev, EventRequestBase):
                ev.src = self.name
            LOG.debug("EVENT %s->%s %s %s" %
                      (self.name, name, ev.__class__.__name__, state))
            SERVICE_BRICKS[name]._send_event(ev, state)
        else:
            LOG.debug("EVENT LOST %s->%s %s %s" %
                      (self.name, name, ev.__class__.__name__, state))

    def send_event_to_observers(self, ev, state=None):
        for observer in self.get_observers(ev, state):
            self.send_event(observer, ev, state)

    def reply_to_request(self, req, rep):
        rep.dst = req.src
        if req.sync:
            self.send_reply(rep)
        else:
            self.send_event(rep.dst, rep)

    def close(self):
        """
        teardown method.
        The method name, close, is chosen for python context manager
        """
        pass


class RyuBundle(object):
    APPS = []


def _split(str_or_class):
    if inspect.isclass(str_or_class):
        return [str_or_class]
    assert isinstance(str_or_class, basestring)
    return str_or_class.split(',')


class AppManager(object):
    # singletone
    _instance = None

    @staticmethod
    def get_instance():
        if not AppManager._instance:
            AppManager._instance = AppManager()
        return AppManager._instance

    def __init__(self):
        self.applications_cls = {}
        self.applications = {}
        self.contexts_cls = {}
        self.contexts = {}

    def _setup_app(self, app_cls_name, app_cls):
        # for now, only single instance of a given module
        # Do we need to support multiple instances?
        # Yes, maybe for slicing.
        assert app_cls_name not in self.applications_cls
        assert issubclass(app_cls, RyuApp)
        self.applications_cls[app_cls_name] = app_cls

        for key, context_cls in app_cls.context_iteritems():
            cls = self.contexts_cls.setdefault(key, context_cls)
            assert cls == context_cls

    def load_apps(self, app_lists):
        bundle_loaded_apps = {}

        for str_or_cls in itertools.chain.from_iterable([_split(app_list)
                                                         for app_list
                                                         in app_lists]):
            if inspect.isclass(str_or_cls):
                cls = str_or_cls
                cls_name = cls.__name__
            else:
                cls = None
                cls_name = str_or_cls

            # for now, only single instance of a given module
            # Do we need to support multiple instances?
            # Yes, maybe for slicing.
            assert cls_name not in self.applications_cls
            LOG.info('loading app %s', cls_name)

            if cls is None:
                cls = _load_bundle_cls(cls_name)
                if cls is None:
                    cls = _load_app_cls(cls_name)
                    if cls is None:
                        continue

            if issubclass(cls, RyuBundle):
                for app_cls in cls.APPS:
                    if isinstance(app_cls, basestring):
                        app_name = app_cls
                        LOG.info('loading class %s', app_name)
                        app_cls = _load_app_cls(app_name)
                        if app_cls is None:
                            raise ValueError('class %s can be loaded' %
                                             app_name)
                    else:
                        app_name = app_cls.__name__
                    bundle_loaded_apps.setdefault(app_name, app_cls)
                    assert bundle_loaded_apps[app_name] == app_cls
                continue

            self._setup_app(cls_name, cls)

        LOG.debug('bundle_loaded_apps %s', bundle_loaded_apps)
        for cls_name, cls in bundle_loaded_apps.iteritems():
            if cls_name not in self.applications_cls:
                self._setup_app(cls_name, cls)

    def create_contexts(self):
        for key, cls in self.contexts_cls.items():
            if issubclass(cls, RyuApp):
                # hack for dpset
                context = self._instantiate(None, cls)
            else:
                context = cls()
            LOG.info('creating context %s', key)
            assert not key in self.contexts
            self.contexts[key] = context
        return self.contexts

    def _update_bricks(self):
        for i in SERVICE_BRICKS.values():
            for _k, m in inspect.getmembers(i, inspect.ismethod):
                if not hasattr(m, 'observer'):
                    continue

                # name is module name of ev_cls
                name = m.observer.split('.')[-1]
                if name in SERVICE_BRICKS:
                    brick = SERVICE_BRICKS[name]
                    brick.register_observer(m.ev_cls, i.name, m.dispatchers)

                # allow RyuApp and Event class are in different module
                for brick in SERVICE_BRICKS.itervalues():
                    if m.ev_cls in brick._EVENTS:
                        brick.register_observer(m.ev_cls, i.name,
                                                m.dispatchers)

    @staticmethod
    def _report_brick(name, app):
        LOG.debug("BRICK %s" % name)
        for ev_cls, list_ in sorted(app.observers.items(),
                                    key=lambda e: e[0].__name__):
            LOG.debug("  PROVIDES %s TO %s" % (ev_cls.__name__, list_))
        for ev_cls in sorted(app.event_handlers.keys(),
                             key=lambda ev_cls: ev_cls.__name__):
            LOG.debug("  CONSUMES %s" % (ev_cls.__name__,))

    @staticmethod
    def report_bricks():
        for brick, i in sorted(SERVICE_BRICKS.items()):
            AppManager._report_brick(brick, i)

    def _instantiate(self, app_name, cls, *args, **kwargs):
        # for now, only single instance of a given module
        # Do we need to support multiple instances?
        # Yes, maybe for slicing.
        LOG.info('instantiating app %s of %s', app_name, cls.__name__)

        # avoid circular import
        from ryu.controller.controller import Datapath
        if hasattr(cls, 'OFP_VERSIONS'):
            for k in Datapath.supported_ofp_version.keys():
                if not k in cls.OFP_VERSIONS:
                    del Datapath.supported_ofp_version[k]

        assert len(Datapath.supported_ofp_version), \
            'No OpenFlow version is available'

        if app_name is not None:
            assert app_name not in self.applications
        app = cls(*args, **kwargs)
        register_app(app)
        assert app.name not in self.applications
        self.applications[app.name] = app
        return app

    def instantiate(self, cls, *args, **kwargs):
        app = self._instantiate(None, cls, *args, **kwargs)
        self._update_bricks()
        self._report_brick(app.name, app)
        return app

    def instantiate_apps(self, *args, **kwargs):
        for app_name, cls in self.applications_cls.items():
            self._instantiate(app_name, cls, *args, **kwargs)

        self._update_bricks()
        self.report_bricks()

        for app in self.applications.values():
            app.start()

    @staticmethod
    def _close(app):
        close_method = getattr(app, 'close', None)
        if callable(close_method):
            close_method()

    def uninstantiate(self, name):
        app = self.applications.pop(name)
        unregister_app(app)
        for app_ in SERVICE_BRICKS.values():
            app_.unregister_observer_all_event(name)
        app.stop()
        self._close(app)
        events = app.events
        if not events.empty():
            app.logger.debug('%s events remians %d', app.name, events.qsize())

    def close(self):
        def close_all(close_dict):
            for app in close_dict.values():
                self._close(app)
            close_dict.clear()

        close_all(self.applications)
        close_all(self.contexts)

    def joinall(self):
        for app in self.applications.values():
            app.joinall()
