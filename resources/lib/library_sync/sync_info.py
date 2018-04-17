# -*- coding: utf-8 -*-
from logging import getLogger
from threading import Thread, Lock

from xbmc import sleep
from xbmcgui import DialogProgressBG

from utils import thread_methods, language as lang

###############################################################################

LOG = getLogger("PLEX." + __name__)

GET_METADATA_COUNT = 0
PROCESS_METADATA_COUNT = 0
PROCESSING_VIEW_NAME = ''
LOCK = Lock()

###############################################################################


@thread_methods(add_stops=['SUSPEND_LIBRARY_THREAD',
                           'STOP_SYNC',
                           'SUSPEND_SYNC'])
class ThreadedShowSyncInfo(Thread):
    """
    Threaded class to show the Kodi statusbar of the metadata download.

    Input:
        total:       Total number of items to get
        item_type:
    """
    def __init__(self, total, item_type):
        self.total = total
        self.item_type = item_type
        Thread.__init__(self)

    def run(self):
        """
        Do the work
        """
        LOG.debug('Show sync info thread started')
        # cache local variables because it's faster
        total = self.total
        dialog = DialogProgressBG('dialoglogProgressBG')
        dialog.create("%s %s: %s %s"
                      % (lang(39714), self.item_type, str(total), lang(39715)))

        total = 2 * total
        total_progress = 0
        while not self.stopped():
            with LOCK:
                get_progress = GET_METADATA_COUNT
                process_progress = PROCESS_METADATA_COUNT
                view_name = PROCESSING_VIEW_NAME
            total_progress = get_progress + process_progress
            try:
                percentage = int(float(total_progress) / float(total)*100.0)
            except ZeroDivisionError:
                percentage = 0
            dialog.update(percentage,
                          message="%s %s. %s %s: %s"
                                  % (get_progress,
                                     lang(39712),
                                     process_progress,
                                     lang(39713),
                                     view_name))
            # Sleep for x milliseconds
            sleep(200)
        dialog.close()
        LOG.debug('Show sync info thread terminated')
