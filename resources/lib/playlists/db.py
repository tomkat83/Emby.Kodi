#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Synced playlists are stored in our plex.db. Interact with it through this
module
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .common import Playlist, PlaylistError

from .. import kodidb_functions as kodidb
from .. import plexdb_functions as plexdb
from .. import path_ops, utils, variables as v
###############################################################################
LOG = getLogger('PLEX.playlists.db')

###############################################################################


def plex_playlist_ids():
    """
    Returns a list of all Plex ids of the playlists already in our DB
    """
    with plexdb.Get_Plex_DB() as plex_db:
        return plex_db.plex_ids_all_playlists()


def kodi_playlist_paths():
    """
    Returns a list of all Kodi playlist paths of the playlists already synced
    """
    with plexdb.Get_Plex_DB() as plex_db:
        return plex_db.all_kodi_playlist_paths()


def update_playlist(playlist, delete=False):
    """
    Assumes that all sync operations are over. Takes playlist [Playlist]
    and creates/updates the corresponding Plex playlists table entry

    Pass delete=True to delete the playlist entry
    """
    with plexdb.Get_Plex_DB() as plex_db:
        if delete:
            plex_db.delete_playlist_entry(playlist)
        else:
            plex_db.insert_playlist_entry(playlist)


def get_playlist(path=None, kodi_hash=None, plex_id=None):
    """
    Returns the playlist as a Playlist for either the plex_id, path or
    kodi_hash. kodi_hash will be more reliable as it includes path and file
    content.
    """
    playlist = Playlist()
    with plexdb.Get_Plex_DB() as plex_db:
        playlist = plex_db.retrieve_playlist(playlist,
                                             plex_id,
                                             path, kodi_hash)
    return playlist


def _m3u_iterator(text):
    """
    Yields e.g. plugin://plugin.video.plexkodiconnect.movies/?plex_id=xxx
    """
    lines = iter(text.split('\n'))
    for line in lines:
        if line.startswith('#EXTINF:'):
            yield next(lines).strip()


def m3u_to_plex_ids(playlist):
    """
    Adapter to process *.m3u playlist files. Encoding is not uniform!
    """
    plex_ids = list()
    with open(path_ops.encode_path(playlist.kodi_path), 'rb') as f:
        text = f.read()
    try:
        text = text.decode(v.M3U_ENCODING)
    except UnicodeDecodeError:
        LOG.warning('Fallback to ISO-8859-1 decoding for %s', playlist)
        text = text.decode('ISO-8859-1')
    for entry in _m3u_iterator(text):
        plex_id = utils.REGEX_PLEX_ID.search(entry)
        if plex_id:
            plex_id = plex_id.group(1)
            plex_ids.append(plex_id)
        else:
            # Add-on paths not working, try direct
            kodi_id, kodi_type = kodidb.kodiid_from_filename(
                entry, db_type=playlist.kodi_type)
            if not kodi_id:
                continue
            with plexdb.Get_Plex_DB() as plex_db:
                plex_id = plex_db.getItem_byKodiId(kodi_id, kodi_type)
            if plex_id:
                plex_ids.append(plex_id[0])
    return plex_ids


def playlist_file_to_plex_ids(playlist):
    """
    Takes the playlist file located at path [unicode] and parses it.
    Returns a list of plex_ids (str) or raises PL.PlaylistError if a single
    item cannot be parsed from Kodi to Plex.
    """
    if playlist.kodi_extension == 'm3u':
        plex_ids = m3u_to_plex_ids(playlist)
    else:
        LOG.error('Unsupported playlist extension: %s',
                  playlist.kodi_extension)
        raise PlaylistError
    return plex_ids
