# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
from Queue import Empty
from xbmc import sleep

from .. import utils
from .. import itemtypes
from . import sync_info

###############################################################################
LOG = getLogger("PLEX." + __name__)

###############################################################################


@utils.thread_methods(add_stops=['SUSPEND_LIBRARY_THREAD',
                                 'STOP_SYNC',
                                 'SUSPEND_SYNC'])
class ThreadedProcessMetadata(Thread):
    """
    Not yet implemented for more than 1 thread - if ever. Only to be called by
    ONE thread!
    Processes the XML metadata in the queue

    Input:
        queue:      Queue.Queue() object that you'll need to fill up with
                    the downloaded XML eTree objects
        item_class: as used to call functions in itemtypes.py e.g. 'Movies' =>
                    itemtypes.Movies()
    """
    def __init__(self, queue, item_class):
        self.queue = queue
        self.item_class = item_class
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
        Do the work
        """
        LOG.debug('Processing thread started')
        # Constructs the method name, e.g. itemtypes.Movies
        item_fct = getattr(itemtypes, self.item_class)
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
                    item_method(item['xml'][0],
                                viewtag=item['view_name'],
                                viewid=item['view_id'],
                                children=item['children'])
                else:
                    item_method(item['xml'][0],
                                viewtag=item['view_name'],
                                viewid=item['view_id'])
                # Keep track of where we are at
                with sync_info.LOCK:
                    sync_info.PROCESS_METADATA_COUNT += 1
                    sync_info.PROCESSING_VIEW_NAME = item['title']
                queue.task_done()
        self.terminate_now()
        LOG.debug('Processing thread terminated')
