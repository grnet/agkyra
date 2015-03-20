from ws4py.websocket import WebSocket
import json
import logging


LOG = logging.getLogger(__name__)


class WebSocketProtocol(WebSocket):
    """Helper-side WebSocket protocol for communication with GUI:

    -- INTERRNAL HANDSAKE --
    GUI: {"method": "post", "gui_id": <GUI ID>}
    HELPER: {"ACCEPTED": 202}" or "{"REJECTED": 401}

    -- SHUT DOWN --
    GUI: {"method": "post", "path": "shutdown"}

    -- GET SETTINGS --
    GUI: {"method": "get", "path": "settings"}
    HELPER:
        {
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
            "exclude": <file path>
        }
    HELPER: {"CREATED": 201} or {<ERROR>: <ERROR CODE>}

    -- GET STATUS --
    GUI: {"method": "get", "path": "status"}
    HELPER: ""progress": <int>, "paused": <boolean>} or {<ERROR>: <ERROR CODE>}
    """

    gui_id = None
    accepted = False

    # Syncer-related methods
    def get_status(self):
        self.progress = getattr(self, 'progress', -1)
        self.progress += 1
        return dict(progress=self.progress, paused=False)

    def get_settings(self):
        return dict(
            token='token',
            url='http://www.google.com',
            container='pithos',
            directory='~/tmp',
            exclude='agkyra.log')

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
        if self.accepted:
            if r['path'] == 'shutdown':
                self.close()
            raise KeyError()
        elif r['gui_id'] == self.gui_id:
            self.accepted = True
            self.send_json({'ACCEPTED': 202})
        else:
            self.send_json({'REJECTED': 401})
            self.terminate()

    def _put(self, r):
        """Handle PUT requests"""
        if not self.accepted:
            self.send_json({'UNAUTHORIZED': 401})
            self.terminate()
        else:
            LOG.debug('put %s' % r)

    def _get(self, r):
        """Handle GET requests"""
        if not self.accepted:
            self.send_json({'UNAUTHORIZED': 401})
            self.terminate()
        else:
            data = {
                'settings': self.get_settings,
                'status': self.get_status,
            }[r.pop('path')]()
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
            {
                'post': self._post,
                'put': self._put,
                'get': self._get
            }[r.pop('method')](r)
        except KeyError as ke:
            self.send_json({'BAD REQUEST': 400})
            LOG.error('KEY ERROR: %s' % ke)
        except Exception as e:
            self.send_json({'INTERNAL ERROR': 500})
            LOG.error('EXCEPTION: %s' % e)
            self.terminate()
