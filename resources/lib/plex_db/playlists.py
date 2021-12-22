#!/usr/bin/env python
# -*- coding: utf-8 -*-

class Playlists(object):
    def playlist_ids(self):
        """
        Returns an iterator of all Plex ids of playlists.
        """
        self.cursor.execute('SELECT plex_id FROM playlists')
        return (x[0] for x in self.cursor)

    def kodi_playlist_paths(self):
        """
        Returns an iterator of all Kodi playlist paths.
        """
        self.cursor.execute('SELECT kodi_path FROM playlists')
        return (x[0] for x in self.cursor)

    def delete_playlist(self, playlist):
        """
        Removes the entry for playlist [Playqueue()] from the Plex
        playlists table.
        Be sure to either set playlist.id or playlist.kodi_path
        """
        if playlist.plex_id:
            query = 'DELETE FROM playlists WHERE plex_id = ?'
            var = playlist.plex_id
        elif playlist.kodi_path:
            query = 'DELETE FROM playlists WHERE kodi_path = ?'
            var = playlist.kodi_path
        else:
            raise RuntimeError('Cannot delete playlist: %s' % playlist)
        self.cursor.execute(query, (var, ))

    def add_playlist(self, playlist):
        """
        Inserts or modifies an existing entry in the Plex playlists table.
        """
        query = '''
            INSERT OR REPLACE INTO playlists(
                plex_id,
                plex_name,
                plex_updatedat,
                kodi_path,
                kodi_type,
                kodi_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            '''
        self.cursor.execute(
            query,
            (playlist.plex_id,
             playlist.plex_name,
             playlist.plex_updatedat,
             playlist.kodi_path,
             playlist.kodi_type,
             playlist.kodi_hash))

    def playlist(self, playlist, plex_id=None, path=None):
        """
        Returns a complete Playlist (empty one passed in via playlist) for the
        entry with plex_id OR kodi_path.
        Returns None if not found
        """
        query = 'SELECT * FROM playlists WHERE %s = ? LIMIT 1'
        if plex_id:
            query = query % 'plex_id'
            var = plex_id
        elif path:
            query = query % 'kodi_path'
            var = path
        self.cursor.execute(query, (var, ))
        answ = self.cursor.fetchone()
        if not answ:
            return
        playlist.plex_id = answ[0]
        playlist.plex_name = answ[1]
        playlist.plex_updatedat = answ[2]
        playlist.kodi_path = answ[3]
        playlist.kodi_type = answ[4]
        playlist.kodi_hash = answ[5]
        return playlist

    def all_kodi_paths(self):
        """
        Returns a generator for all kodi_paths of all synched playlists
        """
        self.cursor.execute('SELECT kodi_path FROM playlists')
        return (x[0] for x in self.cursor)

    def wipe_playlists(self):
        """
        Deletes all entries in the playlists table
        """
        self.cursor.execute('DELETE FROM playlists')
