#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from ntpath import dirname

from ..plex_db import PlexDB, PLEXDB_LOCK
from ..kodi_db import KodiVideoDB, KODIDB_LOCK
from .. import db, timing, app

LOG = getLogger('PLEX.itemtypes.common')

# Note: always use same order of URL arguments, NOT urlencode:
#   plex_id=<plex_id>&plex_type=<plex_type>&mode=play


def process_path(playurl):
    """
    Do NOT use os.path since we have paths that might not apply to the current
    OS!
    """
    if '\\' in playurl:
        # Local path
        path = '%s\\' % playurl
        toplevelpath = '%s\\' % dirname(dirname(path))
    else:
        # Network path
        path = '%s/' % playurl
        toplevelpath = '%s/' % dirname(dirname(path))
    return path, toplevelpath


class ItemBase(object):
    """
    Items to be called with "with Items() as xxx:" to ensure that __enter__
    method is called (opens db connections)

    Input:
        kodiType:       optional argument; e.g. 'video' or 'music'
    """
    def __init__(self, last_sync, plexdb=None, kodidb=None, lock=True):
        self.last_sync = last_sync
        self.lock = lock
        self.plexdb = plexdb
        self.kodidb = kodidb
        self.plexconn = plexdb.plexconn if plexdb else None
        self.plexcursor = plexdb.cursor if plexdb else None
        self.kodiconn = kodidb.kodiconn if kodidb else None
        self.kodicursor = kodidb.cursor if kodidb else None
        self.artconn = kodidb.artconn if kodidb else None
        self.artcursor = kodidb.artcursor if kodidb else None

    def __enter__(self):
        """
        Open DB connections and cursors
        """
        if self.lock:
            PLEXDB_LOCK.acquire()
            KODIDB_LOCK.acquire()
        self.plexconn = db.connect('plex')
        self.plexcursor = self.plexconn.cursor()
        self.kodiconn = db.connect('video')
        self.kodicursor = self.kodiconn.cursor()
        self.artconn = db.connect('texture')
        self.artcursor = self.artconn.cursor()
        self.plexdb = PlexDB(plexconn=self.plexconn, lock=False)
        self.kodidb = KodiVideoDB(texture_db=True,
                                  kodiconn=self.kodiconn,
                                  artconn=self.artconn,
                                  lock=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Make sure DB changes are committed and connection to DB is closed.
        """
        try:
            if exc_type:
                # re-raise any exception
                return False
            self.plexconn.commit()
            self.kodiconn.commit()
            if self.artconn:
                self.artconn.commit()
            return self
        finally:
            self.plexconn.close()
            self.kodiconn.close()
            if self.artconn:
                self.artconn.close()
            if self.lock:
                PLEXDB_LOCK.release()
                KODIDB_LOCK.release()

    def commit(self):
        self.plexconn.commit()
        self.plexconn.execute('BEGIN')
        self.kodiconn.commit()
        self.kodiconn.execute('BEGIN')
        if self.artconn:
            self.artconn.commit()
            self.artconn.execute('BEGIN')

    def set_fanart(self, artworks, kodi_id, kodi_type):
        """
        Writes artworks [dict containing only set artworks] to the Kodi art DB
        """
        self.kodidb.modify_artwork(artworks,
                                   kodi_id,
                                   kodi_type)

    def update_playstate(self, mark_played, view_count, resume, duration,
                         kodi_fileid, kodi_fileid_2, lastViewedAt):
        """
        Use with websockets, not xml
        """
        # If the playback was stopped, check whether we need to increment the
        # playcount. PMS won't tell us the playcount via websockets
        if mark_played:
            LOG.info('Marking item as completely watched in Kodi')
            try:
                view_count += 1
            except TypeError:
                view_count = 1
            resume = 0
        # Do the actual update
        self.kodidb.set_resume(kodi_fileid,
                               resume,
                               duration,
                               view_count,
                               timing.plex_date_to_kodi(lastViewedAt))
        if kodi_fileid_2:
            # Our dirty hack for episodes
            self.kodidb.set_resume(kodi_fileid_2,
                                   resume,
                                   duration,
                                   view_count,
                                   timing.plex_date_to_kodi(lastViewedAt))

    @staticmethod
    def sync_this_item(section_id):
        """
        Returns False if we are NOT synching the corresponding Plex library
        with section_id [int] to Kodi or if this sections has not yet been
        encountered by PKC
        """
        return section_id in app.SYNC.section_ids

    def update_provider_ids(self, api, kodi_id):
        """
        Updates the unique metadata provider ids (such as the IMDB id). Returns
        a dict of the Kodi unique ids
        """
        # We might have an old provider id stored!
        self.kodidb.remove_uniqueid(kodi_id, api.kodi_type)
        return self.add_provider_ids(api, kodi_id)

    def add_provider_ids(self, api, kodi_id):
        """
        Adds the unique ids for all metadata providers to the Kodi database,
        such as IMDB or The Movie Database TMDB.
        Returns a dict of the Kodi ids: {<provider>: <kodi_unique_id>}
        """
        kodi_unique_ids = api.guids.copy()
        for provider, provider_id in api.guids.items():
            kodi_unique_ids[provider] = self.kodidb.add_uniqueid(
                kodi_id,
                api.kodi_type,
                provider_id,
                provider)
        return kodi_unique_ids
