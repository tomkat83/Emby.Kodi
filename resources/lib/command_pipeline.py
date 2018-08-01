#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
import logging
from threading import Thread
from xbmc import sleep

from . import utils
from . import state

###############################################################################
LOG = logging.getLogger('PLEX.command_pipeline')
###############################################################################


@utils.thread_methods
class Monitor_Window(Thread):
    """
    Monitors window('plex_command') for new entries that we need to take care
    of, e.g. for new plays initiated on the Kodi side with addon paths.

    Adjusts state.py accordingly
    """
    def run(self):
        stopped = self.stopped
        queue = state.COMMAND_PIPELINE_QUEUE
        LOG.info("----===## Starting Kodi_Play_Client ##===----")
        while not stopped():
            if utils.window('plex_command'):
                value = utils.window('plex_command')
                utils.window('plex_command', clear=True)
                if value.startswith('PLAY-'):
                    queue.put(value.replace('PLAY-', ''))
                elif value == 'SUSPEND_LIBRARY_THREAD-True':
                    state.SUSPEND_LIBRARY_THREAD = True
                elif value == 'SUSPEND_LIBRARY_THREAD-False':
                    state.SUSPEND_LIBRARY_THREAD = False
                elif value == 'STOP_SYNC-True':
                    state.STOP_SYNC = True
                elif value == 'STOP_SYNC-False':
                    state.STOP_SYNC = False
                elif value == 'PMS_STATUS-Auth':
                    state.PMS_STATUS = 'Auth'
                elif value == 'PMS_STATUS-401':
                    state.PMS_STATUS = '401'
                elif value == 'SUSPEND_USER_CLIENT-True':
                    state.SUSPEND_USER_CLIENT = True
                elif value == 'SUSPEND_USER_CLIENT-False':
                    state.SUSPEND_USER_CLIENT = False
                elif value.startswith('PLEX_TOKEN-'):
                    state.PLEX_TOKEN = value.replace('PLEX_TOKEN-', '') or None
                elif value.startswith('PLEX_USERNAME-'):
                    state.PLEX_USERNAME = \
                        value.replace('PLEX_USERNAME-', '') or None
                elif value.startswith('RUN_LIB_SCAN-'):
                    state.RUN_LIB_SCAN = value.replace('RUN_LIB_SCAN-', '')
                elif value.startswith('CONTEXT_menu?'):
                    queue.put('dummy?mode=context_menu&%s'
                              % value.replace('CONTEXT_menu?', ''))
                elif value.startswith('NAVIGATE'):
                    queue.put(value.replace('NAVIGATE-', ''))
                else:
                    raise NotImplementedError('%s not implemented' % value)
            else:
                sleep(50)
        # Put one last item into the queue to let playback_starter end
        queue.put(None)
        LOG.info("----===## Kodi_Play_Client stopped ##===----")
