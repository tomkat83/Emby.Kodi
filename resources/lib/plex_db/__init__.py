#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals

from .common import PlexDBBase, initialize, wipe, PLEXDB_LOCK
from .tvshows import TVShows
from .movies import Movies
from .music import Music
from .playlists import Playlists
from .sections import Sections


class PlexDB(PlexDBBase, TVShows, Movies, Music, Playlists, Sections):
    pass


def kodi_from_plex(plex_id, plex_type=None):
    """
    Returns the tuple (kodi_id, kodi_type) for plex_id. Faster, if plex_type
    is provided

    Returns (None, None) if unsuccessful
    """
    with PlexDB(lock=False) as plexdb:
        db_item = plexdb.item_by_id(plex_id, plex_type)
    if db_item:
        return (db_item['kodi_id'], db_item['kodi_type'])
    else:
        return None, None
