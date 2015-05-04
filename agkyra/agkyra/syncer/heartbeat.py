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

import threading


class HeartBeat(object):
    def __init__(self, *args, **kwargs):
        self._LOG = {}
        self._LOCK = threading.Lock()

    def lock(self):
        class Lock(object):
            def __enter__(this):
                self._LOCK.acquire()
                return this

            def __exit__(this, exctype, value, traceback):
                self._LOCK.release()
                if value is not None:
                    raise value

            def get(this, key):
                return self._LOG.get(key)

            def set(this, key, value):
                self._LOG[key] = value

            def delete(this, key):
                self._LOG.pop(key)

        return Lock()
