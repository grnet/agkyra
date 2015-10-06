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

import time
try:
    import pysqlite2.dbapi2 as sqlite3
except ImportError:
    import sqlite3
import json
import logging
import random
import threading
import datetime
import inspect

from agkyra.syncer import common, utils

logger = logging.getLogger(__name__)

logger.debug("sqlite3.version = %s" % sqlite3.version)
logger.debug("sqlite3.sqlite_version = %s" % sqlite3.sqlite_version)

thread_local_data = threading.local()


class DB(object):
    def __init__(self, dbname, initialize=False):
        self.dbname = dbname
        self.db = sqlite3.connect(dbname)
        if initialize:
            self.init()

    def begin(self):
        self.db.execute("begin immediate")

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()


class ClientDB(DB):
    def init(self):
        logger.info("Initializing DB '%s'" % self.dbname)
        db = self.db

        Q = ("create table if not exists "
             "cachenames(cachename text, client text, objname text, "
             "primary key (cachename))")
        db.execute(Q)

        self.commit()

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


class SyncerDB(DB):
    def init(self):
        logger.info("Initializing DB '%s'" % self.dbname)
        db = self.db

        Q = ("create table if not exists "
             "archives(archive text, objname text, serial integer, "
             "info blob, primary key (archive, objname))")
        db.execute(Q)

        Q = ("create table if not exists "
             "serials(objname text, nextserial bigint, primary key (objname))")
        db.execute(Q)

        Q = ("create table if not exists "
             "config(key text, value text, primary key (key))")
        db.execute(Q)

        self.commit()

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

    def get_dir_contents(self, archive, objname):
        Q = ("select objname from archives where archive = ? and info != '{}'"
             " and objname like ?")
        c = self.db.execute(Q, (archive, utils.join_objname(objname, '%')))
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

    def get_config(self, key):
        Q = "select value from config where key = ?"
        c = self.db.execute(Q, (key,))
        r = c.fetchone()
        if not r:
            return None
        return json.loads(r[0])

    def set_config(self, key, value):
        Q = "insert or replace into config(key, value) values (?, ?)"
        self.db.execute(Q, (key, json.dumps(value)))

    def purge_archives(self):
        self.db.execute("delete from archives")
        self.db.execute("delete from serials")


def rand(lim):
    return random.random() * lim


def get_db(dbtuple, initialize=False):
    dbname = dbtuple.dbname
    dbtype = dbtuple.dbtype
    dbs = getattr(thread_local_data, "dbs", None)
    if dbs is not None:
        db = dbs.get(dbname)
    else:
        db = None

    if db is None:
        logger.debug("Connecting db: '%s', thread: %s" %
                     (dbname, threading.current_thread().ident))
        db = dbtype(dbname, initialize=initialize)
        if dbs is None:
            thread_local_data.dbs = {}
        thread_local_data.dbs[dbname] = db
    return db


def initialize(dbtuple):
    return get_db(dbtuple, initialize=True)


class TransactedConnection(object):
    def __init__(self, dbtuple, max_wait=60, init_wait=0.4, exp_backoff=1.1):
        self.db = get_db(dbtuple)
        self.max_wait = max_wait
        self.init_wait = init_wait
        self.exp_backoff = exp_backoff

    def __enter__(self):
        attempt = 0
        current_max_wait = self.init_wait
        total_wait = 0
        while True:
            try:
                curframe = inspect.currentframe()
                calframe = inspect.getouterframes(curframe, 2)
                caller_name = calframe[1][3]
                tbefore = datetime.datetime.now()
                self.db.begin()
                tafter = datetime.datetime.now()
                logger.debug("BEGIN %s %s" % (tafter-tbefore, caller_name))
                return self.db
            except sqlite3.Error as e:
                tfail = datetime.datetime.now()
                self.db.rollback()
                if isinstance(e, sqlite3.OperationalError) and \
                   "locked" in e.message:
                    if total_wait <= self.max_wait:
                        attempt += 1
                        logger.warning(
                            "Got DB error '%s' while beginning transaction %s "
                            "after %s sec. Retrying (%s times)." %
                            (e, caller_name, tfail-tbefore, attempt))
                        sleeptime = rand(current_max_wait)
                        total_wait += sleeptime
                        time.sleep(sleeptime)
                        current_max_wait *= self.exp_backoff
                    else:
                        logger.error(
                            "Got DB error '%s' while beginning transaction %s. "
                            "Aborting." %
                            (e, caller_name))
                        raise common.DatabaseError(e)
                else:
                    logger.error(
                        "Got sqlite3 error '%s while beginning transaction %s. "
                        "Aborting." %
                        (e, caller_name))
                    raise common.DatabaseError(e)

    def __exit__(self, exctype, value, traceback):
        if value is not None:
            try:
                self.db.rollback()
            finally:
                if issubclass(exctype, sqlite3.Error):
                    raise common.DatabaseError(value)
                return False  # re-raise
        else:
            try:
                self.db.commit()
            except sqlite3.Error as e:
                try:
                    self.db.rollback()
                finally:
                    raise common.DatabaseError(e)
