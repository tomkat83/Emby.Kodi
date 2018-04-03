# -*- coding: utf-8 -*-
from logging import getLogger
from threading import Thread, Lock

from xbmc import sleep, Player
from xbmcgui import DialogProgressBG

from utils import thread_methods, language as lang

###############################################################################

log = getLogger("PLEX."+__name__)

GET_METADATA_COUNT = 0
PROCESS_METADATA_COUNT = 0
PROCESSING_VIEW_NAME = ''
LOCK = Lock()

###############################################################################


@thread_methods(add_stops=['SUSPEND_LIBRARY_THREAD', 'STOP_SYNC'])
class Threaded_Show_Sync_Info(Thread):
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
        Catch all exceptions and log them
        """
        try:
            self.__run()
        except Exception as e:
            log.error('Exception %s' % e)
            import traceback
            log.error("Traceback:\n%s" % traceback.format_exc())

    def __run(self):
        """
        Do the work
        """
        log.debug('Show sync info thread started')
        # cache local variables because it's faster
        total = self.total
        dialog = DialogProgressBG('dialoglogProgressBG')
        dialog.create("%s %s: %s %s"
                      % (lang(39714), self.item_type, str(total), lang(39715)))
        player = Player()

        total = 2 * total
        totalProgress = 0
        while self.stopped() is False and not player.isPlaying():
            with LOCK:
                get_progress = GET_METADATA_COUNT
                process_progress = PROCESS_METADATA_COUNT
                viewName = PROCESSING_VIEW_NAME
            totalProgress = get_progress + process_progress
            try:
                percentage = int(float(totalProgress) / float(total)*100.0)
            except ZeroDivisionError:
                percentage = 0
            dialog.update(percentage,
                          message="%s %s. %s %s: %s"
                                  % (get_progress,
                                     lang(39712),
                                     process_progress,
                                     lang(39713),
                                     viewName))
            # Sleep for x milliseconds
            sleep(200)
        dialog.close()
        log.debug('Show sync info thread terminated')
