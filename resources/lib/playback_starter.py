#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
from urlparse import parse_qsl

from . import playback
from . import context_entry
from . import json_rpc as js
from . import pickler
from . import kodidb_functions as kodidb
from . import state

###############################################################################

LOG = getLogger('PLEX.playback_starter')

###############################################################################


class PlaybackStarter(Thread):
    """
    Processes new plays
    """
    @staticmethod
    def _triage(item):
        try:
            _, params = item.split('?', 1)
        except ValueError:
            # E.g. other add-ons scanning for Extras folder
            LOG.debug('Detected 3rd party add-on call - ignoring')
            pickler.pickle_me(pickler.Playback_Successful())
            return
        params = dict(parse_qsl(params))
        mode = params.get('mode')
        resolve = False if params.get('handle') == '-1' else True
        LOG.debug('Received mode: %s, params: %s', mode, params)
        if mode == 'play':
            playback.playback_triage(plex_id=params.get('plex_id'),
                                     plex_type=params.get('plex_type'),
                                     path=params.get('path'),
                                     resolve=resolve)
        elif mode == 'plex_node':
            playback.process_indirect(params['key'],
                                      params['offset'],
                                      resolve=resolve)
        elif mode == 'navigation':
            # e.g. when plugin://...tvshows is called for entire season
            with kodidb.GetKodiDB('video') as kodi_db:
                show_id = kodi_db.show_id_from_path(params.get('path'))
            if show_id:
                js.activate_window('videos',
                                   'videodb://tvshows/titles/%s' % show_id)
            else:
                LOG.error('Could not find tv show id for %s', item)
            if resolve:
                pickler.pickle_me(pickler.Playback_Successful())
        elif mode == 'context_menu':
            context_entry.ContextMenu(kodi_id=params.get('kodi_id'),
                                      kodi_type=params.get('kodi_type'))

    def run(self):
        queue = state.COMMAND_PIPELINE_QUEUE
        LOG.info("----===## Starting PlaybackStarter ##===----")
        while True:
            item = queue.get()
            if item is None:
                # Need to shutdown - initiated by command_pipeline
                break
            else:
                self._triage(item)
                queue.task_done()
        LOG.info("----===## PlaybackStarter stopped ##===----")
