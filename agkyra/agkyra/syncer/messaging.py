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
        self.serial = kwargs["serial"]
        self.logger.info("Updating archive: %s, object: '%s', serial: %s" %
                         (self.archive, self.objname, self.serial))


class SyncMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.archive = kwargs["archive"]
        self.serial = kwargs["serial"]
        self.logger.info("Syncing archive: %s, object: '%s', serial: %s" %
                         (self.archive, self.objname, self.serial))


class AckSyncMessage(Message):
    def __init__(self, *args, **kwargs):
        Message.__init__(self, *args, **kwargs)
        self.objname = kwargs["objname"]
        self.archive = kwargs["archive"]
        self.serial = kwargs["serial"]
        self.logger.info("Acked archive: %s, object: '%s', serial: %s" %
                         (self.archive, self.objname, self.serial))


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
