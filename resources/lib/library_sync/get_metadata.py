# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
from Queue import Empty
from xbmc import sleep

from .. import utils
from .. import plex_functions as PF
from . import sync_info

###############################################################################

LOG = getLogger("PLEX." + __name__)

###############################################################################


@utils.thread_methods(add_stops=['SUSPEND_LIBRARY_THREAD',
                                 'STOP_SYNC',
                                 'SUSPEND_SYNC'])
class ThreadedGetMetadata(Thread):
    """
    Threaded download of Plex XML metadata for a certain library item.
    Fills the out_queue with the downloaded etree XML objects

    Input:
        queue               Queue.Queue() object that you'll need to fill up
                            with plex_ids
        out_queue           Queue() object where this thread will store
                            the downloaded metadata XMLs as etree objects
    """
    def __init__(self, queue, out_queue):
        self.queue = queue
        self.out_queue = out_queue
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
        if self.stopped():
            # Shutdown from outside requested; purge out_queue as well
            while not self.out_queue.empty():
                # Still try because remaining item might have been taken
                try:
                    self.out_queue.get(block=False)
                except Empty:
                    sleep(10)
                    continue
                else:
                    self.out_queue.task_done()

    def run(self):
        """
        Do the work
        """
        LOG.debug('Starting get metadata thread')
        # cache local variables because it's faster
        queue = self.queue
        out_queue = self.out_queue
        stopped = self.stopped
        while stopped() is False:
            # grabs Plex item from queue
            try:
                item = queue.get(block=False)
            # Empty queue
            except Empty:
                sleep(20)
                continue
            # Download Metadata
            xml = PF.GetPlexMetadata(item['plex_id'])
            if xml is None:
                # Did not receive a valid XML - skip that item for now
                LOG.error("Could not get metadata for %s. Skipping that item "
                          "for now", item['plex_id'])
                # Increase BOTH counters - since metadata won't be processed
                with sync_info.LOCK:
                    sync_info.GET_METADATA_COUNT += 1
                    sync_info.PROCESS_METADATA_COUNT += 1
                queue.task_done()
                continue
            elif xml == 401:
                LOG.error('HTTP 401 returned by PMS. Too much strain? '
                          'Cancelling sync for now')
                utils.window('plex_scancrashed', value='401')
                # Kill remaining items in queue (for main thread to cont.)
                queue.task_done()
                break

            item['xml'] = xml
            if item.get('get_children') is True:
                children_xml = PF.GetAllPlexChildren(item['plex_id'])
                try:
                    children_xml[0].attrib
                except (TypeError, IndexError, AttributeError):
                    LOG.error('Could not get children for Plex id %s',
                              item['plex_id'])
                    item['children'] = []
                else:
                    item['children'] = children_xml

            # place item into out queue
            out_queue.put(item)
            # Keep track of where we are at
            with sync_info.LOCK:
                sync_info.GET_METADATA_COUNT += 1
            # signals to queue job is done
            queue.task_done()
        # Empty queue in case PKC was shut down (main thread hangs otherwise)
        self.terminate_now()
        LOG.debug('Get metadata thread terminated')
