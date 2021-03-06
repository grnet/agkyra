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

import Queue

from agkyra.syncer import utils


class Messager(object):
    def __init__(self, *args, **kwargs):
        self.queue = Queue.Queue()

    def put(self, obj):
        return self.queue.put(obj)

    def get(self, **kwargs):
        try:
            return self.queue.get(**kwargs)
        except Queue.Empty:
            return None


class Message(object):
    def __init__(self, *args, **kwargs):
        self.tstamp = utils.time_stamp()
        self.logger = kwargs["logger"]
        self.name = self.__class__.__name__


class UpdateMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.archive = kwargs["archive"]
        self.objname = kwargs["objname"]
        self.old_serial = kwargs["old_serial"]
        self.serial = kwargs["serial"]
        self.logger.info("Updating archive: %s, object: '%s', serial: %s" %
                         (self.archive, self.objname, self.serial))


class IgnoreProbeMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.archive = kwargs["archive"]
        self.objname = kwargs["objname"]
        self.logger.warning("Ignoring probe archive: %s, object: %s" %
                            (self.archive, self.objname))


class AlreadyProbedMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.archive = kwargs["archive"]
        self.objname = kwargs["objname"]
        self.serial = kwargs["serial"]
        self.logger.debug("Already probed archive: %s, "
                          "object: '%s'" % (self.archive, self.objname))


class HeartbeatNoProbeMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.archive = kwargs["archive"]
        self.objname = kwargs["objname"]
        self.heartbeat = kwargs["heartbeat"]
        self.logger.debug("Object '%s' is being synced; "
                          "Probe in archive %s aborted." %
                          (self.objname, self.archive))


class HeartbeatNoDecideMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.heartbeat = kwargs["heartbeat"]
        self.logger.debug("Object '%s' already handled; aborting deciding."
                          % self.objname)


class HeartbeatReplayDecideMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.heartbeat = kwargs["heartbeat"]
        self.logger.info("Found heartbeat with current ident %s"
                         % self.heartbeat["ident"])


class HeartbeatSkipDecideMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.heartbeat = kwargs["heartbeat"]
        self.logger.debug("Skipping decide due to recent failure: %s" %
                          self.objname)


class FailedSyncIgnoreDecisionMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.serial = kwargs["serial"]
        self.logger.warning(
            "Ignoring failed decision for: '%s', decision: %s" %
            (self.objname, self.serial))


class LiveInfoUpdateMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.archive = kwargs["archive"]
        self.objname = kwargs["objname"]
        self.info = kwargs["info"]
        self.logger.warning("Actual info differs in %s for object: '%s'; "
                            "updating..." % (self.archive, self.objname))


class SyncMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.archive = kwargs["archive"]
        self.serial = kwargs["serial"]
        self.info = kwargs["info"]
        self.logger.info("Syncing archive: %s, object: '%s', serial: %s"
                         % (self.archive, self.objname, self.serial))


class AckSyncMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.archive = kwargs["archive"]
        self.serial = kwargs["serial"]
        self.logger.info("Acked archive: %s, object: '%s', serial: %s" %
                         (self.archive, self.objname, self.serial))


class SyncErrorMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.serial = kwargs["serial"]
        self.exception = kwargs["exception"]
        self.logger.warning(
            "Sync failed; object: '%s' serial: %s error: %s"
            % (self.objname, self.serial, self.exception))


class CollisionMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.etag = kwargs["etag"]
        self.logger.warning(
            "Failed to upload; object: '%s' with etag: %s "
            "collided with upstream" % (self.objname, self.etag))


class ConflictStashMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.stash_name = kwargs["stash_name"]
        self.logger.warning("Stashing file '%s' to '%s'" %
                            (self.objname, self.stash_name))


class LocalfsSyncDisabled(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.logger.warning("Localfs sync is disabled")


class PithosSyncDisabled(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.logger.warning("Pithos sync is disabled")


class LocalfsSyncEnabled(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.logger.info("Localfs sync is enabled")


class PithosSyncEnabled(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.logger.info("Pithos sync is enabled")


class PithosGenericError(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.exc = kwargs["exc"]
        self.logger.error(self.exc)


class PithosAuthTokenError(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.exc = kwargs["exc"]
        self.logger.error(self.exc)
