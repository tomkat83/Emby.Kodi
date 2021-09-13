#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sqlite3
from functools import wraps

from . import variables as v, app
from .exceptions import LockedDatabase

DB_WRITE_ATTEMPTS = 100
DB_WRITE_ATTEMPTS_TIMEOUT = 1  # in seconds
DB_CONNECTION_TIMEOUT = 10


def catch_operationalerrors(method):
    """
    sqlite.OperationalError is raised immediately if another DB connection
    is open, reading something that we're trying to change

    So let's catch it and try again

    Also see https://github.com/mattn/go-sqlite3/issues/274
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        attempts = DB_WRITE_ATTEMPTS
        while True:
            try:
                return method(self, *args, **kwargs)
            except sqlite3.OperationalError as err:
                if err.args[0] and 'database is locked' not in err.args[0]:
                    # Not an error we want to catch, so reraise it
                    raise
                attempts -= 1
                if attempts == 0:
                    # Reraise in order to NOT catch nested OperationalErrors
                    raise LockedDatabase('Database is locked')
                # Need to close the transactions and begin new ones
                self.kodiconn.commit()
                if self.artconn:
                    self.artconn.commit()
                if app.APP.monitor.waitForAbort(DB_WRITE_ATTEMPTS_TIMEOUT):
                    # PKC needs to quit
                    return
                # Start new transactions
                self.kodiconn.execute('BEGIN')
                if self.artconn:
                    self.artconn.execute('BEGIN')
    return wrapper


def _initial_db_connection_setup(conn):
    """
    Set-up DB e.g. for WAL journal mode, if that hasn't already been done
    before. Also start a transaction
    """
    conn.execute('PRAGMA journal_mode = WAL;')
    conn.execute('PRAGMA cache_size = -8000;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    conn.execute('BEGIN')


def connect(media_type=None):
    """
    Open a connection to the Kodi database.
        media_type: 'video' (standard if not passed), 'plex', 'music', 'texture'
    """
    if media_type == "plex":
        db_path = v.DB_PLEX_PATH
    elif media_type == 'plex-copy':
        db_path = v.DB_PLEX_COPY_PATH
    elif media_type == "music":
        db_path = v.DB_MUSIC_PATH
    elif media_type == "texture":
        db_path = v.DB_TEXTURE_PATH
    else:
        db_path = v.DB_VIDEO_PATH
    conn = sqlite3.connect(db_path,
                           timeout=DB_CONNECTION_TIMEOUT,
                           isolation_level=None)
    attempts = DB_WRITE_ATTEMPTS
    while True:
        try:
            _initial_db_connection_setup(conn)
        except sqlite3.OperationalError as err:
            if 'database is locked' not in err:
                # Not an error we want to catch, so reraise it
                raise
            attempts -= 1
            if attempts == 0:
                # Reraise in order to NOT catch nested OperationalErrors
                raise LockedDatabase('Database is locked')
            if app.APP.monitor.waitForAbort(0.05):
                # PKC needs to quit
                raise LockedDatabase('Database was locked and we need to exit')
        else:
            break
    return conn
