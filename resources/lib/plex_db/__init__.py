#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .common import PlexDBBase, initialize, wipe, PLEXDB_LOCK
from .tvshows import TVShows
from .movies import Movies
from .music import Music
from .playlists import Playlists
from .sections import Sections


class PlexDB(PlexDBBase, TVShows, Movies, Music, Playlists, Sections):
    pass
