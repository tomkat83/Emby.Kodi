# -*- coding: utf-8 -*-
from logging import getLogger
from threading import Thread
from Queue import Empty

from xbmc import sleep

from utils import thread_methods, settings, language as lang, dialog
import plexdb_functions as plexdb
import itemtypes
from artwork import ArtworkSyncMessage
import variables as v
import state

###############################################################################

LOG = getLogger("PLEX." + __name__)

###############################################################################


@thread_methods(add_suspends=['SUSPEND_LIBRARY_THREAD',
                              'DB_SCAN',
                              'STOP_SYNC',
                              'SUSPEND_SYNC'])
class ThreadedProcessFanart(Thread):
    """
    Threaded download of additional fanart in the background

    Input:
        queue           Queue.Queue() object that you will need to fill with
                        dicts of the following form:
            {
              'plex_id':                the Plex id as a string
              'plex_type':              the Plex media type, e.g. 'movie'
              'refresh': True/False     if True, will overwrite any 3rd party
                                        fanart. If False, will only get missing
            }
    """
    def __init__(self, queue):
        self.queue = queue
        Thread.__init__(self)

    def run(self):
        """
        Do the work
        """
        LOG.debug("---===### Starting FanartSync ###===---")
        stopped = self.stopped
        suspended = self.suspended
        queue = self.queue
        while not stopped():
            # In the event the server goes offline
            while suspended():
                # Set in service.py
                if stopped():
                    # Abort was requested while waiting. We should exit
                    LOG.info("---===### Stopped FanartSync ###===---")
                    return
                sleep(1000)
            # grabs Plex item from queue
            try:
                item = queue.get(block=False)
            except Empty:
                sleep(200)
                continue

            if isinstance(item, ArtworkSyncMessage):
                if item.artwork_counter is not None:
                    if item.artwork_counter == 0:
                        # Done caching, show this in the PKC settings, too
                        settings('fanarttv_lookups', value=lang(30069))
                        LOG.info('Done caching major images!')
                    else:
                        settings('fanarttv_lookups',
                                 value=str(item.artwork_counter))
                if item.message and state.IMAGE_SYNC_NOTIFICATIONS:
                    dialog('notification',
                           heading=lang(29999),
                           message=item.message,
                           icon='{plex}',
                           sound=False)
                queue.task_done()
                continue

            LOG.debug('Get additional fanart for Plex id %s', item['plex_id'])
            with getattr(itemtypes,
                         v.ITEMTYPE_FROM_PLEXTYPE[item['plex_type']])() as item_type:
                result = item_type.getfanart(item['plex_id'],
                                             refresh=item['refresh'])
            if result is True:
                LOG.debug('Done getting fanart for Plex id %s', item['plex_id'])
                with plexdb.Get_Plex_DB() as plex_db:
                    plex_db.set_fanart_synched(item['plex_id'])
            queue.task_done()
        LOG.debug("---===### Stopped FanartSync ###===---")
