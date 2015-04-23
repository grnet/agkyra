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

    def get(self, key):
        self._Lock.acquire()
        value = self._Dict.get(key)
        self._Lock.release()
        return value
