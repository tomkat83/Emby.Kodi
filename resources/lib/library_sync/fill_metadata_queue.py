# -*- coding: utf-8 -*-
from logging import getLogger
from queue import Full

from . import common, sections
from ..plex_db import PlexDB
from .. import backgroundthread

LOG = getLogger('PLEX.sync.fill_metadata_queue')

QUEUE_TIMEOUT = 60  # seconds


class FillMetadataQueue(common.LibrarySyncMixin,
                        backgroundthread.KillableThread):
    """
    Determines which plex_ids we need to sync and puts these ids in a separate
    queue. Will use a COPIED plex.db file (plex-copy.db) in order to read much
    faster without the writing thread stalling
    """
    def __init__(self, repair, section_queue, get_metadata_queue,
                 processing_queue):
        self.repair = repair
        self.section_queue = section_queue
        self.get_metadata_queue = get_metadata_queue
        self.processing_queue = processing_queue
        super(FillMetadataQueue, self).__init__()

    def _process_section(self, section):
        # Initialize only once to avoid loosing the last value before we're
        # breaking the for loop
        LOG.debug('Process section %s with %s items',
                  section, section.number_of_items)
        count = 0
        do_process_section = False
        with PlexDB(lock=False, copy=True) as plexdb:
            for xml in section.iterator:
                if self.should_cancel():
                    break
                plex_id = int(xml.get('ratingKey'))
                checksum = int('{}{}'.format(
                    plex_id,
                    abs(int(xml.get('updatedAt',
                            xml.get('addedAt', '1541572987'))))))
                if (not self.repair and
                        plexdb.checksum(plex_id, section.plex_type) == checksum):
                    continue
                if not do_process_section:
                    do_process_section = True
                    self.processing_queue.add_section(section)
                    LOG.debug('Put section in processing queue: %s', section)
                try:
                    self.get_metadata_queue.put((count, plex_id, section),
                                                timeout=QUEUE_TIMEOUT)
                except Full:
                    LOG.error('Putting %s in get_metadata_queue timed out - '
                              'aborting sync now', plex_id)
                    section.sync_successful = False
                    break
                else:
                    count += 1
        # We might have received LESS items from the PMS than anticipated.
        # Ensures that our queues finish
        self.processing_queue.change_section_number_of_items(section,
                                                             count)
        LOG.debug('%s items to process for section %s',
                  section.number_of_items, section)

    def _run(self):
        while not self.should_cancel():
            section = self.section_queue.get()
            self.section_queue.task_done()
            if section is None:
                break
            self._process_section(section)
        # Signal the download metadata threads to stop with a sentinel
        self.get_metadata_queue.put(None)
        # Sentinel for the process_thread once we added everything else
        self.processing_queue.add_sentinel(sections.Section())
