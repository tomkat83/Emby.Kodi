#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:module: plexkodiconnect.playlists
:synopsis: This module syncs Plex playlists to Kodi playlists and vice-versa
:author: Croneter

.. autoclass:: kodi_playlist_monitor

.. autoclass:: full_sync

.. autoclass:: websocket
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .common import Playlist, PlaylistError, PlaylistObserver
from . import pms, db, kodi_pl, plex_pl

from ..watchdog import events
from ..plex_api import API
from .. import utils, path_ops, variables as v, state

###############################################################################
LOG = getLogger('PLEX.playlists')

# Safety margin for playlist filesystem operations
FILESYSTEM_TIMEOUT = 1

# Which playlist formates are supported by PKC?
SUPPORTED_FILETYPES = (
    'm3u',
    # 'm3u8'
    # 'pls',
    # 'cue',
)
# Avoid endless loops. Store Plex IDs for creating, Kodi paths for deleting!
IGNORE_KODI_PLAYLIST_CHANGE = list()
# Used for updating Plex playlists due to Kodi changes - Plex playlist
# will have to be deleted first. Add Plex ids!
IGNORE_PLEX_PLAYLIST_CHANGE = list()
###############################################################################


def kodi_playlist_monitor():
    """
    Monitor for the Kodi playlist folder special://profile/playlist

    Monitors for all file changes and will thus catch all changes on the Kodi
    side of things (as soon as the user saves a new or modified playlist). This
    is accomplished by starting a PlaylistObserver with the
    PlaylistEventhandler

    Returns
    -------
    PlaylistObserver
        Returns an already started PlaylistObserver instance

    Notes
    -----
    Be sure to stop the returned PlaylistObserver with observer.stop()
    (and maybe observer.join()) to shut down properly
    """
    event_handler = PlaylistEventhandler()
    observer = PlaylistObserver(timeout=FILESYSTEM_TIMEOUT)
    observer.schedule(event_handler, v.PLAYLIST_PATH, recursive=True)
    observer.start()
    return observer


def websocket(plex_id, status):
    """
    Call this function to process websocket messages from the PMS

    Will use the playlist lock to process one single websocket message from
    the PMS, and e.g. create or delete the corresponding Kodi playlist (if
    applicable settings are set)

    Parameters
    ----------
    plex_id : unicode
        The unqiue Plex id 'ratingKey' as received from the PMS
    status : int
        'state' as communicated by the PMS in the websocket message. This
        function will then take the correct actions to process the message
        * 0: 'created'
        * 2: 'matching'
        * 3: 'downloading'
        * 4: 'loading'
        * 5: 'finished'
        * 6: 'analyzing'
        * 9: 'deleted'
    """
    create = False
    with state.LOCK_PLAYLISTS:
        playlist = db.get_playlist(plex_id=plex_id)
        if plex_id in IGNORE_PLEX_PLAYLIST_CHANGE:
            LOG.debug('Ignoring detected Plex playlist change for %s',
                      playlist)
            IGNORE_PLEX_PLAYLIST_CHANGE.remove(plex_id)
            return
        if playlist and status == 9:
            # Won't be able to download metadata of the deleted playlist
            if sync_plex_playlist(playlist=playlist):
                LOG.debug('Plex deletion of playlist detected: %s', playlist)
                try:
                    IGNORE_KODI_PLAYLIST_CHANGE.append(plex_id)
                    kodi_pl.delete(playlist)
                except PlaylistError:
                    IGNORE_KODI_PLAYLIST_CHANGE.remove(plex_id)
            return
        xml = pms.metadata(plex_id)
        if xml is None:
            LOG.debug('Could not download playlist %s, probably deleted',
                      plex_id)
            return
        if not sync_plex_playlist(xml=xml[0]):
            return
        api = API(xml[0])
        try:
            if playlist:
                if api.updated_at() == playlist.plex_updatedat:
                    LOG.debug('Playlist with id %s already synced: %s',
                              plex_id, playlist)
                else:
                    LOG.debug('Change of Plex playlist detected: %s',
                              playlist)
                    IGNORE_KODI_PLAYLIST_CHANGE.append(plex_id)
                    kodi_pl.delete(playlist)
                    create = True
            elif not playlist and not status == 9:
                LOG.debug('Creation of new Plex playlist detected: %s',
                          plex_id)
                create = True
            # To the actual work
            if create:
                IGNORE_KODI_PLAYLIST_CHANGE.append(plex_id)
                kodi_pl.create(plex_id)
        except PlaylistError:
            IGNORE_KODI_PLAYLIST_CHANGE.remove(plex_id)


def full_sync():
    """
    Full sync of playlists between Kodi and Plex

    Call to trigger a full sync both ways, e.g. on Kodi start-up. If issues
    with a single playlist are encountered on either the Plex or Kodi side,
    this particular playlist is omitted. Will use the playlist lock.

    Returns
    -------
    bool
        True if successful, False otherwise (actually only if we failed to
        fetch the PMS playlists)
    """
    LOG.info('Starting playlist full sync')
    with state.LOCK_PLAYLISTS:
        # Need to lock because we're messing with playlists
        return _full_sync()


def _full_sync():
    # Get all Plex playlists
    xml = pms.all_playlists()
    if xml is None:
        return False
    # For each playlist, check Plex database to see whether we already synced
    # before. If yes, make sure that hashes are identical. If not, sync it.
    old_plex_ids = db.plex_playlist_ids()
    for xml_playlist in xml:
        api = API(xml_playlist)
        try:
            old_plex_ids.remove(api.plex_id())
        except ValueError:
            pass
        if not sync_plex_playlist(xml=xml_playlist):
            continue
        playlist = db.get_playlist(plex_id=api.plex_id())
        if not playlist:
            LOG.debug('New Plex playlist %s discovered: %s',
                      api.plex_id(), api.title())
            IGNORE_KODI_PLAYLIST_CHANGE.append(api.plex_id())
            try:
                kodi_pl.create(api.plex_id())
            except PlaylistError:
                LOG.info('Skipping creation of playlist %s', api.plex_id())
                IGNORE_KODI_PLAYLIST_CHANGE.remove(api.plex_id())
        elif playlist.plex_updatedat != api.updated_at():
            LOG.debug('Detected changed Plex playlist %s: %s',
                      api.plex_id(), api.title())
            # Since we are DELETING a playlist, we need to catch with path!
            IGNORE_KODI_PLAYLIST_CHANGE.append(playlist.kodi_path)
            try:
                kodi_pl.delete(playlist)
            except PlaylistError:
                LOG.info('Skipping recreation of playlist %s', api.plex_id())
                IGNORE_KODI_PLAYLIST_CHANGE.remove(playlist.kodi_path)
            else:
                IGNORE_KODI_PLAYLIST_CHANGE.append(api.plex_id())
                try:
                    kodi_pl.create(api.plex_id())
                except PlaylistError:
                    LOG.info('Could not recreate playlist %s', api.plex_id())
                    IGNORE_KODI_PLAYLIST_CHANGE.remove(api.plex_id())
    # Get rid of old Plex playlists that were deleted on the Plex side
    for plex_id in old_plex_ids:
        playlist = db.get_playlist(plex_id=plex_id)
        IGNORE_KODI_PLAYLIST_CHANGE.append(playlist.kodi_path)
        LOG.debug('Removing outdated Plex playlist from Kodi: %s', playlist)
        try:
            kodi_pl.delete(playlist)
        except PlaylistError:
            LOG.debug('Skipping deletion of playlist: %s', playlist)
            IGNORE_KODI_PLAYLIST_CHANGE.remove(playlist.kodi_path)
    # Look at all supported Kodi playlists. Check whether they are in the DB.
    old_kodi_paths = db.kodi_playlist_paths()
    for root, _, files in path_ops.walk(v.PLAYLIST_PATH):
        for f in files:
            path = path_ops.path.join(root, f)
            try:
                old_kodi_paths.remove(path)
            except ValueError:
                pass
            if not sync_kodi_playlist(path):
                continue
            kodi_hash = utils.generate_file_md5(path)
            playlist = db.get_playlist(path=path)
            if playlist and playlist.kodi_hash == kodi_hash:
                continue
            if not playlist:
                LOG.debug('New Kodi playlist detected: %s', path)
                playlist = Playlist()
                playlist.kodi_path = path
                playlist.kodi_hash = kodi_hash
                try:
                    plex_pl.create(playlist)
                except PlaylistError:
                    LOG.info('Skipping Kodi playlist %s', path)
            else:
                LOG.debug('Changed Kodi playlist detected: %s', path)
                IGNORE_PLEX_PLAYLIST_CHANGE.append(playlist.plex_id)
                plex_pl.delete(playlist)
                playlist.kodi_hash = kodi_hash
                try:
                    plex_pl.create(playlist)
                except PlaylistError:
                    LOG.info('Skipping Kodi playlist %s', path)
    for kodi_path in old_kodi_paths:
        playlist = db.get_playlist(path=kodi_path)
        try:
            plex_pl.delete(playlist)
        except PlaylistError:
            LOG.debug('Skipping deletion of Plex playlist: %s', playlist)
    LOG.info('Playlist full sync done')
    return True


def sync_kodi_playlist(path):
    """
    Checks whether we should sync a specific Kodi playlist to Plex

    Will check the following conditions for one single Kodi playlist:
    * Kodi mixed playlists return False
    * Support of the file type of the playlist, e.g. m3u
    * Whether filename matches user settings to sync, if enabled

    Parameters
    ----------
    path : unicode
        Absolute file path to the Kodi playlist in question

    Returns
    -------
    bool
        True if we should sync this Kodi playlist to Plex, False otherwise
    """
    if path.startswith(v.PLAYLIST_PATH_MIXED):
        return False
    try:
        extension = path.rsplit('.', 1)[1].lower()
    except IndexError:
        return False
    if extension not in SUPPORTED_FILETYPES:
        return False
    if not state.SYNC_SPECIFIC_KODI_PLAYLISTS:
        return True
    playlist = Playlist()
    playlist.kodi_path = path
    prefix = utils.settings('syncSpecificKodiPlaylistsPrefix').lower()
    if playlist.kodi_filename.lower().startswith(prefix):
        return True
    LOG.debug('User chose to not sync Kodi playlist %s', path)
    return False


def sync_plex_playlist(playlist=None, xml=None, plex_id=None):
    """
    Checks whether we should sync a specific Plex playlist to Kodi

    Will check the following conditions for one single Plex playlist:
    * Plex music playlists return False if PKC audio sync is disabled
    * Whether filename matches user settings to sync, if enabled
    * False is returned if we could not retrieve more information about the
      playlist if only the plex_id was given

    Parameters
    ----------
    Pass in either playlist, xml or plex_id (preferably in this order)

    plex_id : unicode
        Absolute file path to the Kodi playlist in question
    xml : etree xml
        PMS metadata for the Plex element in question. API(xml) instead of
        the usual API(xml[0]) will be used!
    playlist: PlayList
        A PlayList instance with Playlist.plex_name and PlayList.kodi_type set

    Returns
    -------
    bool
        True if we should sync this Plex playlist to Kodi, False otherwise
    """
    if playlist:
        # Mainly once we DELETED a Plex playlist that we're NOT supposed
        # to sync
        name = playlist.plex_name
        typus = playlist.kodi_type
    else:
        if xml is None:
            xml = pms.metadata(plex_id)
            if xml is None:
                LOG.info('Could not get Plex metadata for playlist %s',
                         plex_id)
                return False
            api = API(xml[0])
        else:
            api = API(xml)
        if api.playlist_type() == v.PLEX_TYPE_PHOTO_PLAYLIST:
            # Not supported by Kodi
            return False
        name = api.title()
        typus = v.KODI_PLAYLIST_TYPE_FROM_PLEX[api.playlist_type()]
    if (not state.ENABLE_MUSIC and typus == v.PLEX_PLAYLIST_TYPE_AUDIO):
        LOG.debug('Not synching Plex audio playlist')
        return False
    if not state.SYNC_SPECIFIC_PLEX_PLAYLISTS:
        return True
    prefix = utils.settings('syncSpecificPlexPlaylistsPrefix').lower()
    if name and name.lower().startswith(prefix):
        return True
    LOG.debug('User chose to not sync Plex playlist %s', name)
    return False


class PlaylistEventhandler(events.FileSystemEventHandler):
    """
    PKC eventhandler to monitor Kodi playlists safed to disk
    """
    def dispatch(self, event):
        """
        Dispatches events to the appropriate methods.

        Parameters
        ----------
        :type event:
            :class:`FileSystemEvent`
            The event object representing the file system event.
        """
        path = event.dest_path if event.event_type == events.EVENT_TYPE_MOVED \
            else event.src_path
        if not sync_kodi_playlist(path):
            return
        playlist = db.get_playlist(path=path)
        if playlist and playlist.plex_id in IGNORE_KODI_PLAYLIST_CHANGE:
            LOG.debug('Ignoring event %s for playlist %s', event, playlist)
            IGNORE_KODI_PLAYLIST_CHANGE.remove(playlist.plex_id)
            return
        if not playlist and path in IGNORE_KODI_PLAYLIST_CHANGE:
            LOG.debug('Ignoring deletion event %s for playlist %s',
                      event, playlist)
            IGNORE_KODI_PLAYLIST_CHANGE.remove(path)
            return
        _method_map = {
            events.EVENT_TYPE_MODIFIED: self.on_modified,
            events.EVENT_TYPE_MOVED: self.on_moved,
            events.EVENT_TYPE_CREATED: self.on_created,
            events.EVENT_TYPE_DELETED: self.on_deleted,
        }
        with state.LOCK_PLAYLISTS:
            _method_map[event.event_type](event)

    def on_created(self, event):
        LOG.debug('on_created: %s', event.src_path)
        old_playlist = db.get_playlist(path=event.src_path)
        kodi_hash = utils.generate_file_md5(event.src_path)
        if old_playlist and old_playlist.kodi_hash == kodi_hash:
            LOG.debug('Playlist already in DB - skipping')
            return
        elif old_playlist:
            LOG.debug('Playlist already in DB but it has been changed')
            self.on_modified(event)
            return
        playlist = Playlist()
        playlist.kodi_path = event.src_path
        playlist.kodi_hash = kodi_hash
        try:
            plex_pl.create(playlist)
        except PlaylistError:
            pass

    def on_modified(self, event):
        LOG.debug('on_modified: %s', event.src_path)
        old_playlist = db.get_playlist(path=event.src_path)
        kodi_hash = utils.generate_file_md5(event.src_path)
        if old_playlist and old_playlist.kodi_hash == kodi_hash:
            LOG.debug('Nothing modified, playlist already in DB - skipping')
            return
        new_playlist = Playlist()
        if old_playlist:
            # Retain the name! Might've come from Plex
            # (rename should fire on_moved)
            new_playlist.plex_name = old_playlist.plex_name
            plex_pl.delete(old_playlist)
        new_playlist.kodi_path = event.src_path
        new_playlist.kodi_hash = kodi_hash
        try:
            plex_pl.create(new_playlist)
        except PlaylistError:
            pass

    def on_moved(self, event):
        LOG.debug('on_moved: %s to %s', event.src_path, event.dest_path)
        kodi_hash = utils.generate_file_md5(event.dest_path)
        # First check whether we don't already have destination playlist in
        # our DB. Just in case....
        old_playlist = db.get_playlist(path=event.dest_path)
        if old_playlist:
            LOG.warning('Found target playlist already in our DB!')
            new_event = events.FileModifiedEvent(event.dest_path)
            self.on_modified(new_event)
            return
        # All good
        old_playlist = db.get_playlist(path=event.src_path)
        if not old_playlist:
            LOG.debug('Did not have source path in the DB %s', event.src_path)
        else:
            plex_pl.delete(old_playlist)
        new_playlist = Playlist()
        new_playlist.kodi_path = event.dest_path
        new_playlist.kodi_hash = kodi_hash
        try:
            plex_pl.create(new_playlist)
        except PlaylistError:
            pass

    def on_deleted(self, event):
        LOG.debug('on_deleted: %s', event.src_path)
        playlist = db.get_playlist(path=event.src_path)
        if not playlist:
            LOG.debug('Playlist not found in DB for path %s', event.src_path)
        else:
            plex_pl.delete(playlist)
