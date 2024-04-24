#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .. import variables as v

class TVShows(object):
    def add_show(self, plex_id, plex_guid, checksum, section_id, kodi_id, kodi_pathid,
                 last_sync):
        """
        Appends or replaces tv show entry into the plex table
        """
        self.cursor.execute(
            '''
            INSERT OR REPLACE INTO show(
                plex_id,
                plex_guid,
                checksum,
                section_id,
                kodi_id,
                kodi_pathid,
                fanart_synced,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (plex_id,
             plex_guid,
             checksum,
             section_id,
             kodi_id,
             kodi_pathid,
             0,
             last_sync))

    def add_season(self, plex_id, plex_guid, checksum, section_id, show_id, parent_id,
                   kodi_id, last_sync):
        """
        Appends or replaces an entry into the plex table
        """
        self.cursor.execute(
            '''
            INSERT OR REPLACE INTO season(
                plex_id,
                plex_guid,
                checksum,
                section_id,
                show_id,
                parent_id,
                kodi_id,
                fanart_synced,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (plex_id,
             plex_guid,
             checksum,
             section_id,
             show_id,
             parent_id,
             kodi_id,
             0,
             last_sync))

    def add_episode(self, plex_id, plex_guid, checksum, section_id, show_id,
                    grandparent_id, season_id, parent_id, kodi_id, kodi_fileid,
                    kodi_fileid_2, kodi_pathid, last_sync):
        """
        Appends or replaces an entry into the plex table
        """
        self.cursor.execute(
            '''
            INSERT OR REPLACE INTO episode(
                plex_id,
                plex_guid,
                checksum,
                section_id,
                show_id,
                grandparent_id,
                season_id,
                parent_id,
                kodi_id,
                kodi_fileid,
                kodi_fileid_2,
                kodi_pathid,
                fanart_synced,
                last_sync)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (plex_id,
             plex_guid,
             checksum,
             section_id,
             show_id,
             grandparent_id,
             season_id,
             parent_id,
             kodi_id,
             kodi_fileid,
             kodi_fileid_2,
             kodi_pathid,
             0,
             last_sync))

    def show(self, plex_id):
        """
        Returns the show info as a tuple for the TV show with plex_id:
            plex_id INTEGER PRIMARY KEY ASC,
            plex_guid TEXT,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            kodi_id INTEGER,
            kodi_pathid INTEGER,
            fanart_synced INTEGER,
            last_sync INTEGER
        """
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM show WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_show(self.cursor.fetchone())

    def shows_by_guid(self, plex_guid):
        """
        Returns a list of shows or an empty list, each element being a 
        dictionary looking like this:
            plex_id INTEGER PRIMARY KEY ASC,
            plex_guid TEXT,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            kodi_id INTEGER,
            kodi_pathid INTEGER,
            fanart_synced INTEGER,
            last_sync INTEGER
        """
        if plex_guid is None:
            return list()
        self.cursor.execute('SELECT * FROM show WHERE plex_guid = ?',
                            (plex_guid, ))
        return list(self.entry_to_show(x) for x in self.cursor.fetchall())

    def season(self, plex_id):
        """
        Returns the show info as a tuple for the TV show with plex_id:
            plex_id INTEGER PRIMARY KEY,
            plex_guid TEXT,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            show_id INTEGER,  # plex_id of the parent show
            parent_id INTEGER,  # kodi_id of the parent show
            kodi_id INTEGER,
            fanart_synced INTEGER,
            last_sync INTEGER
        """
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM season WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_season(self.cursor.fetchone())

    def seasons_by_guid(self, plex_guid):
        """
        Returns a list of seasons or an empty list, with each list element
        being a dictionary looking like this:
            plex_id INTEGER PRIMARY KEY,
            plex_guid TEXT,
            checksum INTEGER UNIQUE,
            section_id INTEGER,
            show_id INTEGER,  # plex_id of the parent show
            parent_id INTEGER,  # kodi_id of the parent show
            kodi_id INTEGER,
            fanart_synced INTEGER,
            last_sync INTEGER
        """
        if plex_guid is None:
            return list()
        self.cursor.execute('SELECT * FROM season WHERE plex_guid = ?',
                            (plex_guid, ))
        return list(self.entry_to_season(x) for x in self.cursor.fetchall())

    def episode(self, plex_id):
        if plex_id is None:
            return
        self.cursor.execute('SELECT * FROM episode WHERE plex_id = ? LIMIT 1',
                            (plex_id, ))
        return self.entry_to_episode(self.cursor.fetchone())

    def episodes_by_guid(self, plex_guid):
        """
        Returns a list of episodes or an empty list, each list element being
        a dictionary with the following keys:
            plex_type
            kodi_type
            plex_id
            plex_guid
            checksum
            section_id
            show_id
            grandparent_id
            season_id
            parent_id
            kodi_id
            kodi_fileid
            kodi_fileid_2
            kodi_pathid
            fanart_synced
            last_sync
        """
        if plex_guid is None:
            return list()
        self.cursor.execute('SELECT * FROM episode WHERE plex_guid = ?',
                            (plex_guid, ))
        return list(self.entry_to_episode(x) for x in self.cursor.fetchall())

    @staticmethod
    def entry_to_episode(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_EPISODE,
            'kodi_type': v.KODI_TYPE_EPISODE,
            'plex_id': entry[0],
            'plex_guid': entry[1],
            'checksum': entry[2],
            'section_id': entry[3],
            'show_id': entry[4],
            'grandparent_id': entry[5],
            'season_id': entry[6],
            'parent_id': entry[7],
            'kodi_id': entry[8],
            'kodi_fileid': entry[9],
            'kodi_fileid_2': entry[10],
            'kodi_pathid': entry[11],
            'fanart_synced': entry[12],
            'last_sync': entry[13]
        }

    @staticmethod
    def entry_to_show(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_SHOW,
            'kodi_type': v.KODI_TYPE_SHOW,
            'plex_id': entry[0],
            'plex_guid': entry[1],
            'checksum': entry[2],
            'section_id': entry[3],
            'kodi_id': entry[4],
            'kodi_pathid': entry[5],
            'fanart_synced': entry[6],
            'last_sync': entry[7]
        }

    @staticmethod
    def entry_to_season(entry):
        if not entry:
            return
        return {
            'plex_type': v.PLEX_TYPE_SEASON,
            'kodi_type': v.KODI_TYPE_SEASON,
            'plex_id': entry[0],
            'plex_guid': entry[1],
            'checksum': entry[2],
            'section_id': entry[3],
            'show_id': entry[4],
            'parent_id': entry[5],
            'kodi_id': entry[6],
            'fanart_synced': entry[7],
            'last_sync': entry[8]
        }

    def season_has_episodes(self, plex_id):
        """
        Returns True if there are episodes left for the season with plex_id
        """
        self.cursor.execute('SELECT plex_id FROM episode WHERE season_id = ? LIMIT 1',
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def show_has_seasons(self, plex_id):
        """
        Returns True if there are seasons left for the show with plex_id
        """
        self.cursor.execute('SELECT plex_id FROM season WHERE show_id = ? LIMIT 1',
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def show_has_episodes(self, plex_id):
        """
        Returns True if there are episodes left for the show with plex_id
        """
        self.cursor.execute('SELECT plex_id FROM episode WHERE show_id = ? LIMIT 1',
                            (plex_id, ))
        return self.cursor.fetchone() is not None

    def episode_by_season(self, plex_id):
        """
        Returns an iterator for all episodes that have a parent season_id with
        a value of plex_id
        """
        return (self.entry_to_episode(x) for x in
                self.cursor.execute('SELECT * FROM episode WHERE season_id = ?',
                                    (plex_id, )))

    def episode_by_show(self, plex_id):
        """
        Returns an iterator for all episodes that have a grandparent show_id
        with a value of plex_id
        """
        return (self.entry_to_episode(x) for x in
                self.cursor.execute('SELECT * FROM episode WHERE show_id = ?',
                                    (plex_id, )))

    def season_by_show(self, plex_id):
        """
        Returns an iterator for all seasons that have a parent show_id
        with a value of plex_id
        """
        return (self.entry_to_season(x) for x in
                self.cursor.execute('SELECT * FROM season WHERE show_id = ?',
                                    (plex_id, )))
