#!/usr/bin/env python
# -*- coding: utf-8 -*-
from threading import Lock

from .. import db, variables as v

PLEXDB_LOCK = Lock()

SUPPORTED_KODI_TYPES = (
    v.KODI_TYPE_MOVIE,
    v.KODI_TYPE_SHOW,
    v.KODI_TYPE_SEASON,
    v.KODI_TYPE_EPISODE,
    v.KODI_TYPE_ARTIST,
    v.KODI_TYPE_ALBUM,
    v.KODI_TYPE_SONG
)


class PlexDBBase(object):
    """
    Plex database methods used for all types of items.
    """
    def __init__(self, plexconn=None, lock=True, copy=False):
        # Allows us to use this class with a cursor instead of context mgr
        self.plexconn = plexconn
        self.cursor = self.plexconn.cursor() if self.plexconn else None
        self.lock = lock
        self.copy = copy

    def __enter__(self):
        if self.lock:
            PLEXDB_LOCK.acquire()
        self.plexconn = db.connect('plex-copy' if self.copy else 'plex')
        self.cursor = self.plexconn.cursor()
        return self

    def __exit__(self, e_typ, e_val, trcbak):
        try:
            if e_typ:
                # re-raise any exception
                return False
            self.plexconn.commit()
        finally:
            self.plexconn.close()
            if self.lock:
                PLEXDB_LOCK.release()

    def is_recorded(self, plex_id, plex_type):
        """
        FAST method to check whether a plex_id has already been recorded
        """
        self.cursor.execute('SELECT plex_id FROM %s WHERE plex_id = ?' % plex_type,
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def item_by_id(self, plex_id, plex_type=None):
        """
        Returns the item for plex_id or None.
        Supply with the correct plex_type to speed up lookup
        """
        answ = None
        if plex_type == v.PLEX_TYPE_MOVIE:
            answ = self.movie(plex_id)
        elif plex_type == v.PLEX_TYPE_EPISODE:
            answ = self.episode(plex_id)
        elif plex_type == v.PLEX_TYPE_SHOW:
            answ = self.show(plex_id)
        elif plex_type == v.PLEX_TYPE_SEASON:
            answ = self.season(plex_id)
        elif plex_type == v.PLEX_TYPE_SONG:
            answ = self.song(plex_id)
        elif plex_type == v.PLEX_TYPE_ALBUM:
            answ = self.album(plex_id)
        elif plex_type == v.PLEX_TYPE_ARTIST:
            answ = self.artist(plex_id)
        elif plex_type in (v.PLEX_TYPE_CLIP, v.PLEX_TYPE_PHOTO, v.PLEX_TYPE_PLAYLIST):
            # Will never be synched to Kodi
            pass
        elif plex_type is None:
            # SLOW - lookup plex_id in all our tables
            for kind in (v.PLEX_TYPE_MOVIE,
                         v.PLEX_TYPE_EPISODE,
                         v.PLEX_TYPE_SHOW,
                         v.PLEX_TYPE_SEASON,
                         'song',  # darn
                         v.PLEX_TYPE_ALBUM,
                         v.PLEX_TYPE_ARTIST):
                method = getattr(self, kind)
                answ = method(plex_id)
                if answ:
                    break
        return answ

    def items_by_guid(self, plex_guid, plex_type=None):
        """
        Returns a list of items for plex_guid or an empty list.
        Supply with the correct plex_type to speed up lookup
        """
        answ = list()
        if plex_type == v.PLEX_TYPE_MOVIE:
            answ = self.movies_by_guid(plex_guid)
        elif plex_type == v.PLEX_TYPE_EPISODE:
            answ = self.episodes_by_guid(plex_guid)
        elif plex_type == v.PLEX_TYPE_SHOW:
            answ = self.shows_by_guid(plex_guid)
        elif plex_type == v.PLEX_TYPE_SEASON:
            answ = self.seasons_by_guid(plex_guid)
        elif plex_type is None:
            # SLOW - lookup plex_id in all our tables
            for kind in (v.PLEX_TYPE_MOVIE,
                         v.PLEX_TYPE_EPISODE,
                         v.PLEX_TYPE_SHOW,
                         v.PLEX_TYPE_SEASON):
                method = getattr(self, kind + "s_by_guid")
                answ = method(plex_guid)
                if answ:
                    break
        return answ

    def item_by_kodi_id(self, kodi_id, kodi_type):
        """
        """
        if kodi_type not in SUPPORTED_KODI_TYPES:
            return
        self.cursor.execute('SELECT * from %s WHERE kodi_id = ? LIMIT 1'
                            % v.PLEX_TYPE_FROM_KODI_TYPE[kodi_type],
                            (kodi_id, ))
        method = getattr(self, 'entry_to_%s' % v.PLEX_TYPE_FROM_KODI_TYPE[kodi_type])
        return method(self.cursor.fetchone())

    def plex_id_by_last_sync(self, plex_type, last_sync, limit):
        """
        Returns an iterator for all items where the last_sync is NOT identical
        """
        query = '''
            SELECT plex_id FROM %s WHERE last_sync <> ? LIMIT %s
        ''' % (plex_type, limit)
        return (x[0] for x in self.cursor.execute(query, (last_sync, )))

    def checksum(self, plex_id, plex_type):
        """
        Returns the checksum for plex_id
        """
        self.cursor.execute('SELECT checksum FROM %s WHERE plex_id = ? LIMIT 1' % plex_type,
                            (plex_id, ))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    def update_last_sync(self, plex_id, plex_type, last_sync):
        """
        Sets a new timestamp for plex_id
        """
        self.cursor.execute('UPDATE %s SET last_sync = ? WHERE plex_id = ?' % plex_type,
                            (last_sync, plex_id))

    def remove(self, plex_id, plex_type):
        """
        Removes the item from our Plex db
        """
        self.cursor.execute('DELETE FROM %s WHERE plex_id = ?' % plex_type, (plex_id, ))

    def every_plex_id(self, plex_type, offset, limit):
        """
        Returns an iterator for plex_type for every single plex_id
        Will start with records at DB position offset [int] and return limit
        [int] number of items
        """
        return (x[0] for x in
                self.cursor.execute('SELECT plex_id FROM %s LIMIT %s OFFSET %s'
                                    % (plex_type, limit, offset)))

    def missing_fanart(self, plex_type, offset, limit):
        """
        Returns an iterator for plex_type for all plex_id, where fanart_synced
        has not yet been set to 1
        Will start with records at DB position offset [int] and return limit
        [int] number of items
        """
        query = '''
            SELECT plex_id FROM %s WHERE fanart_synced = 0
            LIMIT %s OFFSET %s
        ''' % (plex_type, limit, offset)
        return (x[0] for x in self.cursor.execute(query))

    def missing_trailers(self, plex_type, offset, limit):
        """
        Returns an iterator for plex_type for all plex_id, where trailer_synced
        has not yet been set to 1
        Will start with records at DB position offset [int] and return limit
        [int] number of items
        """
        query = '''
            SELECT plex_id FROM %s WHERE trailer_synced = 0
            LIMIT %s OFFSET %s
        ''' % (plex_type, limit, offset)
        return (x[0] for x in self.cursor.execute(query))

    def set_fanart_synced(self, plex_id, plex_type):
        """
        Toggles fanart_synced to 1 for plex_id
        """
        self.cursor.execute('UPDATE %s SET fanart_synced = 1 WHERE plex_id = ?' % plex_type,
                            (plex_id, ))

    def set_trailer_synced(self, plex_id, plex_type):
        """
        Toggles fanart_synced to 1 for plex_id
        """
        self.cursor.execute('UPDATE %s SET trailer_synced = 1 WHERE plex_id = ?' % plex_type,
                            (plex_id, ))

    def plexid_by_sectionid(self, section_id, plex_type, limit):
        query = '''
            SELECT plex_id FROM %s WHERE section_id = ? LIMIT %s
        ''' % (plex_type, limit)
        return (x[0] for x in self.cursor.execute(query, (section_id, )))

    def kodiid_by_sectionid(self, section_id, plex_type):
        return (x[0] for x in
                self.cursor.execute('SELECT kodi_id FROM %s WHERE section_id = ?' % plex_type,
                                    (section_id, )))


def initialize():
        """
        Run once upon PKC startup to verify that plex db exists.
        """
        with PlexDBBase() as plexdb:
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS version(
                    idVersion TEXT PRIMARY KEY)
            ''')
            plexdb.cursor.execute('''
                INSERT OR REPLACE INTO version(idVersion)
                VALUES (?)
            ''', (v.ADDON_VERSION, ))
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS sections(
                    section_id INTEGER PRIMARY KEY,
                    section_name TEXT,
                    plex_type TEXT,
                    kodi_tagid INTEGER,
                    sync_to_kodi INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS movie(
                    plex_id INTEGER PRIMARY KEY,
                    plex_guid TEXT,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    kodi_id INTEGER,
                    kodi_fileid INTEGER,
                    kodi_pathid INTEGER,
                    fanart_synced INTEGER,
                    trailer_synced BOOLEAN,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS show(
                    plex_id INTEGER PRIMARY KEY,
                    plex_guid TEXT,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    kodi_id INTEGER,
                    kodi_pathid INTEGER,
                    fanart_synced INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS season(
                    plex_id INTEGER PRIMARY KEY,
                    plex_guid TEXT,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    show_id INTEGER,
                    parent_id INTEGER,
                    kodi_id INTEGER,
                    fanart_synced INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS episode(
                    plex_id INTEGER PRIMARY KEY,
                    plex_guid TEXT,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    show_id INTEGER,
                    grandparent_id INTEGER,
                    season_id INTEGER,
                    parent_id INTEGER,
                    kodi_id INTEGER,
                    kodi_fileid INTEGER,
                    kodi_fileid_2 INTEGER,
                    kodi_pathid INTEGER,
                    fanart_synced INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS artist(
                    plex_id INTEGER PRIMARY KEY,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    kodi_id INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS album(
                    plex_id INTEGER PRIMARY KEY,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    artist_id INTEGER,
                    parent_id INTEGER,
                    kodi_id INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS track(
                    plex_id INTEGER PRIMARY KEY,
                    checksum INTEGER UNIQUE,
                    section_id INTEGER,
                    artist_id INTEGER,
                    grandparent_id INTEGER,
                    album_id INTEGER,
                    parent_id INTEGER,
                    kodi_id INTEGER,
                    kodi_pathid INTEGER,
                    last_sync INTEGER)
            ''')
            plexdb.cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists(
                    plex_id INTEGER PRIMARY KEY,
                    plex_name TEXT,
                    plex_updatedat INTEGER,
                    kodi_path TEXT,
                    kodi_type TEXT,
                    kodi_hash TEXT)
            ''')
            # DB indicees for faster lookups
            commands = (
                'CREATE INDEX IF NOT EXISTS ix_movie_1 ON movie (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_movie_2 ON movie (kodi_id)',
                'CREATE INDEX IF NOT EXISTS ix_movie_3 ON movie (plex_guid)',
                'CREATE INDEX IF NOT EXISTS ix_show_1 ON show (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_show_2 ON show (kodi_id)',
                'CREATE INDEX IF NOT EXISTS ix_show_3 ON show (plex_guid)',
                'CREATE INDEX IF NOT EXISTS ix_season_1 ON season (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_season_2 ON season (kodi_id)',
                'CREATE INDEX IF NOT EXISTS ix_season_3 ON season (plex_guid)',
                'CREATE INDEX IF NOT EXISTS ix_episode_1 ON episode (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_episode_2 ON episode (kodi_id)',
                'CREATE INDEX IF NOT EXISTS ix_episode_3 ON season (plex_guid)',
                'CREATE INDEX IF NOT EXISTS ix_artist_1 ON artist (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_artist_2 ON artist (kodi_id)',
                'CREATE INDEX IF NOT EXISTS ix_album_1 ON album (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_album_2 ON album (kodi_id)',
                'CREATE INDEX IF NOT EXISTS ix_track_1 ON track (last_sync)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_track_2 ON track (kodi_id)',
                'CREATE UNIQUE INDEX IF NOT EXISTS ix_playlists_2 ON playlists (kodi_path)',
                'CREATE INDEX IF NOT EXISTS ix_playlists_3 ON playlists (kodi_hash)',
            )
            for cmd in commands:
                plexdb.cursor.execute(cmd)


def wipe(table=None):
    """
    Completely resets the Plex database.
    If a table [unicode] name is provided, only that table will be dropped
    """
    with PlexDBBase() as plexdb:
        if table:
            tables = [table]
        else:
            plexdb.cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            tables = [i[0] for i in plexdb.cursor.fetchall()]
        for table in tables:
            plexdb.cursor.execute('DROP table IF EXISTS %s' % table)
