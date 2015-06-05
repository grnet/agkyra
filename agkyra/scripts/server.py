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

import os

from agkyra import config
AGKYRA_DIR = config.AGKYRA_DIR

import logging
LOGFILE = os.path.join(AGKYRA_DIR, 'agkyra.log')
LOGGER = logging.getLogger('agkyra')
HANDLER = logging.FileHandler(LOGFILE)
FORMATTER = logging.Formatter("%(name)s %(levelname)s:%(asctime)s:%(message)s")
HANDLER.setFormatter(FORMATTER)
LOGGER.addHandler(HANDLER)
LOGGER.setLevel(logging.INFO)


def main():
    from agkyra.protocol import SessionHelper
    LOGGER.debug('Start the session helper')
    helper = SessionHelper()
    if not helper.load_active_session():
        helper.create_session()
        helper.server.serve_forever()
    else:
        LOGGER.info('Another session is running, aborting')
        exit(1)


if __name__ == "__main__":
    main()