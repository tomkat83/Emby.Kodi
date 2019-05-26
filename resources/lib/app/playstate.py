#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals


class PlayState(object):
    # "empty" dict for the PLAYER_STATES above. Use copy.deepcopy to duplicate!
    template = {
        'type': None,
        'time': {
            'hours': 0,
            'minutes': 0,
            'seconds': 0,
            'milliseconds': 0},
        'totaltime': {
            'hours': 0,
            'minutes': 0,
            'seconds': 0,
            'milliseconds': 0},
        'speed': 0,
        'shuffled': False,
        'repeat': 'off',
        'position': None,
        'playlistid': None,
        'currentvideostream': -1,
        'currentaudiostream': -1,
        'subtitleenabled': False,
        'currentsubtitle': -1,
        'file': None,
        'kodi_id': None,
        'kodi_type': None,
        'plex_id': None,
        'plex_type': None,
        'container_key': None,
        'volume': 100,
        'muted': False,
        'playmethod': None,
        'playcount': None
    }

    def __init__(self):
        # Kodi player states - here, initial values are set
        self.player_states = {
            0: {},
            1: {},
            2: {}
        }
        # The LAST playstate once playback is finished
        self.old_player_states = {
            0: {},
            1: {},
            2: {}
        }
        self.played_info = {}

        # Set by SpecialMonitor - did user choose to resume playback or start
        # from the beginning?
        # Do set to None if NO resume dialog is displayed! True/False otherwise
        self.resume_playback = None
        # Don't ask user whether to resume but immediatly resume
        self.autoplay = False
        # Was the playback initiated by the user using the Kodi context menu?
        self.context_menu_play = False
        # Which Kodi player is/has been active? (either int 0, 1, 2)
        self.active_players = set()
        # Have we initiated playback via Plex Companion or Alexa - so from the
        # Plex side of things?
        self.initiated_by_plex = False
        # PKC adds/replaces items in the playqueue. We need to use
        # xbmcplugin.setResolvedUrl() AFTER an item has successfully been added
        # This flag is set by Kodimonitor/xbmc.Monitor() and the Playlist.OnAdd
        # signal only when the currently playing item that called the
        # webservice has successfully been processed
        self.playlist_ready = False
        # Flag for Kodimonitor to check when the correct item has been
        # processed and the Playlist.OnAdd signal has been received
        self.playlist_start_pos = None
