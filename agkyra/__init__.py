from wsgiref.simple_server import make_server
# from ws4py.websocket import EchoWebSocket
from protocol import WebSocketProtocol
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication
from tempfile import NamedTemporaryFile
import subprocess
import json
from os.path import abspath
from threading import Thread
from hashlib import sha256
from os import urandom

from ws4py.client import WebSocketBaseClient


class GUILauncher(WebSocketBaseClient):
    """Launch the GUI when the helper server is ready"""

    def __init__(self, addr, gui_exec_path, token):
        """Initialize the GUI Launcher"""
        super(GUILauncher, self).__init__(addr)
        self.addr = addr
        self.gui_exec_path = gui_exec_path
        self.token = token

    def handshake_ok(self):
        """If handshake is OK, the helper is UP, so the GUI can be launched
        If the GUI is terminated for some reason, the WebSocket is closed"""
        with NamedTemporaryFile(mode='a+') as fp:
            json.dump(dict(token=self.token, address=self.addr), fp)
            fp.flush()
            # subprocess.call blocks the execution
            subprocess.call([
                '/home/saxtouri/node-webkit-v0.11.6-linux-x64/nw',
                abspath('gui/gui.nw'),
                fp.name])
        self.close()


def setup_server(token, port=0):
    """Setup and return the helper server"""
    WebSocketProtocol.token = token
    server = make_server(
        '', port,
        server_class=WSGIServer,
        handler_class=WebSocketWSGIRequestHandler,
        app=WebSocketWSGIApplication(handler_cls=WebSocketProtocol))
    server.initialize_websockets_manager()
    # self.port = server.server_port
    return server


def random_token():
    return 'random token'


def run(gui_exec_path):
    """Prepare helper and GUI and run them in the proper order"""
    token = sha256(urandom(256)).hexdigest()
    server = setup_server(token)
    addr = 'ws://localhost:%s' % server.server_port

    gui = GUILauncher(addr, gui_exec_path, token)
    Thread(target=gui.connect).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print 'Shutdown GUI'
        gui.close()

if __name__ == '__main__':
    run('/home/saxtouri/node-webkit-v0.11.6-linux-x64/nw gui.nw')
