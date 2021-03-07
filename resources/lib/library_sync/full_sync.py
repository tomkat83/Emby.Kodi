#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import queue

import xbmcgui

from .get_metadata import GetMetadataThread
from .fill_metadata_queue import FillMetadataQueue
from .process_metadata import ProcessMetadataThread
from . import common, sections
from .. import utils, timing, backgroundthread as bg, variables as v, app
from .. import plex_functions as PF, itemtypes, path_ops

if common.PLAYLIST_SYNC_ENABLED:
    from .. import playlists


LOG = getLogger('PLEX.sync.full_sync')
DELETION_BATCH_SIZE = 250
PLAYSTATE_BATCH_SIZE = 5000

# Max. number of plex_ids held in memory for later processing
BACKLOG_QUEUE_SIZE = 10000
# Max number of xmls held in memory
XML_QUEUE_SIZE = 500
# Safety margin to filter PMS items - how many seconds to look into the past?
UPDATED_AT_SAFETY = 60 * 5
LAST_VIEWED_AT_SAFETY = 60 * 5


class FullSync(common.LibrarySyncMixin, bg.KillableThread):
    def __init__(self, repair, callback, show_dialog):
        """
        repair=True: force sync EVERY item
        """
        self.successful = True
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
        self.current_time = timing.plex_now()
        self.last_section = sections.Section()
        self.install_sync_done = utils.settings('SyncInstallRunDone') == 'true'
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

    @staticmethod
    def copy_plex_db():
        """
        Takes the current plex.db file and copies it to plex-copy.db
        This will allow us to have "concurrent" connections during adding/
        updating items, increasing sync speed tremendously.
        Using the same DB with e.g. WAL mode did not really work out...
        """
        path_ops.copyfile(v.DB_PLEX_PATH, v.DB_PLEX_COPY_PATH)

    @utils.log_time
    def process_new_and_changed_items(self, section_queue, processing_queue):
        LOG.debug('Start working')
        get_metadata_queue = queue.Queue(maxsize=BACKLOG_QUEUE_SIZE)
        scanner_thread = FillMetadataQueue(self.repair,
                                           section_queue,
                                           get_metadata_queue,
                                           processing_queue)
        scanner_thread.start()
        metadata_threads = [
            GetMetadataThread(get_metadata_queue, processing_queue)
            for _ in range(int(utils.settings('syncThreadNumber')))
        ]
        for t in metadata_threads:
            t.start()
        process_thread = ProcessMetadataThread(self.current_time,
                                               processing_queue,
                                               self.update_progressbar)
        process_thread.start()
        LOG.debug('Waiting for scanner thread to finish up')
        scanner_thread.join()
        LOG.debug('Waiting for metadata download threads to finish up')
        for t in metadata_threads:
            t.join()
        LOG.debug('Download metadata threads finished')
        process_thread.join()
        self.successful = process_thread.successful
        LOG.debug('threads finished work. successful: %s', self.successful)

    @utils.log_time
    def processing_loop_playstates(self, section_queue):
        while not self.should_cancel():
            section = section_queue.get()
            section_queue.task_done()
            if section is None:
                break
            self.playstate_per_section(section)

    def playstate_per_section(self, section):
        LOG.debug('Processing %s playstates for library section %s',
                  section.number_of_items, section)
        try:
            with section.context(self.current_time) as context:
                for xml in section.iterator:
                    section.count += 1
                    if not context.update_userdata(xml, section.plex_type):
                        # Somehow did not sync this item yet
                        context.add_update(xml,
                                           section_name=section.name,
                                           section_id=section.section_id)
                    context.plexdb.update_last_sync(int(xml.attrib['ratingKey']),
                                                    section.plex_type,
                                                    self.current_time)
                    self.update_progressbar(section, '', section.count - 1)
                    if section.count % PLAYSTATE_BATCH_SIZE == 0:
                        context.commit()
        except RuntimeError:
            LOG.error('Could not entirely process section %s', section)
            self.successful = False

    def threaded_get_generators(self, kinds, section_queue, items):
        """
        Getting iterators is costly, so let's do it in a dedicated thread
        """
        LOG.debug('Start threaded_get_generators')
        try:
            for kind in kinds:
                for section in (x for x in app.SYNC.sections
                                if x.section_type == kind[1]):
                    if self.should_cancel():
                        LOG.debug('Need to exit now')
                        return
                    if not section.sync_to_kodi:
                        LOG.info('User chose to not sync section %s', section)
                        continue
                    section = sections.get_sync_section(section,
                                                        plex_type=kind[0])
                    timestamp = section.last_sync - UPDATED_AT_SAFETY \
                        if section.last_sync else None
                    if items == 'all':
                        updated_at = None
                        last_viewed_at = None
                    elif items == 'watched':
                        if not timestamp:
                            # No need to sync playstate updates since section
                            # has not yet been synched
                            continue
                        else:
                            updated_at = None
                            last_viewed_at = timestamp
                    elif items == 'updated':
                        updated_at = timestamp
                        last_viewed_at = None
                    try:
                        section.iterator = PF.get_section_iterator(
                            section.section_id,
                            plex_type=section.plex_type,
                            updated_at=updated_at,
                            last_viewed_at=last_viewed_at)
                    except RuntimeError:
                        LOG.error('Sync at least partially unsuccessful!')
                        LOG.error('Error getting section iterator %s', section)
                    else:
                        section.number_of_items = section.iterator.total
                        if section.number_of_items > 0:
                            section_queue.put(section)
                            LOG.debug('Put section in queue with %s items: %s',
                                      section.number_of_items, section)
        except Exception:
            utils.ERROR(notify=True)
        finally:
            # Sentinel for the section queue
            section_queue.put(None)
            LOG.debug('Exiting threaded_get_generators')

    def full_library_sync(self):
        section_queue = queue.Queue()
        processing_queue = bg.ProcessingQueue(maxsize=XML_QUEUE_SIZE)
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
        # We need to enforce syncing e.g. show before season before episode
        bg.FunctionAsTask(self.threaded_get_generators,
                          None,
                          kinds,
                          section_queue,
                          items='all' if self.repair else 'updated').start()
        # Do the heavy lifting
        self.process_new_and_changed_items(section_queue, processing_queue)
        common.update_kodi_library(video=True, music=True)
        if self.should_cancel() or not self.successful:
            return

        # In order to not delete all your songs again for playstate synch
        if app.SYNC.enable_music:
            kinds.extend([
                (v.PLEX_TYPE_SONG, v.PLEX_TYPE_ARTIST),
            ])

        # Update playstate progress since last sync - especially useful for
        # users of very large libraries since this step is very fast
        # These playstates will be synched twice
        LOG.debug('Start synching playstate for last watched items')
        bg.FunctionAsTask(self.threaded_get_generators,
                          None,
                          kinds,
                          section_queue,
                          items='watched').start()
        self.processing_loop_playstates(section_queue)
        if self.should_cancel() or not self.successful:
            return

        # Sync Plex playlists to Kodi and vice-versa
        if common.PLAYLIST_SYNC_ENABLED:
            LOG.debug('Start playlist sync')
            if self.show_dialog:
                if self.dialog:
                    self.dialog.close()
                self.dialog = xbmcgui.DialogProgressBG()
                # "Synching playlists"
                self.dialog.create(utils.lang(39715))
            if not playlists.full_sync() or self.should_cancel():
                return

        # SYNC PLAYSTATE of ALL items (otherwise we won't pick up on items that
        # were set to unwatched or changed user ratings). Also mark all items on
        # the PMS to be able to delete the ones still in Kodi
        LOG.debug('Start synching playstate and userdata for every item')
        # Make sure we're not showing an item's title in the sync dialog
        if not self.show_dialog_userdata and self.dialog:
            # Close the progress indicator dialog
            self.dialog.close()
            self.dialog = None
        bg.FunctionAsTask(self.threaded_get_generators,
                          None,
                          kinds,
                          section_queue,
                          items='all').start()
        self.processing_loop_playstates(section_queue)
        if self.should_cancel() or not self.successful:
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
                                                        DELETION_BATCH_SIZE))
                    for plex_id in plex_ids:
                        if self.should_cancel():
                            return
                        ctx.remove(plex_id, plex_type)
                if len(plex_ids) < DELETION_BATCH_SIZE:
                    break
        LOG.debug('Done looking for items to delete')

    @utils.log_time
    def _run(self):
        try:
            # Get latest Plex libraries and build playlist and video node files
            if self.should_cancel() or not sections.sync_from_pms(self):
                return
            self.copy_plex_db()
            self.full_library_sync()
        finally:
            common.update_kodi_library(video=True, music=True)
            if self.dialog:
                self.dialog.close()
            if not self.successful and not self.should_cancel():
                # "ERROR in library sync"
                utils.dialog('notification',
                             heading='{plex}',
                             message=utils.lang(39410),
                             icon='{error}')
            self.callback(self.successful)


def start(show_dialog, repair=False, callback=None):
    # Call run() and NOT start in order to not spawn another thread
    FullSync(repair, callback, show_dialog).run()
