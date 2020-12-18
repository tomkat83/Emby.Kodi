#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .movies import Movie
from .tvshows import Show, Season, Episode
from .music import Artist, Album, Song
from .. import variables as v

# Note: always use same order of URL arguments, NOT urlencode:
#   plex_id=<plex_id>&plex_type=<plex_type>&mode=play

ITEMTYPE_FROM_PLEXTYPE = {
    v.PLEX_TYPE_MOVIE: Movie,
    v.PLEX_TYPE_SHOW: Show,
    v.PLEX_TYPE_SEASON: Season,
    v.PLEX_TYPE_EPISODE: Episode,
    v.PLEX_TYPE_ARTIST: Artist,
    v.PLEX_TYPE_ALBUM: Album,
    v.PLEX_TYPE_SONG: Song
}

ITEMTYPE_FROM_KODITYPE = {
    v.KODI_TYPE_MOVIE: Movie,
    v.KODI_TYPE_SHOW: Show,
    v.KODI_TYPE_SEASON: Season,
    v.KODI_TYPE_EPISODE: Episode,
    v.KODI_TYPE_ARTIST: Artist,
    v.KODI_TYPE_ALBUM: Album,
    v.KODI_TYPE_SONG: Song
}
