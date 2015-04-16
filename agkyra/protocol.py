from ws4py.websocket import WebSocket
import json
import logging
from os.path import abspath
from titanic import syncer


LOG = logging.getLogger(__name__)


class WebSocketProtocol(WebSocket):
    """Helper-side WebSocket protocol for communication with GUI:

    -- INTERRNAL HANDSAKE --
    GUI: {"method": "post", "gui_id": <GUI ID>}
    HELPER: {"ACCEPTED": 202, "method": "post"}" or
        "{"REJECTED": 401, "action": "post gui_id"}

    -- SHUT DOWN --
    GUI: {"method": "post", "path": "shutdown"}

    -- PAUSE --
    GUI: {"method": "post", "path": "pause"}
    HELPER: {"OK": 200, "action": "post pause"} or error

    -- start --
    GUI: {"method": "post", "path": "start"}
    HELPER: {"OK": 200, "action": "post start"} or error

    -- GET SETTINGS --
    GUI: {"method": "get", "path": "settings"}
    HELPER:
        {
            "action": "get settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>
        } or {<ERROR>: <ERROR CODE>}

    -- PUT SETTINGS --
    GUI: {
            "method": "put", "path": "settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "pithos_url": <pithos URL>,
            "exclude": <file path>
        }
    HELPER: {"CREATED": 201, "action": "put settings",} or
        {<ERROR>: <ERROR CODE>, "action": "get settings",}

    -- GET STATUS --
    GUI: {"method": "get", "path": "status"}
    HELPER: {"progress": <int>, "paused": <boolean>, "action": "get status"} or
        {<ERROR>: <ERROR CODE>, "action": "get status"}
    """

    gui_id = None
    accepted = False
    settings = dict(
        token='token',
        url='https://accounts.okeanos.grnet.gr/identity/v2.0',
        container='pithos',
        directory='/tmp/.',
        exclude=abspath('exclude.cnf'),
        pithos_url='https://pithos.okeanos.grnet.gr/ui/',
        weblogin='https://accounts.okeanos.grnet.gr/ui')
    status = dict(progress=0, paused=True)
    file_syncer = None

    # Syncer-related methods
    def get_status(self):
        from random import randint
        if self.status['progress'] < 100:
            self.status['progress'] += 0 if randint(0, 2) else 1
        return self.status

    def get_settings(self):
        return self.settings

    def set_settings(self, new_settings):
        self.settings = new_settings

    def pause_sync(self):
        self.status['paused'] = True

    def start_sync(self):
        self.status['paused'] = False

    # WebSocket connection methods
    def opened(self):
        LOG.debug('Helper: connection established')

    def closed(self, *args):
        LOG.debug('Helper: connection closed')

    def send_json(self, msg):
        LOG.debug('send: %s' % msg)
        self.send(json.dumps(msg))

    # Protocol handling methods
    def _post(self, r):
        """Handle POST requests"""
        LOG.debug('CALLED with %s' % r)
        if self.accepted:
            action = r['path']
            if action == 'shutdown':
                self.close()
                return
            {
                'start': self.start_sync,
                'pause': self.pause_sync
            }[action]()
            self.send_json({'OK': 200, 'action': 'post %s' % action})
        elif r['gui_id'] == self.gui_id:
            self.accepted = True
            self.send_json({'ACCEPTED': 202, 'action': 'post gui_id'})
        else:
            action = r.get('path', 'gui_id')
            self.send_json({'REJECTED': 401, 'action': 'post %s' % action})
            self.terminate()

    def _put(self, r):
        """Handle PUT requests"""
        if not self.accepted:
            action = r['path']
            self.send_json({'UNAUTHORIZED': 401, 'action': 'put %s' % action})
            self.terminate()
        else:
            LOG.debug('put %s' % r)
            action = r.pop('path')
            self.set_settings(r)
            r.update({'CREATED': 201, 'action': 'put %s' % action})
            self.send_json(r)

    def _get(self, r):
        """Handle GET requests"""
        action = r.pop('path')
        if not self.accepted:
            self.send_json({'UNAUTHORIZED': 401, 'action': 'get %s' % action})
            self.terminate()
        else:
            data = {
                'settings': self.get_settings,
                'status': self.get_status,
            }[action]()
            data['action'] = 'get %s' % action
            self.send_json(data)

    def received_message(self, message):
        """Route requests to corresponding handling methods"""
        LOG.debug('recv: %s' % message)
        try:
            r = json.loads('%s' % message)
        except ValueError as ve:
            self.send_json({'BAD REQUEST': 400})
            LOG.error('JSON ERROR: %s' % ve)
            return
        try:
            method = r.pop('method')
            {
                'post': self._post,
                'put': self._put,
                'get': self._get
            }[method](r)
        except KeyError as ke:
            self.send_json({'BAD REQUEST': 400})
            LOG.error('KEY ERROR: %s' % ke)
        except Exception as e:
            self.send_json({'INTERNAL ERROR': 500})
            LOG.error('EXCEPTION: %s' % e)
            self.terminate()
