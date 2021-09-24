#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Create and delete playlists on the Plex side of things
"""
from logging import getLogger

from . import pms, db
from ..exceptions import PlaylistError

###############################################################################
LOG = getLogger('PLEX.playlists.plex_pl')
# Used for updating Plex playlists due to Kodi changes - Plex playlist
# will have to be deleted first. Add Plex ids!
IGNORE_PLEX_PLAYLIST_CHANGE = list()
###############################################################################


def create(playlist):
    """
    Adds the playlist Playlist to the PMS. If playlist.id is
    not None the existing Plex playlist will be overwritten; otherwise a new
    playlist will be generated and stored accordingly in the playlist object.
    Will also add (or modify an existing) Plex playlist table entry.
    Make sure that playlist.kodi_hash is set!
    Returns None or raises PlaylistError
    """
    LOG.debug('Creating Plex playlist from Kodi file: %s', playlist)
    plex_ids = db.playlist_file_to_plex_ids(playlist)
    if not plex_ids:
        LOG.warning('No Plex ids found for playlist %s', playlist)
        raise PlaylistError
    pms.add_items(playlist, plex_ids)
    IGNORE_PLEX_PLAYLIST_CHANGE.append(playlist.plex_id)
    db.update_playlist(playlist)
    LOG.debug('Done creating Plex playlist %s', playlist)


def delete(playlist):
    """
    Removes the playlist Playlist from the PMS. Will also delete the
    entry in the Plex playlist table.
    Returns None or raises PlaylistError
    """
    LOG.debug('Deleting playlist from PMS: %s', playlist)
    IGNORE_PLEX_PLAYLIST_CHANGE.append(playlist.plex_id)
    pms.delete(playlist)
    db.update_playlist(playlist, delete=True)
