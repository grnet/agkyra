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


LOG = logging.getLogger(__name__)


class UIClient(WebSocketClient):
    """W Web Socket Client for Agkyra"""
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
        LOG.debug('Client exits with %s, %s' % code, reason)

    def wait_until_ready(self, timeout=20):
        """Wait until client is connected"""
        while not self.ready:
            time.sleep(1)
        assert self.ready, 'UI client timed out while waiting to be ready'
        return self.ready

    def received_message(self, m):
        """handle server responces according to the protocol"""
        msg = json.loads('%s' % m)
        {
            'post ui_id': self.recv_authenticate,
            'get status': self.recv_get_status
        }[msg['action']](msg)

    # Request handlers
    def send_get_status(self):
        """Request: GET STATUS"""
        self.send(json.dumps(dict(method='get', path='status')))

    # Receive handlers
    def recv_authenticate(self, msg):
        """Receive: client authentication response"""
        assert 'ACCEPTED' in msg, json.dumps(msg)
        self.ready = True

    def recv_get_status(self, msg):
        """Receive: GET STATUS"""
        assert 'can_sync' in msg, json.dumps(msg)
        self.buf[msg['action']] = msg

    # API methods
    def get_status(self):
        """Ask server for status, return status"""
        self.wait_until_ready()
        self.send_get_status()
        while 'get status' not in self.buf:
            time.sleep(1)
        return self.buf.pop('get status')
