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

from ws4py.client import WebSocketBaseClient
from agkyra.protocol import HelperServer
from tempfile import NamedTemporaryFile
import subprocess
import json
import os
import logging

CURPATH = os.path.dirname(os.path.abspath(__file__))
LOG = logging.getLogger(__name__)


class GUI(WebSocketBaseClient):
    """Launch the GUI when the helper server is ready"""

    def __init__(self, addr, gui_id, **kwargs):
        """Initialize the GUI Launcher"""
        super(GUI, self).__init__(addr)
        self.addr = addr
        self.gui_id = gui_id
        self.start = self.connect
        self.nw = kwargs.get(
            'nw', os.path.join(os.path.join(CURPATH, 'nwjs'), 'nw'))
        self.gui_code = kwargs.get('gui_code', os.path.join(CURPATH, 'gui.nw'))

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
        subprocess.call([self.nw, self.gui_code, fp.name])
        LOG.debug('GUI process closed, remove temp file')
        os.remove(fp.name)

    def handshake_ok(self):
        """If handshake is OK, the helper is UP, so the GUI can be launched"""
        self.run_gui()
        LOG.debug('Close GUI wrapper connection')
        self.close()


def run():
    """Prepare helper and GUI and run them in the proper order"""
    server = HelperServer()
    gui = GUI(server.addr, server.gui_id)

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
    run(os.path.abspath('gui/app'))
