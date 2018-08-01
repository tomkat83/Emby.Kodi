#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Functions to communicate with the currently connected PMS in order to
manipulate playlists
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import urllib

from .common import PlaylistError

from ..plex_api import API
from ..downloadutils import DownloadUtils as DU
from .. import variables as v
###############################################################################
LOG = getLogger('PLEX.playlists.pms')

###############################################################################


def all_playlists():
    """
    Returns an XML with all Plex playlists or None
    """
    xml = DU().downloadUrl('{server}/playlists')
    try:
        xml.attrib
    except (AttributeError, TypeError):
        LOG.error('Could not download a list of all playlists')
        xml = None
    return xml


def get_playlist(plex_id):
    """
    Fetches the PMS playlist/playqueue as an XML. Pass in playlist id
    Returns None if something went wrong
    """
    xml = DU().downloadUrl("{server}/playlists/%s/items" % plex_id)
    try:
        xml.attrib
    except AttributeError:
        xml = None
    return xml


def initialize(playlist, plex_id):
    """
    Initializes a new playlist on the PMS side. Will set playlist.plex_id and
    playlist.plex_updatedat. Will raise PlaylistError if something went wrong.
    """
    LOG.debug('Initializing the playlist with Plex id %s on the Plex side: %s',
              plex_id, playlist)
    params = {
        'type': v.PLEX_PLAYLIST_TYPE_FROM_KODI[playlist.kodi_type],
        'title': playlist.plex_name,
        'smart': 0,
        'uri': ('library://None/item/%s' % (urllib.quote('/library/metadata/%s'
                                                         % plex_id, safe='')))
    }
    xml = DU().downloadUrl(url='{server}/playlists',
                           action_type='POST',
                           parameters=params)
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not initialize playlist on Plex side with plex id %s',
                  plex_id)
        raise PlaylistError('Could not initialize Plex playlist %s', plex_id)
    api = API(xml[0])
    playlist.plex_id = api.plex_id()
    playlist.plex_updatedat = api.updated_at()


def add_item(playlist, plex_id):
    """
    Adds the item with plex_id to the existing Plex playlist (at the end).
    Will set playlist.plex_updatedat
    Raises PlaylistError if that did not work out.
    """
    params = {
        'uri': ('library://None/item/%s' % (urllib.quote('/library/metadata/%s'
                                                         % plex_id, safe='')))
    }
    xml = DU().downloadUrl(url='{server}/playlists/%s/items' % playlist.plex_id,
                           action_type='PUT',
                           parameters=params)
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not initialize playlist on Plex side with plex id %s',
                  plex_id)
        raise PlaylistError('Could not item %s to Plex playlist %s',
                            plex_id, playlist)
    api = API(xml[0])
    playlist.plex_updatedat = api.updated_at()


def metadata(plex_id):
    """
    Returns an xml with the entire metadata like updatedAt.
    """
    xml = DU().downloadUrl('{server}/playlists/%s' % plex_id)
    try:
        xml.attrib
    except AttributeError:
        xml = None
    return xml


def delete(playlist):
    """
    Deletes the playlist from the PMS
    """
    DU().downloadUrl('{server}/playlists/%s' % playlist.plex_id,
                     action_type="DELETE")
