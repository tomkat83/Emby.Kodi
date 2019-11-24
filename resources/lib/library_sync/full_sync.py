#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import Queue

import xbmcgui

from .get_metadata import GetMetadataThread
from . import common, sections
from .. import utils, timing, backgroundthread, variables as v, app
from .. import plex_functions as PF, itemtypes
from ..plex_db import PlexDB

if common.PLAYLIST_SYNC_ENABLED:
    from .. import playlists


LOG = getLogger('PLEX.sync.full_sync')
# How many items will be put through the processing chain at once?
BATCH_SIZE = 250
# Size of queue for xmls to be downloaded from PMS for/and before processing
QUEUE_BUFFER = 50
# Safety margin to filter PMS items - how many seconds to look into the past?
UPDATED_AT_SAFETY = 60 * 5
LAST_VIEWED_AT_SAFETY = 60 * 5


class FullSync(common.fullsync_mixin):
    def __init__(self, repair, callback, show_dialog):
        """
        repair=True: force sync EVERY item
        """
        self.repair = repair
        self.callback = callback
        # For progress dialog
        self.show_dialog = show_dialog
        self.show_dialog_userdata = utils.settings('playstate_sync_indicator') == 'true'
        if self.show_dialog:
            self.dialog = xbmcgui.DialogProgressBG()
            self.dialog.create(utils.lang(39714))
        else:
            self.dialog = None

        self.section_queue = Queue.Queue()
        self.get_metadata_queue = Queue.Queue()
        self.metadata_queue_exhausted = False
        self.processing_queue = backgroundthread.ProcessingQueue()
        self.current_time = timing.plex_now()
        self.last_section = sections.Section()

        self.successful = True
        self.install_sync_done = utils.settings('SyncInstallRunDone') == 'true'
        self.threads = [
            GetMetadataThread(self.get_metadata_queue, self.processing_queue)
            for _ in range(int(utils.settings('syncThreadNumber')))
        ]
        for t in self.threads:
            t.start()
        super(FullSync, self).__init__()

    def update_progressbar(self, section, title, current):
        if not self.dialog:
            return
        current += 1
        try:
            progress = int(float(current) / float(section.number_of_items) * 100.0)
        except ZeroDivisionError:
            progress = 0
        self.dialog.update(progress,
                           '%s (%s)' % (section.name, section.section_type_text),
                           '%s %s/%s'
                           % (title, current, section.number_of_items))
        if app.APP.is_playing_video:
            self.dialog.close()
            self.dialog = None

    def fill_metadata_queue(self, plexdb, xml_item, section, count):
        """
        Throw a single item into a queue to download its metadata from the pms
        """
        plex_id = int(xml_item.get('ratingKey'))
        if not self.repair and plexdb.checksum(plex_id, section.plex_type) == \
                int('%s%s' % (plex_id,
                              xml_item.get('updatedAt',
                                           xml_item.get('addedAt', 1541572987)))):
            return
        self.get_metadata_queue.put((count, plex_id, section))

    def process_metadata(self, finish=False):
        LOG.debug('Processing metadata and writing to databases')
        try:
            # Do NOT block since we can't know whether we received all items
            # to finish a specific section - block could thus be indefinite
            item = self.processing_queue.get(block=False)
        except Queue.Empty:
            LOG.debug('Did not yet receive an item')
            return
        self.processing_queue.task_done()
        if item:
            section = item['section']
            processed = 0
            self.start_section(section)
        while not self.isCanceled():
            if item is None:
                break
            elif item['section'] != section:
                # We received an entirely new section
                self.start_section(item['section'])
                section = item['section']
            with section.context(self.current_time) as context:
                while not self.isCanceled():
                    if item is None or item['section'] != section:
                        break
                    self.update_progressbar(section,
                                            item['xml'][0].get('title'),
                                            section.count)
                    context.add_update(item['xml'][0],
                                       section_name=section.name,
                                       section_id=section.section_id,
                                       children=item['children'])
                    processed += 1
                    section.count += 1
                    if processed == BATCH_SIZE:
                        # For at most every x items, safe to databases
                        processed = 0
                        context.commit()
                    if not finish and self.get_metadata_queue.qsize() < QUEUE_BUFFER:
                        LOG.debug('Pause processing metadata to fill queue')
                        return
                    try:
                        item = self.processing_queue.get(block=False)
                    except Queue.Empty:
                        LOG.debug('Did not receive an item from our queue')
                        return
                    self.processing_queue.task_done()
        LOG.debug('Done writing changes to Kodi library')

    def start_section(self, section):
        if section != self.last_section:
            if self.last_section:
                self.finish_last_section()
            LOG.debug('Start or continue processing section %s', section)
            self.last_section = section
            # Warn the user for this new section if we cannot access a file
            app.SYNC.path_verified = False
        else:
            LOG.debug('Resume processing section %s', section)

    def finish_last_section(self):
        if (not self.isCanceled() and self.last_section and
                self.last_section.sync_successful):
            # Check for isCanceled() because we cannot be sure that we
            # processed every item of the section
            with PlexDB() as plexdb:
                # Set the new time mark for the next delta sync
                plexdb.update_section_last_sync(self.last_section.section_id,
                                                self.current_time)
            LOG.info('Finished processing section successfully: %s',
                     self.last_section)
        elif self.last_section and not self.last_section.sync_successful:
            LOG.warn('Sync not successful for section %s', self.last_section)
            self.successful = False

    @utils.log_time
    def processing_loop_new_and_changed_items(self):
        LOG.debug('Entering processing_loop_new_and_changed_items')
        while not self.isCanceled():
            section = self.section_queue.get()
            self.section_queue.task_done()
            if section is None:
                break
            # Initialize only once to avoid loosing the last value before
            # we're breaking the for loop
            loop = common.tag_last(section.iterator)
            last = True
            count = 0
            while not self.isCanceled():
                with PlexDB() as plexdb:
                    LOG.debug('Processing batch with count %s for section %s',
                              count, section)
                    for last, xml_item in loop:
                        if self.isCanceled():
                            return False
                        self.fill_metadata_queue(plexdb,
                                                 xml_item,
                                                 section,
                                                 count)
                        count += 1
                        if count % BATCH_SIZE == 0:
                            break
                if self.processing_queue.total_size() >= BATCH_SIZE:
                    self.process_metadata(finish=False)
                if last:
                    # We might have received LESS items from the PMS than
                    # anticipated. Ensures that our queues finish
                    section.number_of_items = count
                    break
        # Signal the download threads to stop
        self.get_metadata_queue.put(None)
        while not self.isCanceled() and self.processing_queue.total_size():
            LOG.debug('Finishing up processing of metadata')
            self.process_metadata(finish=True)
        self.finish_last_section()
        LOG.debug('Finished processing_loop_new_and_changed_items')

    @utils.log_time
    def processing_loop_playstates(self):
        while not self.isCanceled():
            section = self.section_queue.get()
            self.section_queue.task_done()
            if section is None:
                break
            self.playstate_per_section(section)

    def playstate_per_section(self, section):
        LOG.debug('Processing %s playstates for library section %s',
                  section.number_of_items, section)
        try:
            iterator = section.iterator
            iterator = common.tag_last(iterator)
            last = True
            while not self.isCanceled():
                with section.context(self.current_time) as itemtype:
                    for last, xml_item in iterator:
                        section.count += 1
                        if not itemtype.update_userdata(xml_item, section.plex_type):
                            # Somehow did not sync this item yet
                            itemtype.add_update(xml_item,
                                                section_name=section.name,
                                                section_id=section.section_id)
                        itemtype.plexdb.update_last_sync(int(xml_item.attrib['ratingKey']),
                                                         section.plex_type,
                                                         self.current_time)
                        self.update_progressbar(section, '', section.count)
                        if section.count % (10 * BATCH_SIZE) == 0:
                            break
                if last:
                    break
        except RuntimeError:
            LOG.error('Could not entirely process section %s', section)
            self.successful = False

    def threaded_get_iterators(self, kinds, queue, all_items):
        """
        Getting iterators is costly, so let's do it asynchronously
        """
        LOG.debug('Start threaded_get_iterators')
        try:
            for kind in kinds:
                for section in (x for x in app.SYNC.sections
                                if x.section_type == kind[1]):
                    if self.isCanceled():
                        LOG.debug('Need to exit now')
                        return
                    if not section.sync_to_kodi:
                        LOG.info('User chose to not sync section %s', section)
                        continue
                    section = sections.get_sync_section(section,
                                                        plex_type=kind[0])
                    if self.repair or all_items:
                        updated_at = None
                    else:
                        updated_at = section.last_sync - UPDATED_AT_SAFETY \
                            if section.last_sync else None
                    try:
                        section.iterator = PF.get_section_iterator(
                            section.section_id,
                            plex_type=section.plex_type,
                            updated_at=updated_at,
                            last_viewed_at=None)
                    except RuntimeError:
                        LOG.error('Sync at least partially unsuccessful!')
                        LOG.error('Error getting section iterator %s', section)
                    else:
                        section.number_of_items = section.iterator.total
                        if section.number_of_items > 0:
                            self.processing_queue.add_section(section)
                            queue.put(section)
                            LOG.debug('Put section in queue: %s', section)
        except Exception:
            utils.ERROR(notify=True)
        finally:
            queue.put(None)
            LOG.debug('Exiting threaded_get_iterators')

    def full_library_sync(self):
        kinds = [
            (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_MOVIE),
            (v.PLEX_TYPE_SHOW, v.PLEX_TYPE_SHOW),
            (v.PLEX_TYPE_SEASON, v.PLEX_TYPE_SHOW),
            (v.PLEX_TYPE_EPISODE, v.PLEX_TYPE_SHOW)
        ]
        if app.SYNC.enable_music:
            kinds.extend([
                (v.PLEX_TYPE_ARTIST, v.PLEX_TYPE_ARTIST),
                (v.PLEX_TYPE_ALBUM, v.PLEX_TYPE_ARTIST),
            ])
        # ADD NEW ITEMS
        # Already start setting up the iterators. We need to enforce
        # syncing e.g. show before season before episode
        backgroundthread.KillableThread(
            target=self.threaded_get_iterators,
            args=(kinds, self.section_queue, False)).start()
        # Do the heavy lifting
        self.processing_loop_new_and_changed_items()
        common.update_kodi_library(video=True, music=True)
        if self.isCanceled() or not self.successful:
            return

        # Sync Plex playlists to Kodi and vice-versa
        if common.PLAYLIST_SYNC_ENABLED:
            if self.show_dialog:
                if self.dialog:
                    self.dialog.close()
                self.dialog = xbmcgui.DialogProgressBG()
                # "Synching playlists"
                self.dialog.create(utils.lang(39715))
            if not playlists.full_sync() or self.isCanceled():
                return

        # SYNC PLAYSTATE of ALL items (otherwise we won't pick up on items that
        # were set to unwatched). Also mark all items on the PMS to be able
        # to delete the ones still in Kodi
        LOG.debug('Start synching playstate and userdata for every item')
        if app.SYNC.enable_music:
            # In order to not delete all your songs again
            kinds.extend([
                (v.PLEX_TYPE_SONG, v.PLEX_TYPE_ARTIST),
            ])
        # Make sure we're not showing an item's title in the sync dialog
        if not self.show_dialog_userdata and self.dialog:
            # Close the progress indicator dialog
            self.dialog.close()
            self.dialog = None
        backgroundthread.KillableThread(
            target=self.threaded_get_iterators,
            args=(kinds, self.section_queue, True)).start()
        self.processing_loop_playstates()
        if self.isCanceled() or not self.successful:
            return

        # Delete movies that are not on Plex anymore
        LOG.debug('Looking for items to delete')
        kinds = [
            (v.PLEX_TYPE_MOVIE, itemtypes.Movie),
            (v.PLEX_TYPE_SHOW, itemtypes.Show),
            (v.PLEX_TYPE_SEASON, itemtypes.Season),
            (v.PLEX_TYPE_EPISODE, itemtypes.Episode)
        ]
        if app.SYNC.enable_music:
            kinds.extend([
                (v.PLEX_TYPE_ARTIST, itemtypes.Artist),
                (v.PLEX_TYPE_ALBUM, itemtypes.Album),
                (v.PLEX_TYPE_SONG, itemtypes.Song)
            ])
        for plex_type, context in kinds:
            # Delete movies that are not on Plex anymore
            while True:
                with context(self.current_time) as ctx:
                    plex_ids = list(
                        ctx.plexdb.plex_id_by_last_sync(plex_type,
                                                        self.current_time,
                                                        BATCH_SIZE))
                    for plex_id in plex_ids:
                        if self.isCanceled():
                            return
                        ctx.remove(plex_id, plex_type)
                if len(plex_ids) < BATCH_SIZE:
                    break
        LOG.debug('Done looking for items to delete')

    def run(self):
        app.APP.register_thread(self)
        LOG.info('Running library sync with repair=%s', self.repair)
        try:
            self.run_full_library_sync()
        finally:
            app.APP.deregister_thread(self)
            LOG.info('Library sync done. successful: %s', self.successful)

    @utils.log_time
    def run_full_library_sync(self):
        try:
            # Get latest Plex libraries and build playlist and video node files
            if self.isCanceled() or not sections.sync_from_pms(self):
                return
            if self.isCanceled():
                self.successful = False
                return
            self.full_library_sync()
        finally:
            common.update_kodi_library(video=True, music=True)
            if self.dialog:
                self.dialog.close()
            if not self.successful and not self.isCanceled():
                # "ERROR in library sync"
                utils.dialog('notification',
                             heading='{plex}',
                             message=utils.lang(39410),
                             icon='{error}')
            self.callback(self.successful)


def start(show_dialog, repair=False, callback=None):
    FullSync(repair, callback, show_dialog).run()
