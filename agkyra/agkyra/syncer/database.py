from functools import wraps
import time
import sqlite3
import json
import logging
import random

from agkyra.syncer import common

logger = logging.getLogger(__name__)


class FileStateDB(object):

    def new_serial(self, objname):
        raise NotImplementedError

    def list_files(self, archive):
        raise NotImplementedError

    def put_state(self, state):
        raise NotImplementedError

    def get_state(self, archive, objname):
        raise NotImplementedError


class SqliteFileStateDB(FileStateDB):

    def __init__(self, dbname, initialize=False):
        self.dbname = dbname
        self.db = sqlite3.connect(dbname)
        if initialize:
            self.init()

    def init(self):
        logger.warning("Initializing DB '%s'" % self.dbname)
        db = self.db

        Q = ("create table if not exists "
             "archives(archive text, objname text, serial integer, "
             "info blob, primary key (archive, objname))")
        db.execute(Q)

        Q = ("create table if not exists "
             "serials(objname text, nextserial bigint, primary key (objname))")
        db.execute(Q)

        Q = ("create table if not exists "
             "cachenames(cachename text, client text, objname text, "
             "primary key (cachename))")
        db.execute(Q)

        self.commit()

    def begin(self):
        self.db.execute("begin")

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def get_cachename(self, cachename):
        db = self.db
        Q = "select * from cachenames where cachename = ?"
        c = db.execute(Q, (cachename,))
        r = c.fetchone()
        if r:
            return r
        else:
            return None

    def insert_cachename(self, cachename, client, objname):
        db = self.db
        Q = ("insert into cachenames(cachename, client, objname) "
             "values (?, ?, ?)")
        db.execute(Q, (cachename, client, objname))

    def delete_cachename(self, cachename):
        db = self.db
        Q = "delete from cachenames where cachename = ?"
        db.execute(Q, (cachename,))

    def new_serial(self, objname):
        db = self.db
        Q = ("select nextserial from serials where objname = ?")
        c = db.execute(Q, (objname,))
        r = c.fetchone()
        if r:
            serial = r[0]
            Q = "update serials set nextserial = ? where objname = ?"
        else:
            serial = 0
            Q = "insert into serials(nextserial, objname) values (?, ?)"
        db.execute(Q, (serial + 1, objname))
        return serial

    def list_files_with_info(self, archive, info):
        Q = ("select objname from archives where archive = ? and info = ?"
             " order by objname")
        c = self.db.execute(Q, (archive, info))
        fetchone = c.fetchone
        while True:
            r = fetchone()
            if not r:
                break
            yield r[0]

    def list_non_deleted_files(self, archive):
        Q = ("select objname from archives where archive = ? and info != '{}'"
             " order by objname")
        c = self.db.execute(Q, (archive,))
        fetchone = c.fetchone
        while True:
            r = fetchone()
            if not r:
                break
            yield r[0]

    def list_files(self, archive, prefix=None):
        Q = "select objname from archives where archive = ?"
        if prefix is not None:
            Q += " and objname like ?"
            tpl = (archive, prefix + '%')
        else:
            tpl = (archive,)

        Q += " order by objname"
        c = self.db.execute(Q, tpl)
        fetchone = c.fetchone
        while True:
            r = fetchone()
            if not r:
                break
            yield r[0]

    def list_deciding(self, archives, sync):
        if len(archives) == 1:
            archive = archives[0]
            archives = (archive, archive)
        archives = tuple(archives)
        Q = ("select client.objname from archives client, archives sync "
             "where client.archive in (?, ?) and sync.archive = ? "
             "and client.objname = sync.objname "
             "and client.serial > sync.serial")
        c = self.db.execute(Q, archives + (sync,))
        fetchone = c.fetchone
        while True:
            r = fetchone()
            if not r:
                break
            yield r[0]

    def put_state(self, state):
        Q = ("insert or replace into "
             "archives(archive, objname, serial, info) "
             "values (?, ?, ?, ?)")
        args = (state.archive, state.objname, state.serial,
                json.dumps(state.info))
        self.db.execute(Q, args)

    def _get_state(self, archive, objname):
        Q = ("select archive, objname, serial, info from archives "
             "where archive = ? and objname = ?")
        c = self.db.execute(Q, (archive, objname))
        r = c.fetchone()
        if not r:
            return None

        return common.FileState(archive=r[0], objname=r[1], serial=r[2],
                                info=json.loads(r[3]))

    def get_state(self, archive, objname):
        state = self._get_state(archive, objname)
        if state is None:
            state = common.FileState(
                archive=archive, objname=objname, serial=-1, info={})
        return state


def rand(lim):
    return random.random() * lim


def transaction(max_wait=60, init_wait=0.4, exp_backoff=1.1):
    def wrap(func):
        @wraps(func)
        def inner(*args, **kwargs):
            obj = args[0]
            db = obj.get_db()
            attempt = 0
            current_max_wait = init_wait
            while True:
                try:
                    db.begin()
                    r = func(*args, **kwargs)
                    db.commit()
                    return r
                except Exception as e:
                    db.rollback()
                    # TODO check conflict
                    if isinstance(e, sqlite3.OperationalError) and \
                            "locked" in e.message:
                        if current_max_wait <= max_wait:
                            attempt += 1
                            logger.warning(
                                "Got DB error '%s' while running '%s' "
                                "with args '%s' and kwargs '%s'. "
                                "Retrying transaction (%s times)." %
                                (e, func.__name__, args, kwargs, attempt))
                            time.sleep(rand(current_max_wait))
                            current_max_wait *= exp_backoff
                        else:
                            logger.error(
                                "Got DB error '%s' while running '%s' "
                                "with args '%s' and kwargs '%s'. Aborting." %
                                (e, func.__name__, args, kwargs))
                            return
                    else:
                        raise e
        return inner
    return wrap
