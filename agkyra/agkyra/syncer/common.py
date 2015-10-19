from collections import namedtuple

FileStateTuple = namedtuple('FileStateTuple',
                            ['archive', 'path', 'serial', 'info'])


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
