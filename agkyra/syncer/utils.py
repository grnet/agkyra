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
import hashlib
import datetime
import threading
import watchdog.utils
import sys
import logging
import platform

logger = logging.getLogger(__name__)

from agkyra.syncer.common import OBJECT_DIRSEP

ENCODING = sys.getfilesystemencoding() or 'UTF-8'
PLATFORM = sys.platform
NODE = platform.node()

def iswin():
    return PLATFORM.startswith("win")


def islinux():
    return PLATFORM.startswith("linux")


def isosx():
    return PLATFORM.startswith("darwin")


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


def normalize_standard_suffix(path):
    return path.rstrip(OBJECT_DIRSEP) + OBJECT_DIRSEP


def normalize_local_suffix(path):
    return path.rstrip(os.path.sep) + os.path.sep


def from_unicode(s):
    if type(s) is unicode:
        return s.encode(ENCODING)
    return s


def to_unicode(s):
    if type(s) is unicode:
        return s
    try:
        return unicode(s, ENCODING)
    except UnicodeDecodeError as e:
        logger.warning("Failed to decode %s" % s.__repr__())
        raise


def hash_string(s):
    s = from_unicode(s)
    return hashlib.sha256(s).hexdigest()


def time_stamp():
    return datetime.datetime.now()


def str_time_stamp():
    return time_stamp().isoformat().replace(':', '.')


def younger_than(tstamp, seconds):
    now = datetime.datetime.now()
    delta = now - tstamp
    return delta < datetime.timedelta(seconds=seconds)


def reg_name(settings, objname):
    if settings.case_insensitive:
        return objname.lower()
    return objname


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


class ThreadSafeDict(object):
    def __init__(self, *args, **kwargs):
        self._DICT = {}
        self._LOCK = threading.Lock()

    def lock(self):
        class Lock(object):
            def __enter__(this):
                self._LOCK.acquire()
                return self._DICT

            def __exit__(this, exctype, value, traceback):
                self._LOCK.release()
                if value is not None:
                    return False  # re-raise
        return Lock()
