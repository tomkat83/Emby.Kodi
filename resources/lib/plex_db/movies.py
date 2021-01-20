#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .. import variables as v


class Movies(object):
    def add_movie(self, plex_id, checksum, section_id, kodi_id, kodi_fileid,
                  kodi_pathid, trailer_synced, last_sync):
        """
        Appends or replaces an entry into the plex table for movies
        """
        query = '''
            INSERT OR REPLACE INTO movie(
                plex_id,
                checksum,
                section_id,
                kodi_id,
                kodi_fileid,
                kodi_pathid,
                fanart_synced,
                trailer_synced,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
        self.cursor.execute(
            query,
            (plex_id,
             checksum,
             section_id,
             kodi_id,
             kodi_fileid,
             kodi_pathid,
             0,
             trailer_synced,
             last_sync))

    def movie(self, plex_id):
        """
        Returns the show info as a tuple for the TV show with plex_id:
            plex_id INTEGER PRIMARY KEY ASC,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            kodi_id INTEGER,
            kodi_fileid INTEGER,
            kodi_pathid INTEGER,
            fanart_synced INTEGER,
            last_sync INTEGER
        """
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM movie WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_movie(self.cursor.fetchone())

    @staticmethod
    def entry_to_movie(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_MOVIE,
            'kodi_type': v.KODI_TYPE_MOVIE,
            'plex_id': entry[0],
            'checksum': entry[1],
            'section_id': entry[2],
            'kodi_id': entry[3],
            'kodi_fileid': entry[4],
            'kodi_pathid': entry[5],
            'fanart_synced': entry[6],
            'last_sync': entry[7]
        }
