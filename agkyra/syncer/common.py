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

OBJECT_DIRSEP = '/'


DBTuple = namedtuple('DBTuple',
                     ['dbtype', 'dbname'])

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


class NotStableBusyError(BusyError):
    pass


class OpenBusyError(BusyError):
    pass


class ChangedBusyError(BusyError):
    pass


class ConflictError(SyncError):
    pass


class InvalidInput(SyncError):
    pass


class HandledError(SyncError):
    pass


class DatabaseError(SyncError):
    pass


class HardSyncError(SyncError):
    pass


class CollisionError(HardSyncError):
    pass
