#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

import xbmc

from .common import PLAYQUEUES, PlaylistItem
from .playqueue import PlayQueue

from ..downloadutils import DownloadUtils as DU
from .. import json_rpc as js, app, variables as v, plex_functions as PF
from .. import utils

LOG = getLogger('PLEX.playqueue_functions')


def init_playqueues():
    """
    Call this once on startup to initialize the PKC playqueue objects in
    the list PLAYQUEUES
    """
    if PLAYQUEUES:
        LOG.debug('Playqueues have already been initialized')
        return
    # Initialize Kodi playqueues
    with app.APP.lock_playqueues:
        for i in (0, 1, 2):
            # Just in case the Kodi response is not sorted correctly
            for queue in js.get_playlists():
                if queue['playlistid'] != i:
                    continue
                playqueue = PlayQueue()
                playqueue.playlistid = i
                playqueue.type = queue['type']
                # Initialize each Kodi playlist
                if playqueue.type == v.KODI_TYPE_AUDIO:
                    playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
                elif playqueue.type == v.KODI_TYPE_VIDEO:
                    playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                else:
                    # Currently, only video or audio playqueues available
                    playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                    # Overwrite 'picture' with 'photo'
                    playqueue.type = v.KODI_TYPE_PHOTO
                PLAYQUEUES.append(playqueue)
    LOG.debug('Initialized the Kodi playqueues: %s', PLAYQUEUES)


def get_playqueue_from_type(kodi_playlist_type):
    """
    Returns the playqueue according to the kodi_playlist_type ('video',
    'audio', 'picture') passed in
    """
    for playqueue in PLAYQUEUES:
        if playqueue.type == kodi_playlist_type:
            break
    else:
        raise ValueError('Wrong playlist type passed in: %s'
                         % kodi_playlist_type)
    return playqueue


def playqueue_from_plextype(plex_type):
    if plex_type in v.PLEX_VIDEOTYPES:
        plex_type = v.PLEX_TYPE_VIDEO_PLAYLIST
    elif plex_type in v.PLEX_AUDIOTYPES:
        plex_type = v.PLEX_TYPE_AUDIO_PLAYLIST
    else:
        plex_type = v.PLEX_TYPE_VIDEO_PLAYLIST
    for playqueue in PLAYQUEUES:
        if playqueue.type == plex_type:
            break
    return playqueue


def playqueue_from_id(kodi_playlist_id):
    for playqueue in PLAYQUEUES:
        if playqueue.playlistid == kodi_playlist_id:
            break
    else:
        raise ValueError('Wrong playlist id passed in: %s of type %s'
                         % (kodi_playlist_id, type(kodi_playlist_id)))
    return playqueue


def init_playqueue_from_plex_children(plex_id, transient_token=None):
    """
    Init a new playqueue e.g. from an album. Alexa does this

    Returns the playqueue
    """
    xml = PF.GetAllPlexChildren(plex_id)
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not download the PMS xml for %s', plex_id)
        return
    playqueue = get_playqueue_from_type(
        v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[xml[0].attrib['type']])
    playqueue.clear()
    for i, child in enumerate(xml):
        playlistitem = PlaylistItem(xml_video_element=child)
        playqueue.add_item(playlistitem, i)
    playqueue.plex_transient_token = transient_token
    LOG.debug('Firing up Kodi player')
    app.APP.player.play(playqueue.kodi_pl, None, False, 0)
    return playqueue


def get_PMS_playlist(playlist=None, playlist_id=None):
    """
    Fetches the PMS playlist/playqueue as an XML. Pass in playlist_id if we
    need to fetch a new playlist

    Returns None if something went wrong
    """
    playlist_id = playlist_id if playlist_id else playlist.id
    if playlist and playlist.kind == 'playList':
        xml = DU().downloadUrl("{server}/playlists/%s/items" % playlist_id)
    else:
        xml = DU().downloadUrl("{server}/playQueues/%s" % playlist_id)
    try:
        xml.attrib
    except AttributeError:
        xml = None
    return xml


def get_pms_playqueue(playqueue_id):
    """
    Returns the Plex playqueue as an etree XML or None if unsuccessful
    """
    xml = DU().downloadUrl(
        "{server}/playQueues/%s" % playqueue_id,
        headerOptions={'Accept': 'application/xml'})
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not download Plex playqueue %s', playqueue_id)
        xml = None
    return xml


def get_plextype_from_xml(xml):
    """
    Needed if PMS returns an empty playqueue. Will get the Plex type from the
    empty playlist playQueueSourceURI. Feed with (empty) etree xml

    returns None if unsuccessful
    """
    try:
        plex_id = utils.REGEX_PLEX_ID_FROM_URL.findall(
            xml.attrib['playQueueSourceURI'])[0]
    except IndexError:
        LOG.error('Could not get plex_id from xml: %s', xml.attrib)
        return
    new_xml = PF.GetPlexMetadata(plex_id)
    try:
        new_xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not get plex metadata for plex id %s', plex_id)
        return
    return new_xml[0].attrib.get('type').decode('utf-8')
