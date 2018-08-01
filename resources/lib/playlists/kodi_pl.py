#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Create and delete playlists on the Kodi side of things
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .common import Playlist, PlaylistError
from . import db, pms

from ..plex_api import API
from .. import utils, path_ops, variables as v
###############################################################################
LOG = getLogger('PLEX.playlists.kodi_pl')

###############################################################################


def create(plex_id):
    """
    Creates a new Kodi playlist file. Will also add (or modify an existing)
    Plex playlist table entry.
    Assumes that the Plex playlist is indeed new. A NEW Kodi playlist will be
    created in any case (not replaced). Thus make sure that the "same" playlist
    is deleted from both disk and the Plex database.
    Returns the playlist or raises PlaylistError
    """
    xml_metadata = pms.metadata(plex_id)
    if xml_metadata is None:
        LOG.error('Could not get Plex playlist metadata %s', plex_id)
        raise PlaylistError('Could not get Plex playlist %s' % plex_id)
    api = API(xml_metadata[0])
    playlist = Playlist()
    playlist.plex_id = api.plex_id()
    playlist.kodi_type = v.KODI_PLAYLIST_TYPE_FROM_PLEX[api.playlist_type()]
    playlist.plex_name = api.title()
    playlist.plex_updatedat = api.updated_at()
    LOG.debug('Creating new Kodi playlist from Plex playlist: %s', playlist)
    # Derive filename close to Plex playlist name
    name = utils.valid_filename(playlist.plex_name)
    path = path_ops.path.join(v.PLAYLIST_PATH, playlist.kodi_type,
                              '%s.m3u' % name)
    while path_ops.exists(path) or db.get_playlist(path=path):
        # In case the Plex playlist names are not unique
        occurance = utils.REGEX_FILE_NUMBERING.search(path)
        if not occurance:
            path = path_ops.path.join(v.PLAYLIST_PATH,
                                      playlist.kodi_type,
                                      '%s_01.m3u' % name[:min(len(name), 248)])
        else:
            occurance = int(occurance.group(1)) + 1
            path = path_ops.path.join(v.PLAYLIST_PATH,
                                      playlist.kodi_type,
                                      '%s_%02d.m3u' % (name[:min(len(name),
                                                                 248)],
                                                       occurance))
    LOG.debug('Kodi playlist path: %s', path)
    playlist.kodi_path = path
    xml_playlist = pms.get_playlist(plex_id)
    if xml_playlist is None:
        LOG.error('Could not get Plex playlist %s', plex_id)
        raise PlaylistError('Could not get Plex playlist %s' % plex_id)
    _write_playlist_to_file(playlist, xml_playlist)
    playlist.kodi_hash = utils.generate_file_md5(path)
    db.update_playlist(playlist)
    LOG.debug('Created Kodi playlist based on Plex playlist: %s', playlist)


def delete(playlist):
    """
    Removes the corresponding Kodi file for playlist Playlist from
    disk. Be sure that playlist.kodi_path is set. Will also delete the entry in
    the Plex playlist table.
    Returns None or raises PlaylistError
    """
    if path_ops.exists(playlist.kodi_path):
        try:
            path_ops.remove(playlist.kodi_path)
            LOG.debug('Deleted Kodi playlist: %s', playlist)
        except (OSError, IOError) as err:
            LOG.error('Could not delete Kodi playlist file %s. Error:\n%s: %s',
                      playlist, err.errno, err.strerror)
            raise PlaylistError('Could not delete %s' % playlist.kodi_path)
    db.update_playlist(playlist, delete=True)


def _write_playlist_to_file(playlist, xml):
    """
    Feed with playlist Playlist. Will write the playlist to a m3u file
    Returns None or raises PlaylistError
    """
    text = '#EXTCPlayListM3U::M3U\n'
    for element in xml:
        api = API(element)
        append_season_episode = False
        if api.plex_type() == v.PLEX_TYPE_EPISODE:
            _, show, season_id, episode_id = api.episode_data()
            try:
                season_id = int(season_id)
                episode_id = int(episode_id)
            except ValueError:
                pass
            else:
                append_season_episode = True
            if append_season_episode:
                text += ('#EXTINF:%s,%s S%.2dE%.2d - %s\n%s\n'
                         % (api.runtime(), show, season_id, episode_id,
                            api.title(), api.path()))
            else:
                # Only append the TV show name
                text += ('#EXTINF:%s,%s - %s\n%s\n'
                         % (api.runtime(), show, api.title(), api.path()))
        else:
            text += ('#EXTINF:%s,%s\n%s\n'
                     % (api.runtime(), api.title(), api.path()))
    text += '\n'
    text = text.encode(v.M3U_ENCODING, 'strict')
    try:
        with open(path_ops.encode_path(playlist.kodi_path), 'wb') as f:
            f.write(text)
    except EnvironmentError as err:
        LOG.error('Could not write Kodi playlist file: %s', playlist)
        LOG.error('Error message %s: %s', err.errno, err.strerror)
        raise PlaylistError('Cannot write Kodi playlist to path for %s'
                            % playlist)
