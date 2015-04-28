import os
import hashlib
import datetime
import watchdog.utils

from agkyra.syncer.common import OBJECT_DIRSEP

BUF_SIZE = 65536


def to_local_sep(filename):
    return filename.replace(OBJECT_DIRSEP, os.path.sep)


def to_standard_sep(filename):
    return filename.replace(os.path.sep, OBJECT_DIRSEP)


def join_path(dirpath, filename):
    return os.path.join(dirpath, to_local_sep(filename))


def join_objname(prefix, filename):
    if prefix != "":
        prefix = prefix.rstrip(OBJECT_DIRSEP) + OBJECT_DIRSEP
    return prefix + filename


def hash_string(s):
    return hashlib.sha256(s).hexdigest()


def hash_file(filename, block_size=BUF_SIZE):
    sha256 = hashlib.sha256()
    with open(filename, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()


def time_stamp():
    return datetime.datetime.now().strftime("%s.%f")


def younger_than(tstamp, seconds):
    now = datetime.datetime.now()
    ts = datetime.datetime.fromtimestamp(int(float(tstamp)))
    delta = now - ts
    return delta < datetime.timedelta(seconds=seconds)


BaseStoppableThread = watchdog.utils.BaseThread


class StoppableThread(BaseStoppableThread):
    def run_body(self):
        raise NotImplementedError()

    def run(self):
        while True:
            if not self.should_keep_running():
                return
            self.run_body()


def start_daemon(threadClass):
    thread = threadClass()
    thread.daemon = True
    thread.start()
    return thread
