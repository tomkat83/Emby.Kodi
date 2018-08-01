#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Processes Plex companion inputs from the plexbmchelper to Kodi commands
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from xbmc import Player

from . import playqueue as PQ
from . import plex_functions as PF
from . import json_rpc as js
from . import variables as v
from . import state

###############################################################################

LOG = getLogger('PLEX.companion')

###############################################################################


def skip_to(params):
    """
    Skip to a specific playlist position.

    Does not seem to be implemented yet by Plex!
    """
    playqueue_item_id = params.get('playQueueItemID')
    _, plex_id = PF.GetPlexKeyNumber(params.get('key'))
    LOG.debug('Skipping to playQueueItemID %s, plex_id %s',
              playqueue_item_id, plex_id)
    found = True
    for player in js.get_players().values():
        playqueue = PQ.PLAYQUEUES[player['playerid']]
        for i, item in enumerate(playqueue.items):
            if item.id == playqueue_item_id:
                found = True
                break
        else:
            for i, item in enumerate(playqueue.items):
                if item.plex_id == plex_id:
                    found = True
                    break
        if found is True:
            Player().play(playqueue.kodi_pl, None, False, i)
        else:
            LOG.error('Item not found to skip to')


def convert_alexa_to_companion(dictionary):
    """
    The params passed by Alexa must first be converted to Companion talk
    """
    for key in dictionary:
        if key in v.ALEXA_TO_COMPANION:
            dictionary[v.ALEXA_TO_COMPANION[key]] = dictionary[key]
            del dictionary[key]


def process_command(request_path, params):
    """
    queue: Queue() of PlexCompanion.py
    """
    if params.get('deviceName') == 'Alexa':
        convert_alexa_to_companion(params)
    LOG.debug('Received request_path: %s, params: %s', request_path, params)
    if request_path == 'player/playback/playMedia':
        # We need to tell service.py
        action = 'alexa' if params.get('deviceName') == 'Alexa' else 'playlist'
        state.COMPANION_QUEUE.put({
            'action': action,
            'data': params
        })
    elif request_path == 'player/playback/refreshPlayQueue':
        state.COMPANION_QUEUE.put({
            'action': 'refreshPlayQueue',
            'data': params
        })
    elif request_path == "player/playback/setParameters":
        if 'volume' in params:
            js.set_volume(int(params['volume']))
        else:
            LOG.error('Unknown parameters: %s', params)
    elif request_path == "player/playback/play":
        js.play()
    elif request_path == "player/playback/pause":
        js.pause()
    elif request_path == "player/playback/stop":
        js.stop()
    elif request_path == "player/playback/seekTo":
        js.seek_to(int(params.get('offset', 0)))
    elif request_path == "player/playback/stepForward":
        js.smallforward()
    elif request_path == "player/playback/stepBack":
        js.smallbackward()
    elif request_path == "player/playback/skipNext":
        js.skipnext()
    elif request_path == "player/playback/skipPrevious":
        js.skipprevious()
    elif request_path == "player/playback/skipTo":
        skip_to(params)
    elif request_path == "player/navigation/moveUp":
        js.input_up()
    elif request_path == "player/navigation/moveDown":
        js.input_down()
    elif request_path == "player/navigation/moveLeft":
        js.input_left()
    elif request_path == "player/navigation/moveRight":
        js.input_right()
    elif request_path == "player/navigation/select":
        js.input_select()
    elif request_path == "player/navigation/home":
        js.input_home()
    elif request_path == "player/navigation/back":
        js.input_back()
    elif request_path == "player/playback/setStreams":
        state.COMPANION_QUEUE.put({
            'action': 'setStreams',
            'data': params
        })
    else:
        LOG.error('Unknown request path: %s', request_path)
