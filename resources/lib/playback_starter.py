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


class Playback_Starter(Thread):
    """
    Processes new plays
    """
    def triage(self, item):
        try:
            _, params = item.split('?', 1)
        except ValueError:
            # e.g. when plugin://...tvshows is called for entire season
            with kodidb.GetKodiDB('video') as kodi_db:
                show_id = kodi_db.show_id_from_path(item)
            if show_id:
                js.activate_window('videos',
                                   'videodb://tvshows/titles/%s' % show_id)
            else:
                LOG.error('Could not find tv show id for %s', item)
            pickle_me(Playback_Successful())
            return
        params = dict(parse_qsl(params))
        mode = params.get('mode')
        LOG.debug('Received mode: %s, params: %s', mode, params)
        if mode == 'play':
            playback.playback_triage(plex_id=params.get('plex_id'),
                                     plex_type=params.get('plex_type'),
                                     path=params.get('path'))
        elif mode == 'plex_node':
            playback.process_indirect(params['key'], params['offset'])
        elif mode == 'context_menu':
            ContextMenu(kodi_id=params['kodi_id'],
                        kodi_type=params['kodi_type'])

    def run(self):
        queue = state.COMMAND_PIPELINE_QUEUE
        LOG.info("----===## Starting Playback_Starter ##===----")
        while True:
            item = queue.get()
            if item is None:
                # Need to shutdown - initiated by command_pipeline
                break
            else:
                self.triage(item)
                queue.task_done()
        LOG.info("----===## Playback_Starter stopped ##===----")
