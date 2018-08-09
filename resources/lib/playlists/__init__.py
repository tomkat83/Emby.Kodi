#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Syncs Plex playlists <=> Kodi playlists with 3 main components:

kodi_playlist_monitor()
watchdog Observer checking whether Kodi playlists are changed

websocket(plex_id, status)
Hit with websocket answers from our background sync

full_sync()
Triggers a full re-sync of playlists

PlaylistError is thrown if anything wierd happens
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .common import Playlist, PlaylistError, PlaylistObserver
from . import pms, db, kodi_pl, plex_pl

from ..watchdog import events
from ..plex_api import API
from .. import utils
from .. import path_ops
from .. import variables as v
from .. import state

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
# Avoid endless loops
IGNORE_KODI_PLAYLIST_CHANGE = list()
###############################################################################


def kodi_playlist_monitor():
    """
    Monitors the Kodi playlist folder special://profile/playlist for the user.
    Will thus catch all changes on the Kodi side of things.

    Returns an watchdog Observer instance. Be sure to use
    observer.stop() (and maybe observer.join()) to shut down properly
    """
    event_handler = PlaylistEventhandler()
    observer = PlaylistObserver(timeout=FILESYSTEM_TIMEOUT)
    observer.schedule(event_handler, v.PLAYLIST_PATH, recursive=True)
    observer.start()
    return observer


def websocket(plex_id, status):
    """
    Hit by librarysync to process websocket messages concerning playlists
    """
    create = False
    with state.LOCK_PLAYLISTS:
        playlist = db.get_playlist(plex_id=plex_id)
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
    Full sync of playlists between Kodi and Plex. Returns True is successful,
    False otherwise
    """
    LOG.info('Starting playlist full sync')
    with state.LOCK_PLAYLISTS:
        return _full_sync()


def _full_sync():
    """
    Need to lock because we're messing with playlists
    """
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
        try:
            if not playlist:
                LOG.debug('New Plex playlist %s discovered: %s',
                          api.plex_id(), api.title())
                IGNORE_KODI_PLAYLIST_CHANGE.append(api.plex_id())
                kodi_pl.create(api.plex_id())
            elif playlist.plex_updatedat != api.updated_at():
                LOG.debug('Detected changed Plex playlist %s: %s',
                          api.plex_id(), api.title())
                IGNORE_KODI_PLAYLIST_CHANGE.append(api.plex_id())
                kodi_pl.delete(playlist)
                IGNORE_KODI_PLAYLIST_CHANGE.append(api.plex_id())
                kodi_pl.create(api.plex_id())
        except PlaylistError:
            LOG.info('Skipping playlist %s: %s', api.plex_id(), api.title())
            IGNORE_KODI_PLAYLIST_CHANGE.remove(api.plex_id())
    # Get rid of old Plex playlists that were deleted on the Plex side
    for plex_id in old_plex_ids:
        playlist = db.get_playlist(plex_id=plex_id)
        LOG.debug('Removing outdated Plex playlist: %s', playlist)
        try:
            IGNORE_KODI_PLAYLIST_CHANGE.append(playlist.plex_id)
            kodi_pl.delete(playlist)
        except PlaylistError:
            LOG.debug('Skipping deletion of playlist: %s', playlist)
            IGNORE_KODI_PLAYLIST_CHANGE.remove(playlist.plex_id)
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
            try:
                if not playlist:
                    LOG.debug('New Kodi playlist detected: %s', path)
                    playlist = Playlist()
                    playlist.kodi_path = path
                    playlist.kodi_hash = kodi_hash
                    plex_pl.create(playlist)
                else:
                    LOG.debug('Changed Kodi playlist detected: %s', path)
                    plex_pl.delete(playlist)
                    playlist.kodi_hash = kodi_hash
                    plex_pl.create(playlist)
            except PlaylistError:
                LOG.info('Skipping Kodi playlist %s', path)
    for kodi_path in old_kodi_paths:
        playlist = db.get_playlist(path=kodi_path)
        try:
            plex_pl.delete(playlist)
        except PlaylistError:
            LOG.debug('Skipping deletion of playlist: %s', playlist)
    LOG.info('Playlist full sync done')
    return True


def sync_kodi_playlist(path):
    """
    Returns True if we should sync this Kodi playlist with path [unicode] to
    Plex based on the playlist file name and the user settings, False otherwise
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


def sync_plex_playlist(plex_id=None, xml=None, playlist=None):
    """
    Returns True if we should sync this specific Plex playlist due to the
    user settings (including a disabled music library), False if not.

    Pass in either the plex_id or an xml (where API(xml) will be used)
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
    if not state.SYNC_SPECIFIC_PLEX_PLAYLISTS:
        return True
    if (not state.ENABLE_MUSIC and typus == v.PLEX_PLAYLIST_TYPE_AUDIO):
        LOG.debug('Not synching Plex audio playlist')
        return False
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

        :param event:
            The event object representing the file system event.
        :type event:
            :class:`FileSystemEvent`
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
