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

from collections import namedtuple
import threading

OBJECT_DIRSEP = '/'


FileStateTuple = namedtuple('FileStateTuple',
                            ['archive', 'objname', 'serial', 'info'])


class FileState(FileStateTuple):

    __slots__ = ()

    def set(self, *args, **kwargs):
        return self._replace(*args, **kwargs)


T_DIR = "dir"
T_FILE = "file"
T_UNHANDLED = "unhandled"


class SyncError(Exception):
    pass


class BusyError(SyncError):
    pass


class ConflictError(SyncError):
    pass


class InvalidInput(SyncError):
    pass


class HandledError(SyncError):
    pass


class HardSyncError(SyncError):
    pass


class CollisionError(HardSyncError):
    pass


class LockedDict(object):
    def __init__(self, *args, **kwargs):
        self._Dict = {}
        self._Lock = threading.Lock()

    def put(self, key, value):
        self._Lock.acquire()
        self._Dict[key] = value
        self._Lock.release()

    def get(self, key, default=None):
        self._Lock.acquire()
        value = self._Dict.get(key, default=default)
        self._Lock.release()
        return value

    def pop(self, key, d=None):
        self._Lock.acquire()
        value = self._Dict.pop(key, d)
        self._Lock.release()
        return value

    def update(self, d):
        self._Lock.acquire()
        self._Dict.update(d)
        self._Lock.release()

    def keys(self):
        self._Lock.acquire()
        value = self._Dict.keys()
        self._Lock.release()
        return value
