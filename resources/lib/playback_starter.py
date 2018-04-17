# -*- coding: utf-8 -*-
###############################################################################
from logging import getLogger
from threading import Thread
from urlparse import parse_qsl

import playback
from context_entry import ContextMenu
import state
import json_rpc as js
from pickler import pickle_me, Playback_Successful
import kodidb_functions as kodidb

###############################################################################

LOG = getLogger("PLEX." + __name__)

###############################################################################


class PlaybackStarter(Thread):
    """
    Processes new plays
    """
    @staticmethod
    def _triage(item):
        _, params = item.split('?', 1)
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
                pickle_me(Playback_Successful())
        elif mode == 'context_menu':
            ContextMenu(kodi_id=params.get('kodi_id'),
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
