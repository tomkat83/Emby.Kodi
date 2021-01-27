#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

from .common import ItemBase
from ..plex_api import API
from ..plex_db import PlexDB, PLEXDB_LOCK
from ..kodi_db import KodiMusicDB, KODIDB_LOCK
from .. import plex_functions as PF, db, timing, app, variables as v

LOG = getLogger('PLEX.music')


class MusicMixin(object):
    def __enter__(self):
        """
        Overwrite to use the Kodi music DB instead of the video DB
        """
        if self.lock:
            PLEXDB_LOCK.acquire()
            KODIDB_LOCK.acquire()
        self.plexconn = db.connect('plex')
        self.plexcursor = self.plexconn.cursor()
        self.kodiconn = db.connect('music')
        self.kodicursor = self.kodiconn.cursor()
        self.artconn = db.connect('texture')
        self.artcursor = self.artconn.cursor()
        self.plexdb = PlexDB(plexconn=self.plexconn, lock=False)
        self.kodidb = KodiMusicDB(texture_db=True,
                                  kodiconn=self.kodiconn,
                                  artconn=self.artconn,
                                  lock=False)
        return self

    def update_userdata(self, xml_element, plex_type):
        """
        Updates the Kodi watched state of the item from PMS. Also retrieves
        Plex resume points for movies in progress.

        Returns True if successful, False otherwise (e.g. item missing)
        """
        api = API(xml_element)
        # Get key and db entry on the Kodi db side
        db_item = self.plexdb.item_by_id(api.plex_id, plex_type)
        if not db_item:
            LOG.info('Item not yet synced: %s', xml_element.attrib)
            return False
        # Grab the user's viewcount, resume points etc. from PMS' answer
        self.kodidb.update_userrating(db_item['kodi_id'],
                                      db_item['kodi_type'],
                                      api.userrating())
        if plex_type == v.PLEX_TYPE_SONG:
            self.kodidb.set_playcount(api.viewcount(),
                                      api.lastplayed(),
                                      db_item['kodi_id'],)
        return True

    def remove(self, plex_id, plex_type=None):
        """
        Remove the entire music object, including all associated entries from
        both Plex and Kodi DBs
        """
        db_item = self.plexdb.item_by_id(plex_id, plex_type)
        if not db_item:
            LOG.debug('Cannot delete plex_id %s - not found in DB', plex_id)
            return
        LOG.debug('Removing %s %s with kodi_id: %s',
                  db_item['plex_type'], plex_id, db_item['kodi_id'])

        # Remove the plex reference
        self.plexdb.remove(plex_id, db_item['plex_type'])

        # SONG #####
        if db_item['plex_type'] == v.PLEX_TYPE_SONG:
            # Delete episode, verify season and tvshow
            self.remove_song(db_item['kodi_id'], db_item['kodi_pathid'])
            # Album verification
            if not self.plexdb.album_has_songs(db_item['album_id']):
                # No songleft for this album - so delete the album
                self.remove_album(db_item['parent_id'])
                self.plexdb.remove(db_item['album_id'], v.PLEX_TYPE_ALBUM)
            # Artist verification
            if (not self.plexdb.artist_has_albums(db_item['artist_id']) and
                    not self.plexdb.artist_has_songs(db_item['artist_id'])):
                self.remove_artist(db_item['grandparent_id'])
                self.plexdb.remove(db_item['artist_id'], v.PLEX_TYPE_ARTIST)
        # ALBUM #####
        elif db_item['plex_type'] == v.PLEX_TYPE_ALBUM:
            # Remove songs, album, verify artist
            songs = list(self.plexdb.song_by_album(db_item['plex_id']))
            for song in songs:
                self.remove_song(song['kodi_id'], song['kodi_pathid'])
                self.plexdb.remove(song['plex_id'], v.PLEX_TYPE_SONG)
            # Remove the album
            self.remove_album(db_item['kodi_id'])
            # Show verification
            if (not self.plexdb.artist_has_albums(db_item['kodi_id']) and
                    not self.plexdb.artist_has_songs(db_item['kodi_id'])):
                # There's no other album or song left, delete the artist
                self.remove_artist(db_item['parent_id'])
                self.plexdb.remove(db_item['artist_id'], v.KODI_TYPE_ARTIST)
        # ARTIST #####
        elif db_item['plex_type'] == v.PLEX_TYPE_ARTIST:
            # Remove songs, albums and the artist himself
            songs = list(self.plexdb.song_by_artist(db_item['plex_id']))
            for song in songs:
                self.remove_song(song['kodi_id'], song['kodi_pathid'])
                self.plexdb.remove(song['plex_id'], v.PLEX_TYPE_SONG)
            albums = list(self.plexdb.album_by_artist(db_item['plex_id']))
            for album in albums:
                self.remove_album(album['kodi_id'])
                self.plexdb.remove(album['plex_id'], v.PLEX_TYPE_ALBUM)
            self.remove_artist(db_item['kodi_id'])

        LOG.debug('Deleted %s %s from all databases',
                  db_item['plex_type'], db_item['plex_id'])

    def remove_song(self, kodi_id, path_id=None):
        """
        Remove song, orphaned artists and orphaned paths
        """
        if not path_id:
            path_id = self.kodidb.path_id_from_song(kodi_id)
        self.kodidb.delete_song_from_song_artist(kodi_id)
        self.kodidb.remove_song(kodi_id)
        # Check whether we have orphaned path entries
        if not self.kodidb.path_id_from_song(kodi_id):
            self.kodidb.remove_path(path_id)
        self.kodidb.delete_artwork(kodi_id, v.KODI_TYPE_SONG)

    def remove_album(self, kodi_id):
        '''
        Remove an album
        '''
        self.kodidb.remove_album(kodi_id)
        self.kodidb.delete_artwork(kodi_id, v.KODI_TYPE_ALBUM)

    def remove_artist(self, kodi_id):
        '''
        Remove an artist and associated songs and albums
        '''
        self.kodidb.remove_artist(kodi_id)
        self.kodidb.delete_artwork(kodi_id, v.KODI_TYPE_ARTIST)


class Artist(MusicMixin, ItemBase):
    """
    For Plex library-type artists
    """
    def add_update(self, xml, section_name=None, section_id=None,
                   children=None):
        """
        Process a single artist
        """
        api = API(xml)
        if not self.sync_this_item(section_id or api.library_section_id()):
            LOG.debug('Skipping sync of %s %s: %s - section %s not synched to '
                      'Kodi', api.plex_type, api.plex_id, api.title(),
                      section_id or api.library_section_id())
            return
        plex_id = api.plex_id
        artist = self.plexdb.artist(plex_id)
        if not artist:
            update_item = False
        else:
            update_item = True
            kodi_id = artist['kodi_id']

        # Not yet implemented by Plex
        musicBrainzId = None

        if app.SYNC.artwork:
            artworks = api.artwork()

        # UPDATE THE ARTIST #####
        if update_item:
            LOG.info("UPDATE artist plex_id: %s - Name: %s", plex_id, api.title())
        # OR ADD THE ARTIST #####
        else:
            LOG.info("ADD artist plex_id: %s - Name: %s", plex_id, api.title())
            # safety checks: It looks like plex supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            kodi_id = self.kodidb.add_artist(api.title(), musicBrainzId)
        self.kodidb.update_artist(api.list_to_string(api.genres()),
                                  api.plot(),
                                  timing.unix_date_to_kodi(self.last_sync),
                                  kodi_id)
        if app.SYNC.artwork:
            self.kodidb.modify_artwork(artworks,
                                       kodi_id,
                                       v.KODI_TYPE_ARTIST)
        self.plexdb.add_artist(plex_id,
                               api.checksum(),
                               section_id,
                               kodi_id,
                               self.last_sync)


class Album(MusicMixin, ItemBase):
    def add_update(self, xml, section_name=None, section_id=None,
                   children=None, scan_children=True):
        """
        Process a single album
        scan_children: set to False if you don't want to add children, e.g. to
        avoid infinite loops
        """
        api = API(xml)
        if not self.sync_this_item(section_id or api.library_section_id()):
            LOG.debug('Skipping sync of %s %s: %s - section %s not synched to '
                      'Kodi', api.plex_type, api.plex_id, api.title(),
                      section_id or api.library_section_id())
            return
        plex_id = api.plex_id
        album = self.plexdb.album(plex_id)
        if album:
            update_item = True
            kodi_id = album['kodi_id']
        else:
            update_item = False

        # Parent artist - should always be present
        parent_id = api.parent_id()
        artist = self.plexdb.artist(parent_id)
        if not artist:
            LOG.info('Artist %s does not yet exist in DB', parent_id)
            artist_xml = PF.GetPlexMetadata(parent_id)
            try:
                artist_xml[0].attrib
            except (TypeError, IndexError, AttributeError):
                LOG.error('Could not get artist %s xml for %s',
                          parent_id, xml.attrib)
                return
            Artist(self.last_sync,
                   plexdb=self.plexdb,
                   kodidb=self.kodidb).add_update(artist_xml[0],
                                                  section_name,
                                                  section_id)
            artist = self.plexdb.artist(parent_id)
            if not artist:
                LOG.error('Adding artist %s failed for %s',
                          parent_id, xml.attrib)
                return
        artist_id = artist['kodi_id']
        # See if we have a compilation - Plex does NOT feature a compilation
        # flag for albums
        compilation = 0
        if children is None:
            LOG.info('No children songs passed, getting them')
            children = PF.GetAllPlexChildren(plex_id)
            try:
                children[0].attrib
            except (TypeError, IndexError, AttributeError):
                LOG.error('Could not get children for Plex id %s', plex_id)
                return
        for song in children:
            if song.get('originalTitle') is not None:
                compilation = 1
                break
        name = api.title()
        # Not yet implemented by Plex, let's use unique last.fm or gracenote
        musicBrainzId = None
        genre = api.list_to_string(api.genres())
        if app.SYNC.artwork:
            artworks = api.artwork()

        # UPDATE THE ALBUM #####
        if update_item:
            LOG.info("UPDATE album plex_id: %s - Name: %s", plex_id, name)
            self.kodidb.update_album(name,
                                     musicBrainzId,
                                     api.artist_name(),
                                     genre,
                                     api.premiere_date(),
                                     # TODO: as soon as Plex supports the original
                                     # release date (Kodi: strOrigReleaseDate)
                                     api.premiere_date(),
                                     compilation,
                                     api.plot(),
                                     api.list_to_string(api.studios()),
                                     api.kodi_type,
                                     api.userrating(),
                                     timing.unix_date_to_kodi(self.last_sync),
                                     api.kodi_type,
                                     kodi_id)
        # OR ADD THE ALBUM #####
        else:
            LOG.info("ADD album plex_id: %s - Name: %s", plex_id, name)
            kodi_id = self.kodidb.new_album_id()
            self.kodidb.add_album(kodi_id,
                                  name,
                                  musicBrainzId,
                                  api.artist_name(),
                                  genre,
                                  api.premiere_date(),
                                  # TODO: as soon as Plex supports the original
                                  # release date (Kodi: strOrigReleaseDate)
                                  api.premiere_date(),
                                  compilation,
                                  api.plot(),
                                  api.list_to_string(api.studios()),
                                  api.kodi_type,
                                  api.userrating(),
                                  timing.unix_date_to_kodi(self.last_sync),
                                  api.kodi_type)
        self.kodidb.add_albumartist(artist_id, kodi_id, api.artist_name())
        if app.SYNC.artwork:
            self.kodidb.modify_artwork(artworks,
                                       kodi_id,
                                       v.KODI_TYPE_ALBUM)
        self.plexdb.add_album(plex_id,
                              api.checksum(),
                              section_id,
                              artist_id,
                              parent_id,
                              kodi_id,
                              self.last_sync)
        # Add all children - all tracks
        if scan_children:
            context = Song(self.last_sync,
                           plexdb=self.plexdb,
                           kodidb=self.kodidb)
            for song in children:
                context.add_update(song,
                                   section_name=section_name,
                                   section_id=section_id,
                                   album_xml=xml,
                                   genres=api.genres(),
                                   genre=genre,
                                   compilation=compilation)


class Song(MusicMixin, ItemBase):
    def add_update(self, xml, section_name=None, section_id=None,
                   children=None, album_xml=None, genres=None, genre=None,
                   compilation=None):
        """
        Process single song/track
        """
        api = API(xml)
        if not self.sync_this_item(section_id or api.library_section_id()):
            LOG.debug('Skipping sync of %s %s: %s - section %s not synched to '
                      'Kodi', api.plex_type, api.plex_id, api.title(),
                      section_id or api.library_section_id())
            return
        plex_id = api.plex_id
        song = self.plexdb.song(plex_id)
        if song:
            update_item = True
            kodi_id = song['kodi_id']
            kodi_pathid = song['kodi_pathid']
        else:
            update_item = False
            kodi_id = self.kodidb.add_song_id()
        artist_id = api.grandparent_id()
        album_id = api.parent_id()

        # The grandparent Artist - should always be present for every song!
        artist = self.plexdb.artist(artist_id)
        if not artist:
            LOG.warn('Grandparent artist %s not found in DB, adding it',
                     artist_id)
            artist_xml = PF.GetPlexMetadata(artist_id)
            try:
                artist_xml[0].attrib
            except (TypeError, IndexError, AttributeError):
                LOG.error('Grandparent tvartist %s xml download failed for %s',
                          artist_id, xml.attrib)
                return
            Artist(self.last_sync,
                   plexdb=self.plexdb,
                   kodidb=self.kodidb).add_update(artist_xml[0],
                                                  section_name,
                                                  section_id)
            artist = self.plexdb.artist(artist_id)
            if not artist:
                LOG.error('Still could not find grandparent artist %s for %s',
                          artist_id, xml.attrib)
                return
        grandparent_id = artist['kodi_id']

        # The parent Album
        if not album_id:
            # No album found, create a single's album
            LOG.info('Creating singles album')
            parent_id = self.kodidb.new_album_id()
            self.kodidb.add_album(kodi_id,
                                  None,
                                  None,
                                  None,
                                  genre,
                                  api.premiere_date(),
                                  # TODO: as soon as Plex supports the original
                                  # release date (Kodi: strOrigReleaseDate)
                                  api.premiere_date(),
                                  None,
                                  None,
                                  None,
                                  'single',
                                  None,
                                  None,
                                  timing.unix_date_to_kodi(self.last_sync),
                                  'single')
        else:
            album = self.plexdb.album(album_id)
            if not album:
                LOG.warn('Parent album %s not found in DB, adding it', album_id)
                album_xml = PF.GetPlexMetadata(album_id)
                try:
                    album_xml[0].attrib
                except (TypeError, IndexError, AttributeError):
                    LOG.error('Parent album %s xml download failed for %s',
                              album_id, xml.attrib)
                    return
                Album(self.last_sync,
                      plexdb=self.plexdb,
                      kodidb=self.kodidb).add_update(album_xml[0],
                                                     section_name,
                                                     section_id,
                                                     children=[xml],
                                                     scan_children=False)
                album = self.plexdb.album(album_id)
                if not album:
                    LOG.error('Still could not find parent album %s for %s',
                              album_id, xml.attrib)
                    return
            parent_id = album['kodi_id']

        title = api.title()
        # Not yet implemented by Plex
        musicBrainzId = None
        comment = None
        # Getting artists name is complicated
        if compilation is not None:
            if compilation == 0:
                artists = api.grandparent_title()
            else:
                artists = xml.get('originalTitle')
        else:
            # compilation not set
            artists = xml.get('originalTitle', api.grandparent_title())
        tracknumber = api.index() or 0
        disc = api.disc_number() or 1
        if disc == 1:
            track = tracknumber
        else:
            track = disc * 2 ** 16 + tracknumber
        year = api.year()
        if not year and album_xml is not None:
            # Plex did not pass year info - get it from the parent album
            album_api = API(album_xml)
            year = album_api.year()
        moods = []
        for entry in xml:
            if entry.tag == 'Mood':
                moods.append(entry.attrib['tag'])
        mood = api.list_to_string(moods)
        _, path, filename = api.fullpath()
        audio_codec = api.audio_codec()
        # UPDATE THE SONG #####
        if update_item:
            LOG.info("UPDATE song plex_id: %s - %s", plex_id, title)
            # Use dummy strHash '123' for Kodi
            self.kodidb.update_path(path, kodi_pathid)
            self.kodidb.update_song(parent_id,
                                    artists,
                                    genre,
                                    title,
                                    track,
                                    api.runtime(),
                                    api.premiere_date(),
                                    # TODO: as soon as Plex supports the original
                                    # release date (Kodi: strOrigReleaseDate)
                                    api.premiere_date(),
                                    filename,
                                    api.viewcount(),
                                    api.lastplayed(),
                                    api.userrating(),
                                    comment,
                                    mood,
                                    audio_codec['bitrate'] or 0,
                                    audio_codec['samplingrate'] or 0,
                                    audio_codec['channels'] or 0,
                                    api.date_created(),
                                    kodi_id)
        # OR ADD THE SONG #####
        else:
            LOG.info("ADD song plex_id: %s - %s", plex_id, title)
            # Add path
            kodi_pathid = self.kodidb.add_path(path)
            self.kodidb.add_song(kodi_id,
                                 parent_id,
                                 kodi_pathid,
                                 artists,
                                 genre,
                                 title,
                                 track,
                                 api.runtime(),
                                 api.premiere_date(),
                                 # TODO: as soon as Plex supports the original
                                 # release date (Kodi: strOrigReleaseDate)
                                 api.premiere_date(),
                                 filename,
                                 musicBrainzId,
                                 api.viewcount(),
                                 api.lastplayed(),
                                 api.userrating(),
                                 0,
                                 0,
                                 mood,
                                 audio_codec['bitrate'] or 0,
                                 audio_codec['samplingrate'] or 0,
                                 audio_codec['channels'] or 0,
                                 api.date_created())
        # Link song to artists
        artist_name = api.grandparent_title()
        # Do the actual linking
        self.kodidb.add_song_artist(grandparent_id, kodi_id, artist_name)
        # Add genres
        if genres:
            self.kodidb.add_music_genres(kodi_id, genres, v.KODI_TYPE_SONG)
        if app.SYNC.artwork:
            artworks = api.artwork()
            self.kodidb.modify_artwork(artworks,
                                       kodi_id,
                                       v.KODI_TYPE_SONG)
            if xml.get('parentKey') is None:
                # Update album artwork
                self.kodidb.modify_artwork(artworks,
                                           parent_id,
                                           v.KODI_TYPE_ALBUM)
        self.plexdb.add_song(plex_id,
                             api.checksum(),
                             section_id,
                             artist_id,
                             grandparent_id,
                             album_id,
                             parent_id,
                             kodi_id,
                             kodi_pathid,
                             self.last_sync)
