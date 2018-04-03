# -*- coding: utf-8 -*-
from logging import getLogger
from threading import Thread
from Queue import Empty

from xbmc import sleep

from utils import thread_methods
import itemtypes
import sync_info

###############################################################################
log = getLogger("PLEX."+__name__)

###############################################################################


@thread_methods(add_stops=['SUSPEND_LIBRARY_THREAD', 'STOP_SYNC'])
class Threaded_Process_Metadata(Thread):
    """
    Not yet implemented for more than 1 thread - if ever. Only to be called by
    ONE thread!
    Processes the XML metadata in the queue

    Input:
        queue:      Queue.Queue() object that you'll need to fill up with
                    the downloaded XML eTree objects
        item_type:  as used to call functions in itemtypes.py e.g. 'Movies' =>
                    itemtypes.Movies()
    """
    def __init__(self, queue, item_type):
        self.queue = queue
        self.item_type = item_type
        Thread.__init__(self)

    def terminate_now(self):
        """
        Needed to terminate this thread, because there might be items left in
        the queue which could cause other threads to hang
        """
        while not self.queue.empty():
            # Still try because remaining item might have been taken
            try:
                self.queue.get(block=False)
            except Empty:
                sleep(10)
                continue
            else:
                self.queue.task_done()

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
        log.debug('Processing thread started')
        # Constructs the method name, e.g. itemtypes.Movies
        item_fct = getattr(itemtypes, self.item_type)
        # cache local variables because it's faster
        queue = self.queue
        stopped = self.stopped
        with item_fct() as item_class:
            while stopped() is False:
                # grabs item from queue
                try:
                    item = queue.get(block=False)
                except Empty:
                    sleep(20)
                    continue
                # Do the work
                item_method = getattr(item_class, item['method'])
                if item.get('children') is not None:
                    item_method(item['XML'][0],
                                viewtag=item['viewName'],
                                viewid=item['viewId'],
                                children=item['children'])
                else:
                    item_method(item['XML'][0],
                                viewtag=item['viewName'],
                                viewid=item['viewId'])
                # Keep track of where we are at
                try:
                    log.debug('found child: %s'
                              % item['children'].attrib)
                except:
                    pass
                with sync_info.LOCK:
                    sync_info.PROCESS_METADATA_COUNT += 1
                    sync_info.PROCESSING_VIEW_NAME = item['title']
                queue.task_done()
        self.terminate_now()
        log.debug('Processing thread terminated')
