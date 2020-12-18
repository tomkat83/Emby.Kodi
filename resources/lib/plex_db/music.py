#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .. import variables as v


class Music(object):
    def add_artist(self, plex_id, checksum, section_id, kodi_id, last_sync):
        """
        Appends or replaces music artist entry into the plex table
        """
        query = '''
            INSERT OR REPLACE INTO artist(
                plex_id,
                checksum,
                section_id,
                kodi_id,
                last_sync)
            VALUES (?, ?, ?, ?, ?)
        '''
        self.cursor.execute(
            query,
            (plex_id,
             checksum,
             section_id,
             kodi_id,
             last_sync))

    def add_album(self, plex_id, checksum, section_id, artist_id, parent_id,
                  kodi_id, last_sync):
        """
        Appends or replaces an entry into the plex table
        """
        query = '''
            INSERT OR REPLACE INTO album(
                plex_id,
                checksum,
                section_id,
                artist_id,
                parent_id,
                kodi_id,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        '''
        self.cursor.execute(
            query,
            (plex_id,
             checksum,
             section_id,
             artist_id,
             parent_id,
             kodi_id,
             last_sync))

    def add_song(self, plex_id, checksum, section_id, artist_id, grandparent_id,
                 album_id, parent_id, kodi_id, kodi_pathid, last_sync):
        """
        Appends or replaces an entry into the plex table
        """
        query = '''
            INSERT OR REPLACE INTO track(
                plex_id,
                checksum,
                section_id,
                artist_id,
                grandparent_id,
                album_id,
                parent_id,
                kodi_id,
                kodi_pathid,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
        self.cursor.execute(
            query,
            (plex_id,
             checksum,
             section_id,
             artist_id,
             grandparent_id,
             album_id,
             parent_id,
             kodi_id,
             kodi_pathid,
             last_sync))

    def artist(self, plex_id):
        """
        Returns the show info as a tuple for the TV show with plex_id:
            plex_id INTEGER PRIMARY KEY,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            kodi_id INTEGER,
            last_sync INTEGER
        """
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM artist WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_artist(self.cursor.fetchone())

    def album(self, plex_id):
        """
        Returns the show info as a tuple for the TV show with plex_id:
            plex_id INTEGER PRIMARY KEY,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            artist_id INTEGER,  # plex_id of the parent artist
            parent_id INTEGER,  # kodi_id of the parent artist
            kodi_id INTEGER,
            last_sync INTEGER
        """
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM album WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_album(self.cursor.fetchone())

    def song(self, plex_id):
        """
        Returns the show info as a tuple for the TV show with plex_id:
            plex_id INTEGER PRIMARY KEY,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            artist_id INTEGER,  # plex_id of the parent artist
            grandparent_id INTEGER,  # kodi_id of the parent artist
            album_id INTEGER,  # plex_id of the parent album
            parent_id INTEGER,  # kodi_id of the parent album
            kodi_id INTEGER,
            kodi_pathid INTEGER,
            last_sync INTEGER
        """
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM track WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_track(self.cursor.fetchone())

    @staticmethod
    def entry_to_track(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_SONG,
            'kodi_type': v.KODI_TYPE_SONG,
            'plex_id': entry[0],
            'checksum': entry[1],
            'section_id': entry[2],
            'artist_id': entry[3],
            'grandparent_id': entry[4],
            'album_id': entry[5],
            'parent_id': entry[6],
            'kodi_id': entry[7],
            'kodi_pathid': entry[8],
            'last_sync': entry[9]
        }

    @staticmethod
    def entry_to_album(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_ALBUM,
            'kodi_type': v.KODI_TYPE_ALBUM,
            'plex_id': entry[0],
            'checksum': entry[1],
            'section_id': entry[2],
            'artist_id': entry[3],
            'parent_id': entry[4],
            'kodi_id': entry[5],
            'last_sync': entry[6]
        }

    @staticmethod
    def entry_to_artist(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_ARTIST,
            'kodi_type': v.KODI_TYPE_ARTIST,
            'plex_id': entry[0],
            'checksum': entry[1],
            'section_id': entry[2],
            'kodi_id': entry[3],
            'last_sync': entry[4]
        }

    def album_has_songs(self, plex_id):
        """
        Returns True if there are songs left for the album with plex_id
        """
        self.cursor.execute('SELECT plex_id FROM track WHERE album_id = ? LIMIT 1',
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def artist_has_albums(self, plex_id):
        """
        Returns True if there are albums left for the artist with plex_id
        """
        self.cursor.execute('SELECT plex_id FROM album WHERE artist_id = ? LIMIT 1',
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def artist_has_songs(self, plex_id):
        """
        Returns True if there are episodes left for the show with plex_id
        """
        self.cursor.execute('SELECT plex_id FROM track WHERE artist_id = ? LIMIT 1',
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def song_by_album(self, plex_id):
        """
        Returns an iterator for all songs that have a parent album_id with
        a value of plex_id
        """
        self.cursor.execute('SELECT * FROM track WHERE album_id = ?',
                            (plex_id, ))
        return (self.entry_to_track(x) for x in self.cursor)

    def song_by_artist(self, plex_id):
        """
        Returns an iterator for all songs that have a grandparent artist_id
        with a value of plex_id
        """
        self.cursor.execute('SELECT * FROM track WHERE artist_id = ?',
                            (plex_id, ))
        return (self.entry_to_track(x) for x in self.cursor)

    def album_by_artist(self, plex_id):
        """
        Returns an iterator for all albums that have a parent artist_id
        with a value of plex_id
        """
        self.cursor.execute('SELECT * FROM album WHERE artist_id = ?',
                            (plex_id, ))
        return (self.entry_to_album(x) for x in self.cursor)

    def songs_have_been_synced(self):
        """
        Returns True if at least one song has been synced - indicating that
        Plex Music sync has been active at some point
        """
        self.cursor.execute('SELECT plex_id FROM track LIMIT 1')
        return self.cursor.fetchone() is not None
