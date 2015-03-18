from wsgiref.simple_server import make_server
# from ws4py.websocket import EchoWebSocket
from protocol import WebSocketProtocol
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from ws4py.server.wsgiutils import WebSocketWSGIApplication
from tempfile import NamedTemporaryFile
import subprocess
import json
from os.path import abspath

from ws4py.client import WebSocketBaseClient


class GUILauncher(WebSocketBaseClient):
    """Launch the GUI when the helper server is ready"""

    def __init__(self, port, gui_exec_path, token):
        super(GUILauncher, self).__init__('ws://localhost:%s' % port)
        self.port = port
        self.gui_exec_path = gui_exec_path
        self.token = token

    def handshake_ok(self):
        with NamedTemporaryFile(mode='a+') as fp:
            json.dump(dict(token=self.token, port=self.port), fp)
            fp.flush()
            subprocess.call([
                '/home/saxtouri/node-webkit-v0.11.6-linux-x64/nw',
                abspath('gui/gui.nw'),
                fp.name])


class Helper(object):
    """Coordination between the GUI and the Syncer instances

    Setup a minimal server at a ephemeral port, create a random token, dump
    this information in a local file and launch the GUI with this file as a
    parameter.
    Then the GUI connects and a WebSocket is established.

    """

    def __init__(self, gui_exec_path, port=0):
        self.server = self.setup_server(port)
        self.port = self.server.server_port
        self.token = 'some random token'
        self.gui_exec_path = gui_exec_path

    def setup_server(self, port=0):
        server = make_server(
            '', port,
            server_class=WSGIServer,
            handler_class=WebSocketWSGIRequestHandler,
            app=WebSocketWSGIApplication(handler_cls=WebSocketProtocol))
        server.initialize_websockets_manager()
        # self.port = server.server_port
        return server

    def run(self):
        gui = GUILauncher(self.port, self.gui_exec_path, self.token)
        gui.connect()
        self.server.serve_forever()

Helper('ls').run()
