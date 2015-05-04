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

from wsgiref.simple_server import make_server
# from ws4py.websocket import EchoWebSocket
from agkyra.protocol import WebSocketProtocol
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication
from ws4py.client import WebSocketBaseClient
from tempfile import NamedTemporaryFile
import subprocess
import json
from os.path import abspath, join
from threading import Thread
from hashlib import sha1
import os
import logging

CURPATH = os.path.dirname(os.path.abspath(__file__))

LOG = logging.getLogger(__name__)


class GUI(WebSocketBaseClient):
    """Launch the GUI when the helper server is ready"""

    def __init__(self, addr, gui_id):
        """Initialize the GUI Launcher"""
        super(GUI, self).__init__(addr)
        self.addr = addr
        self.gui_id = gui_id
        self.start = self.connect

    def run_gui(self):
        """Launch the GUI and keep it running, clean up afterwards.
        If the GUI is terminated for some reason, the WebSocket is closed and
        the temporary file with GUI settings is deleted.
        In windows, the file must be closed before the GUI is launched.
        """
        # NamedTemporaryFile creates a file accessible only to current user
        LOG.debug('Create temporary file')
        with NamedTemporaryFile(delete=False) as fp:
            json.dump(dict(gui_id=self.gui_id, address=self.addr), fp)
        # subprocess.call blocks the execution
        LOG.debug('RUN: %s' % (fp.name))
        subprocess.call([
            os.path.join(os.path.join(CURPATH, 'nwjs'), 'nw'),
            os.path.join(CURPATH, 'gui.nw'),
            fp.name,
            '--data-path', abspath('~/.agkyra')])
        LOG.debug('GUI process closed, remove temp file')
        os.remove(fp.name)

    def handshake_ok(self):
        """If handshake is OK, the helper is UP, so the GUI can be launched"""
        self.run_gui()
        LOG.debug('Close GUI wrapper connection')
        self.close()


class HelperServer(object):
    """Agkyra Helper Server sets a WebSocket server with the Helper protocol
    It also provided methods for running and killing the Helper server
    :param gui_id: Only the GUI with this ID is allowed to chat with the Helper
    """

    def __init__(self, port=0):
        """Setup the helper server"""
        self.gui_id = sha1(os.urandom(128)).hexdigest()
        WebSocketProtocol.gui_id = self.gui_id
        server = make_server(
            '', port,
            server_class=WSGIServer,
            handler_class=WebSocketWSGIRequestHandler,
            app=WebSocketWSGIApplication(handler_cls=WebSocketProtocol))
        server.initialize_websockets_manager()
        self.server, self.port = server, server.server_port

    def start(self):
        """Start the helper server in a thread"""
        Thread(target=self.server.serve_forever).start()

    def shutdown(self):
        """Shutdown the server (needs another thread) and join threads"""
        t = Thread(target=self.server.shutdown)
        t.start()
        t.join()


def run():
    """Prepare helper and GUI and run them in the proper order"""
    server = HelperServer()
    addr = 'ws://localhost:%s' % server.port
    gui = GUI(addr, server.gui_id)

    LOG.info('Start helper server')
    server.start()

    try:
        LOG.info('Start GUI')
        gui.start()
    except KeyboardInterrupt:
        LOG.info('Shutdown GUI')
        gui.close()
    LOG.info('Shutdown helper server')
    server.shutdown()

if __name__ == '__main__':
    logging.basicConfig(filename='agkyra.log', level=logging.DEBUG)
    run(abspath('gui/app'))
