#!/usr/bin/env python
# -*- coding: utf-8 -*-

from logging import getLogger
import queue
import copy

import xbmcgui

from .get_metadata import GetMetadataTask, reset_collections
from . import common, sections
from .. import utils, timing, backgroundthread, variables as v, app
from .. import plex_functions as PF, itemtypes
from ..plex_db import PlexDB

if common.PLAYLIST_SYNC_ENABLED:
    from .. import playlists


LOG = getLogger('PLEX.sync.full_sync')
# How many items will be put through the processing chain at once?
BATCH_SIZE = 2000
# Safety margin to filter PMS items - how many seconds to look into the past?
UPDATED_AT_SAFETY = 60 * 5
LAST_VIEWED_AT_SAFETY = 60 * 5


class InitNewSection(object):
    """
    Throw this into the queue used for ProcessMetadata to tell it which
    Plex library section we're looking at
    """
    def __init__(self, context, total_number_of_items, section_name,
                 section_id, plex_type):
        self.context = context
        self.total = total_number_of_items
        self.name = section_name
        self.id = section_id
        self.plex_type = plex_type


class FullSync(common.fullsync_mixin):
    def __init__(self, repair, callback, show_dialog):
        """
        repair=True: force sync EVERY item
        """
        self.repair = repair
        self.callback = callback
        self.queue = None
        self.process_thread = None
        self.current_sync = None
        self.plexdb = None
        self.plex_type = None
        self.section_type = None
        self.worker_count = int(utils.settings('syncThreadNumber'))
        self.item_count = 0
        # For progress dialog
        self.show_dialog = show_dialog
        self.show_dialog_userdata = utils.settings('playstate_sync_indicator') == 'true'
        self.dialog = None
        self.total = 0
        self.current = 0
        self.processed = 0
        self.title = ''
        self.section = None
        self.section_name = None
        self.section_type_text = None
        self.context = None
        self.get_children = None
        self.successful = None
        self.section_success = None
        self.install_sync_done = utils.settings('SyncInstallRunDone') == 'true'
        self.threader = backgroundthread.ThreaderManager(
            worker=backgroundthread.NonstoppingBackgroundWorker,
            worker_count=self.worker_count)
        super(FullSync, self).__init__()

    def update_progressbar(self):
        if self.dialog:
            try:
                progress = int(float(self.current) / float(self.total) * 100.0)
            except ZeroDivisionError:
                progress = 0
            self.dialog.update(progress,
                               '%s (%s)' % (self.section_name, self.section_type_text),
                               '%s %s/%s'
                               % (self.title, self.current, self.total))
            if app.APP.is_playing_video:
                self.dialog.close()
                self.dialog = None

    def process_item(self, xml_item):
        """
        Processes a single library item
        """
        plex_id = int(xml_item.get('ratingKey'))
        if not self.repair and self.plexdb.checksum(plex_id, self.plex_type) == \
                int('%s%s' % (plex_id,
                              xml_item.get('updatedAt',
                                           xml_item.get('addedAt', 1541572987)))):
            return
        self.threader.addTask(GetMetadataTask(self.queue,
                                              plex_id,
                                              self.plex_type,
                                              self.get_children,
                                              self.item_count))
        self.item_count += 1

    def update_library(self):
        LOG.debug('Writing changes to Kodi library now')
        i = 0
        if not self.section:
            _, self.section = self.queue.get()
            self.queue.task_done()
        while not self.isCanceled() and self.item_count > 0:
            section = self.section
            if not section:
                break
            LOG.debug('Start or continue processing section %s (%ss)',
                      section.name, section.plex_type)
            self.processed = 0
            self.total = section.total
            self.section_name = section.name
            self.section_type_text = utils.lang(
                v.TRANSLATION_FROM_PLEXTYPE[section.plex_type])
            with section.context(self.current_sync) as context:
                while not self.isCanceled() and self.item_count > 0:
                    try:
                        _, item = self.queue.get(block=False)
                    except backgroundthread.Queue.Empty:
                        if self.threader.threader.working():
                            app.APP.monitor.waitForAbort(0.02)
                            continue
                        else:
                            # Try again, in case a thread just finished
                            i += 1
                            if i == 3:
                                break
                            continue
                    i = 0
                    self.queue.task_done()
                    if isinstance(item, dict):
                        context.add_update(item['xml'][0],
                                           section_name=section.name,
                                           section_id=section.id,
                                           children=item['children'])
                        self.title = item['xml'][0].get('title')
                        self.processed += 1
                    elif isinstance(item, InitNewSection) or item is None:
                        self.section = item
                        break
                    else:
                        raise ValueError('Unknown type %s' % type(item))
                    self.item_count -= 1
                    self.current += 1
                    self.update_progressbar()
                    if self.processed == 500:
                        self.processed = 0
                        context.commit()
        LOG.debug('Done writing changes to Kodi library')

    @utils.log_time
    def addupdate_section(self, section):
        LOG.debug('Processing library section for new or changed items %s',
                  section)
        if not self.install_sync_done:
            app.SYNC.path_verified = False
        try:
            # Sync new, updated and deleted items
            iterator = section.iterator
            # Tell the processing thread about this new section
            queue_info = InitNewSection(section.context,
                                        iterator.total,
                                        iterator.get('librarySectionTitle',
                                                     iterator.get('title1')),
                                        section.section_id,
                                        section.plex_type)
            self.queue.put((-1, queue_info))
            last = True
            # To keep track of the item-number in order to kill while loops
            self.item_count = 0
            self.current = 0
            # Initialize only once to avoid loosing the last value before
            # we're breaking the for loop
            loop = common.tag_last(iterator)
            while True:
                # Check Plex DB to see what we need to add/update
                with PlexDB() as self.plexdb:
                    for last, xml_item in loop:
                        if self.isCanceled():
                            return False
                        self.process_item(xml_item)
                        if self.item_count == BATCH_SIZE:
                            break
                # Make sure Plex DB above is closed before adding/updating!
                self.update_library()
                if last:
                    break
            reset_collections()
            return True
        except RuntimeError:
            LOG.error('Could not entirely process section %s', section)
            return False

    @utils.log_time
    def playstate_per_section(self, section):
        LOG.debug('Processing %s playstates for library section %s',
                  section.iterator.total, section)
        try:
            # Sync new, updated and deleted items
            iterator = section.iterator
            # Tell the processing thread about this new section
            queue_info = InitNewSection(section.context,
                                        iterator.total,
                                        section.name,
                                        section.section_id,
                                        section.plex_type)
            self.queue.put((-1, queue_info))
            self.total = iterator.total
            self.section_name = section.name
            self.section_type_text = utils.lang(
                v.TRANSLATION_FROM_PLEXTYPE[section.plex_type])
            self.current = 0

            last = True
            loop = common.tag_last(iterator)
            while True:
                with section.context(self.current_sync) as itemtype:
                    for i, (last, xml_item) in enumerate(loop):
                        if self.isCanceled():
                            return False
                        if not itemtype.update_userdata(xml_item, section.plex_type):
                            # Somehow did not sync this item yet
                            itemtype.add_update(xml_item,
                                                section_name=section.name,
                                                section_id=section.section_id)
                        itemtype.plexdb.update_last_sync(int(xml_item.attrib['ratingKey']),
                                                         section.plex_type,
                                                         self.current_sync)
                        self.current += 1
                        self.update_progressbar()
                        if (i + 1) % (10 * BATCH_SIZE) == 0:
                            break
                if last:
                    break
            return True
        except RuntimeError:
            LOG.error('Could not entirely process section %s', section)
            return False

    def threaded_get_iterators(self, kinds, queue, all_items=False):
        """
        Getting iterators is costly, so let's do it asynchronously
        """
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
                    element = copy.deepcopy(section)
                    element.plex_type = kind[0]
                    element.section_type = element.plex_type
                    element.context = kind[2]
                    element.get_children = kind[3]
                    element.Queue = kind[4]
                    if self.repair or all_items:
                        updated_at = None
                    else:
                        updated_at = section.last_sync - UPDATED_AT_SAFETY \
                            if section.last_sync else None
                    try:
                        element.iterator = PF.get_section_iterator(
                            section.section_id,
                            plex_type=element.plex_type,
                            updated_at=updated_at,
                            last_viewed_at=None)
                    except RuntimeError:
                        LOG.warn('Sync at least partially unsuccessful')
                        self.successful = False
                        self.section_success = False
                    else:
                        queue.put(element)
        except Exception:
            utils.ERROR(notify=True)
        finally:
            queue.put(None)

    def full_library_sync(self):
        """
        """
        # structure:
        #  (plex_type,
        #   section_type,
        #   context for itemtype,
        #   download children items, e.g. songs for a specific album?,
        #   Queue)
        kinds = [
            (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_MOVIE, itemtypes.Movie, False, queue.Queue),
            (v.PLEX_TYPE_SHOW, v.PLEX_TYPE_SHOW, itemtypes.Show, False, queue.Queue),
            (v.PLEX_TYPE_SEASON, v.PLEX_TYPE_SHOW, itemtypes.Season, False, queue.Queue),
            (v.PLEX_TYPE_EPISODE, v.PLEX_TYPE_SHOW, itemtypes.Episode, False, queue.Queue)
        ]
        if app.SYNC.enable_music:
            kinds.extend([
                (v.PLEX_TYPE_ARTIST, v.PLEX_TYPE_ARTIST, itemtypes.Artist, False, queue.Queue),
                (v.PLEX_TYPE_ALBUM, v.PLEX_TYPE_ARTIST, itemtypes.Album, True, backgroundthread.OrderedQueue),
            ])
        # ADD NEW ITEMS
        # Already start setting up the iterators. We need to enforce
        # syncing e.g. show before season before episode
        iterator_queue = queue.Queue()
        task = backgroundthread.FunctionAsTask(self.threaded_get_iterators,
                                               None,
                                               kinds,
                                               iterator_queue)
        backgroundthread.BGThreader.addTask(task)
        while True:
            self.section_success = True
            section = iterator_queue.get()
            iterator_queue.task_done()
            if section is None:
                break
            # Setup our variables
            self.plex_type = section.plex_type
            self.section_type = section.section_type
            self.context = section.context
            self.get_children = section.get_children
            self.queue = section.Queue()
            # Now do the heavy lifting
            if self.isCanceled() or not self.addupdate_section(section):
                return False
            if self.section_success:
                # Need to check because a thread might have missed to get
                # some items from the PMS
                with PlexDB() as plexdb:
                    # Set the new time mark for the next delta sync
                    plexdb.update_section_last_sync(section.section_id,
                                                    self.current_sync)
        common.update_kodi_library(video=True, music=True)

        # Sync Plex playlists to Kodi and vice-versa
        if common.PLAYLIST_SYNC_ENABLED:
            if self.show_dialog:
                if self.dialog:
                    self.dialog.close()
                self.dialog = xbmcgui.DialogProgressBG()
                # "Synching playlists"
                self.dialog.create(utils.lang(39715))
            if not playlists.full_sync():
                return False

        # SYNC PLAYSTATE of ALL items (otherwise we won't pick up on items that
        # were set to unwatched). Also mark all items on the PMS to be able
        # to delete the ones still in Kodi
        LOG.info('Start synching playstate and userdata for every item')
        # In order to not delete all your songs again
        if app.SYNC.enable_music:
            # We don't need to enforce the album order now
            kinds.pop(5)
            kinds.extend([
                (v.PLEX_TYPE_ALBUM, v.PLEX_TYPE_ARTIST, itemtypes.Album, True, queue.Queue),
                (v.PLEX_TYPE_SONG, v.PLEX_TYPE_ARTIST, itemtypes.Song, True, queue.Queue),
            ])
        # Make sure we're not showing an item's title in the sync dialog
        self.title = ''
        self.threader.shutdown()
        self.threader = None
        if not self.show_dialog_userdata and self.dialog:
            # Close the progress indicator dialog
            self.dialog.close()
            self.dialog = None
        task = backgroundthread.FunctionAsTask(self.threaded_get_iterators,
                                               None,
                                               kinds,
                                               iterator_queue,
                                               all_items=True)
        backgroundthread.BGThreader.addTask(task)
        while True:
            section = iterator_queue.get()
            iterator_queue.task_done()
            if section is None:
                break
            # Setup our variables
            self.plex_type = section.plex_type
            self.section_type = section.section_type
            self.context = section.context
            self.get_children = section.get_children
            # Now do the heavy lifting
            if self.isCanceled() or not self.playstate_per_section(section):
                return False

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
                with context(self.current_sync) as ctx:
                    plex_ids = list(ctx.plexdb.plex_id_by_last_sync(plex_type,
                                                                    self.current_sync,
                                                                    BATCH_SIZE))
                    for plex_id in plex_ids:
                        if self.isCanceled():
                            return False
                        ctx.remove(plex_id, plex_type)
                if len(plex_ids) < BATCH_SIZE:
                    break
        LOG.debug('Done deleting')
        return True

    def run(self):
        app.APP.register_thread(self)
        try:
            self._run()
        finally:
            app.APP.deregister_thread(self)
            LOG.info('Done full_sync')

    @utils.log_time
    def _run(self):
        self.current_sync = timing.plex_now()
        # Get latest Plex libraries and build playlist and video node files
        if self.isCanceled() or not sections.sync_from_pms(self):
            return
        self.successful = True
        try:
            if self.show_dialog:
                self.dialog = xbmcgui.DialogProgressBG()
                self.dialog.create(utils.lang(39714))

            # Actual syncing - do only new items first
            LOG.info('Running full_library_sync with repair=%s',
                     self.repair)
            if self.isCanceled() or not self.full_library_sync():
                self.successful = False
                return
        finally:
            common.update_kodi_library(video=True, music=True)
            if self.dialog:
                self.dialog.close()
            if self.threader:
                self.threader.shutdown()
                self.threader = None
            if not self.successful and not self.isCanceled():
                # "ERROR in library sync"
                utils.dialog('notification',
                             heading='{plex}',
                             message=utils.lang(39410),
                             icon='{error}')
            if self.callback:
                self.callback(self.successful)


def start(show_dialog, repair=False, callback=None):
    FullSync(repair, callback, show_dialog).run()
