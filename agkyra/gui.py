from wsgiref.simple_server import make_server
# from ws4py.websocket import EchoWebSocket
from protocol import WebSocketProtocol
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication
from ws4py.client import WebSocketBaseClient
from tempfile import NamedTemporaryFile
import subprocess
import json
from os.path import abspath
from threading import Thread
from hashlib import sha1
import os
import logging


LOG = logging.getLogger(__name__)


class GUI(WebSocketBaseClient):
    """Launch the GUI when the helper server is ready"""

    def __init__(self, addr, gui_exec_path, gui_id):
        """Initialize the GUI Launcher"""
        super(GUI, self).__init__(addr)
        self.addr = addr
        self.gui_exec_path = gui_exec_path
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
        LOG.debug('RUN: %s %s' % (self.gui_exec_path, fp.name))
        subprocess.call([
            '/home/saxtouri/node-webkit-v0.11.6-linux-x64/nw',
            # self.gui_exec_path,
            abspath('gui/gui.nw'),
            fp.name])
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


def run(gui_exec_path):
    """Prepare helper and GUI and run them in the proper order"""
    server = HelperServer()
    addr = 'ws://localhost:%s' % server.port
    gui = GUI(addr, gui_exec_path, server.gui_id)

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
