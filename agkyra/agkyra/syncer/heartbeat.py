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
