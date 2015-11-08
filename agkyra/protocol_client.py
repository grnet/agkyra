# Copyright (C) 2015 GRNET S.A.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from ws4py.client.threadedclient import WebSocketClient
import json
import time
import logging
import random
from protocol import STATUS


LOG = logging.getLogger(__name__)


class UIClientError(Exception):
    """UIClient Exception class"""


class TimeOutError(UIClientError):
    """A client request timed out"""

class UnexpectedResponseError(UIClientError):
    """The protocol server response was not as expected"""

    def __init__(self, *args, **kw):
        """:param response: a keyword argument containing the repsonse"""
        self.response = kw.pop('response', None)
        super(UnexpectedResponseError, self).__init__(*args, **kw)


class UIClient(WebSocketClient):
    """Web Socket Client for Agkyra"""
    buf, authenticated, ready = {}, False, False

    def __init__(self, session):
        self.ui_id = session['ui_id']
        super(UIClient, self).__init__(session['address'])

    def opened(self):
        """On connection, authenticate or close"""
        if self.ui_id:
            self.send(json.dumps(dict(method='post', ui_id=self.ui_id)))
        else:
            self.close()

    def closed(self, code, reason):
        """After the client is closed"""
        LOG.debug('Client exits with %s, %s' % (code, reason))

    def wait_until_ready(self, timeout=20):
        """Wait until client is connected"""
        while timeout and not self.ready:
            time.sleep(1)
            timeout -= 1
        if not self.ready:
            raise TimeOutError('UI client timed out while waiting to be ready')
        return self.ready

    def wait_until_syncing(self, timeout=20):
        """Wait until session reaches syncing status"""
        status = self.get_status()
        while timeout and status['code'] != STATUS['SYNCING']:
            time.sleep(1)
            status = self.get_status()
            timeout -= 1
        if status['code'] != STATUS['SYNCING']:
            raise TimeOutError('Still not syncing')

    def wait_until_paused(self, timeout=20):
        """Wait until session reaches paused status"""
        status = self.get_status()
        while timeout and status['code'] != STATUS['PAUSED']:
            time.sleep(1)
            status = self.get_status()
            timeout -= 1
        if status['code'] != STATUS['PAUSED']:
            raise TimeOutError('Still not paused')

    def received_message(self, m):
        """handle server responces according to the protocol"""
        msg = json.loads('%s' % m)
        {
            'post ui_id': self.recv_authenticate,
            'post init': self.recv_init,
            'post start': self.recv_start,
            'post pause': self.recv_pause,
            'get status': self.recv_get_status,
        }[msg['action']](msg)

    # Request handlers
    def send_get_status(self):
        """Request: GET STATUS"""
        self.send(json.dumps(dict(method='get', path='status')))

    # Receive handlers
    def recv_authenticate(self, msg):
        """Receive: client authentication response"""
        if 'ACCEPTED' not in msg:
            raise UnexpectedResponseError(
                'Client authentication failed', response=msg)
        self.ready = True

    def recv_init(self, msg):
        """Receive: init response"""
        if 'OK' not in msg:
            raise UnexpectedResponseError('Init failed', response=msg)

    def recv_start(self, msg):
        """Receive: start response"""
        if 'OK' not in msg:
            raise UnexpectedResponseError('Start failed', response=msg)

    def recv_pause(self, msg):
        """Receive: start response"""
        if 'OK' not in msg:
            raise UnexpectedResponseError('Pause failed', response=msg)

    def recv_get_status(self, msg):
        """Receive: GET STATUS"""
        if 'code' not in msg:
            raise UnexpectedResponseError('Get status failed', response=msg)
        self.buf[msg['action']] = msg

    # API methods
    def get_status(self):
        """Ask server for status, return status"""
        self.wait_until_ready()
        self.send_get_status()
        while 'get status' not in self.buf:
            time.sleep(random.random())
        return self.buf.pop('get status')

    def _post(self, path):
        """send json with action=POST and path=path"""
        self.send(json.dumps(dict(method='post', path=path)))

    def shutdown(self):
        """Request: POST SHUTDOWN"""
        self.wait_until_ready()
        self._post('shutdown')

    def init(self):
        """Request: POST INIT"""
        self.wait_until_ready()
        self._post('init')

    def start(self):
        """Request: POST START"""
        self.wait_until_ready()
        self._post('start')

    def pause(self):
        """Request: POST PAUSE"""
        self.wait_until_ready()
        self._post('pause')
