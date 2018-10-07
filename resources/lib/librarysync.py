#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
import Queue
from random import shuffle
import copy
from collections import OrderedDict
import xbmc
from xbmcvfs import exists

from . import utils
from .downloadutils import DownloadUtils as DU
from . import itemtypes
from . import plexdb_functions as plexdb
from . import kodidb_functions as kodidb
from . import artwork
from . import videonodes
from . import plex_functions as PF
from .plex_api import API
from .library_sync import get_metadata, process_metadata, fanart, sync_info
from . import music
from . import variables as v
from . import state

if (v.PLATFORM != 'Microsoft UWP' and
        utils.settings('enablePlaylistSync') == 'true'):
    # Xbox cannot use watchdog, a dependency for PKC playlist features
    from . import playlists
    PLAYLIST_SYNC_ENABLED = True
else:
    PLAYLIST_SYNC_ENABLED = False

###############################################################################

LOG = getLogger('PLEX.librarysync')

###############################################################################


def update_library(video=True, music=True):
    """
    Updates the Kodi library and thus refreshes the Kodi views and widgets
    """
    if xbmc.getCondVisibility('Container.Content(musicvideos)') or \
            xbmc.getCondVisibility('Window.IsMedia'):
        # Prevent cursor from moving
        LOG.debug("Refreshing container")
        xbmc.executebuiltin('Container.Refresh')
    else:
        # Update widgets
        if video:
            LOG.debug("Doing Kodi Video Lib update")
            xbmc.executebuiltin('UpdateLibrary(video)')
        if music:
            LOG.debug("Doing Kodi Music Lib update")
            xbmc.executebuiltin('UpdateLibrary(music)')


@utils.thread_methods(add_suspends=['SUSPEND_LIBRARY_THREAD', 'STOP_SYNC'])
class LibrarySync(Thread):
    """
    The one and only library sync thread. Spawn only 1!
    """
    def __init__(self):
        self.items_to_process = []
        self.views = []
        self.session_keys = {}
        self.fanartqueue = Queue.Queue()
        self.fanartthread = fanart.ThreadedProcessFanart(self.fanartqueue)
        # How long should we wait at least to process new/changed PMS items?
        self.vnodes = videonodes.VideoNodes()
        self.install_sync_done = utils.settings('SyncInstallRunDone') == 'true'
        # Show sync dialog even if user deactivated?
        self.force_dialog = True
        # Need to be set accordingly later
        self.compare = None
        self.new_items_only = None
        self.update_kodi_video_library = False
        self.update_kodi_music_library = False
        self.nodes = {}
        self.playlists = {}
        self.sorted_views = []
        self.old_views = []
        self.updatelist = []
        self.all_plex_ids = {}
        self.all_kodi_ids = OrderedDict()
        Thread.__init__(self)

    def suspend_item_sync(self):
        """
        Returns True if we should not sync new items or artwork to Kodi or even
        abort a sync currently running.

        Returns False otherwise.
        """
        if self.suspended() or self.stopped():
            return True
        elif state.SUSPEND_SYNC:
            return True
        return False

    def show_kodi_note(self, message, icon="plex"):
        """
        Shows a Kodi popup, if user selected to do so. Pass message in unicode
        or string

        icon:   "plex": shows Plex icon
                "error": shows Kodi error icon
        """
        if state.SYNC_DIALOG is not True and self.force_dialog is not True:
            return
        if icon == "plex":
            utils.dialog('notification',
                         heading='{plex}',
                         message=message,
                         icon='{plex}',
                         sound=False)
        elif icon == "error":
            utils.dialog('notification',
                         heading='{plex}',
                         message=message,
                         icon='{error}')

    @staticmethod
    def sync_pms_time():
        """
        PMS does not provide a means to get a server timestamp. This is a work-
        around.

        In general, everything saved to Kodi shall be in Kodi time.

        Any info with a PMS timestamp is in Plex time, naturally
        """
        LOG.info('Synching time with PMS server')
        # Find a PMS item where we can toggle the view state to enforce a
        # change in lastViewedAt

        # Get all Plex libraries
        sections = PF.get_plex_sections()
        try:
            sections.attrib
        except AttributeError:
            LOG.error("Error download PMS views, abort sync_pms_time")
            return False

        plex_id = None
        for mediatype in (v.PLEX_TYPE_MOVIE,
                          v.PLEX_TYPE_SHOW,
                          v.PLEX_TYPE_ARTIST):
            if plex_id is not None:
                break
            for view in sections:
                if plex_id is not None:
                    break
                if not view.attrib['type'] == mediatype:
                    continue
                library_id = view.attrib['key']
                items = PF.GetAllPlexLeaves(library_id)
                if items in (None, 401):
                    LOG.error("Could not download section %s",
                              view.attrib['key'])
                    continue
                for item in items:
                    if item.attrib.get('viewCount') is not None:
                        # Don't want to mess with items that have playcount>0
                        continue
                    if item.attrib.get('viewOffset') is not None:
                        # Don't mess with items with a resume point
                        continue
                    plex_id = item.attrib.get('ratingKey')
                    LOG.info('Found an item to sync with: %s', plex_id)
                    break

        if plex_id is None:
            LOG.error("Could not find an item to sync time with")
            LOG.error("Aborting PMS-Kodi time sync")
            return False

        # Get the Plex item's metadata
        xml = PF.GetPlexMetadata(plex_id)
        if xml in (None, 401):
            LOG.error("Could not download metadata, aborting time sync")
            return False

        timestamp = xml[0].attrib.get('lastViewedAt')
        if timestamp is None:
            timestamp = xml[0].attrib.get('updatedAt')
            LOG.debug('Using items updatedAt=%s', timestamp)
            if timestamp is None:
                timestamp = xml[0].attrib.get('addedAt')
                LOG.debug('Using items addedAt=%s', timestamp)
                if timestamp is None:
                    timestamp = 0
                    LOG.debug('No timestamp; using 0')

        # Set the timer
        koditime = utils.unix_timestamp()
        # Toggle watched state
        PF.scrobble(plex_id, 'watched')
        # Let the PMS process this first!
        xbmc.sleep(1000)
        # Get PMS items to find the item we just changed
        items = PF.GetAllPlexLeaves(library_id, lastViewedAt=timestamp)
        # Toggle watched state back
        PF.scrobble(plex_id, 'unwatched')
        if items in (None, 401):
            LOG.error("Could not download metadata, aborting time sync")
            return False

        plextime = None
        for item in items:
            if item.attrib['ratingKey'] == plex_id:
                plextime = item.attrib.get('lastViewedAt')
                break

        if plextime is None:
            LOG.error('Could not get lastViewedAt - aborting')
            return False

        # Calculate time offset Kodi-PMS
        state.KODI_PLEX_TIME_OFFSET = float(koditime) - float(plextime)
        utils.settings('kodiplextimeoffset',
                       value=str(state.KODI_PLEX_TIME_OFFSET))
        LOG.info("Time offset Koditime - Plextime in seconds: %s",
                 str(state.KODI_PLEX_TIME_OFFSET))
        return True

    @staticmethod
    def initialize_plex_db():
        """
        Run once during startup to verify that plex db exists.
        """
        with plexdb.Get_Plex_DB() as plex_db:
            # Create the tables for the plex database
            plex_db.plexcursor.execute('''
                CREATE TABLE IF NOT EXISTS plex(
                    plex_id TEXT UNIQUE,
                    view_id TEXT,
                    plex_type TEXT,
                    kodi_type TEXT,
                    kodi_id INTEGER,
                    kodi_fileid INTEGER,
                    kodi_pathid INTEGER,
                    parent_id INTEGER,
                    checksum INTEGER,
                    fanart_synced INTEGER)
            ''')
            plex_db.plexcursor.execute('''
                CREATE TABLE IF NOT EXISTS view(
                    view_id TEXT UNIQUE,
                    view_name TEXT,
                    kodi_type TEXT,
                    kodi_tagid INTEGER,
                    sync_to_kodi INTEGER)
            ''')
            plex_db.plexcursor.execute('''
                CREATE TABLE IF NOT EXISTS version(idVersion TEXT)
            ''')
            plex_db.plexcursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists(
                    plex_id TEXT UNIQUE,
                    plex_name TEXT,
                    plex_updatedat TEXT,
                    kodi_path TEXT,
                    kodi_type TEXT,
                    kodi_hash TEXT)
            ''')
        # Create an index for actors to speed up sync
        utils.create_actor_db_index()

    @utils.log_time
    def full_sync(self, repair=False):
        """
        repair=True: force sync EVERY item
        """
        # Reset our keys
        self.session_keys = {}
        # self.compare == False: we're syncing EVERY item
        # True: we're syncing only the delta, e.g. different checksum
        self.compare = not repair

        self.new_items_only = True
        # This will also update playstates and userratings!
        LOG.info('Running fullsync for NEW PMS items with repair=%s', repair)
        if self._full_sync() is False:
            return False
        self.new_items_only = False
        # This will NOT update playstates and userratings!
        LOG.info('Running fullsync for CHANGED PMS items with repair=%s',
                 repair)
        if not self._full_sync():
            return False
        if PLAYLIST_SYNC_ENABLED and not playlists.full_sync():
            return False
        return True

    def _full_sync(self):
        process = [self.plex_movies, self.plex_tv_show]
        if state.ENABLE_MUSIC:
            process.append(self.plex_music)

        # Do the processing
        for kind in process:
            if self.suspend_item_sync() or not kind():
                return False

        # Let kodi update the views in any case, since we're doing a full sync
        update_library(video=True, music=state.ENABLE_MUSIC)

        if utils.window('plex_scancrashed') == 'true':
            # Show warning if itemtypes.py crashed at some point
            utils.messageDialog(utils.lang(29999), utils.lang(39408))
            utils.window('plex_scancrashed', clear=True)
        elif utils.window('plex_scancrashed') == '401':
            utils.window('plex_scancrashed', clear=True)
            if state.PMS_STATUS not in ('401', 'Auth'):
                # Plex server had too much and returned ERROR
                utils.messageDialog(utils.lang(29999), utils.lang(39409))
        return True

    def _process_view(self, folder_item, kodi_db, plex_db, totalnodes):
        vnodes = self.vnodes
        folder = folder_item.attrib
        mediatype = folder['type']
        # Only process supported formats
        if mediatype not in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW,
                             v.PLEX_TYPE_ARTIST, v.PLEX_TYPE_PHOTO):
            return totalnodes

        # Prevent duplicate for nodes of the same type
        nodes = self.nodes[mediatype]
        # Prevent duplicate for playlists of the same type
        lists = self.playlists[mediatype]
        sorted_views = self.sorted_views

        folderid = folder['key']
        foldername = folder['title']
        viewtype = folder['type']

        # Get current media folders from plex database
        view = plex_db.getView_byId(folderid)
        try:
            current_viewname = view[0]
            current_viewtype = view[1]
            current_tagid = view[2]
        except TypeError:
            LOG.info('Creating viewid: %s in Plex database.', folderid)
            tagid = kodi_db.create_tag(foldername)
            # Create playlist for the video library
            if (foldername not in lists and
                    mediatype in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)):
                utils.playlist_xsp(mediatype, foldername, folderid, viewtype)
                lists.append(foldername)
            # Create the video node
            if foldername not in nodes:
                vnodes.viewNode(sorted_views.index(foldername),
                                foldername,
                                mediatype,
                                viewtype,
                                folderid)
                nodes.append(foldername)
                totalnodes += 1
            # Add view to plex database
            plex_db.addView(folderid, foldername, viewtype, tagid)
        else:
            LOG.info(' '.join((
                'Found viewid: %s' % folderid,
                'viewname: %s' % current_viewname,
                'viewtype: %s' % current_viewtype,
                'tagid: %s' % current_tagid)))

            # Remove views that are still valid to delete rest later
            try:
                self.old_views.remove(folderid)
            except ValueError:
                # View was just created, nothing to remove
                pass

            # View was modified, update with latest info
            if current_viewname != foldername:
                LOG.info('viewid: %s new viewname: %s', folderid, foldername)
                tagid = kodi_db.create_tag(foldername)

                # Update view with new info
                plex_db.updateView(foldername, tagid, folderid)

                if plex_db.getView_byName(current_viewname) is None:
                    # The tag could be a combined view. Ensure there's
                    # no other tags with the same name before deleting
                    # playlist.
                    utils.playlist_xsp(mediatype,
                                       current_viewname,
                                       folderid,
                                       current_viewtype,
                                       True)
                    # Delete video node
                    if mediatype != "musicvideos":
                        vnodes.viewNode(
                            indexnumber=sorted_views.index(foldername),
                            tagname=current_viewname,
                            mediatype=mediatype,
                            viewtype=current_viewtype,
                            viewid=folderid,
                            delete=True)
                # Added new playlist
                if (foldername not in lists and mediatype in
                        (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)):
                    utils.playlist_xsp(mediatype,
                                       foldername,
                                       folderid,
                                       viewtype)
                    lists.append(foldername)
                # Add new video node
                if foldername not in nodes and mediatype != "musicvideos":
                    vnodes.viewNode(sorted_views.index(foldername),
                                    foldername,
                                    mediatype,
                                    viewtype,
                                    folderid)
                    nodes.append(foldername)
                    totalnodes += 1

                # Update items with new tag
                items = plex_db.getItem_byView(folderid)
                for item in items:
                    # Remove the "s" from viewtype for tags
                    kodi_db.update_tag(
                        current_tagid, tagid, item[0], current_viewtype[:-1])
            else:
                # Validate the playlist exists or recreate it
                if (foldername not in lists and mediatype in
                        (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)):
                    utils.playlist_xsp(mediatype,
                                       foldername,
                                       folderid,
                                       viewtype)
                    lists.append(foldername)
                # Create the video node if not already exists
                if foldername not in nodes and mediatype != "musicvideos":
                    vnodes.viewNode(sorted_views.index(foldername),
                                    foldername,
                                    mediatype,
                                    viewtype,
                                    folderid)
                    nodes.append(foldername)
                    totalnodes += 1
        return totalnodes

    def maintain_views(self):
        """
        Compare the views to Plex
        """
        # Get views
        sections = PF.get_plex_sections()
        try:
            sections.attrib
        except AttributeError:
            LOG.error("Error download PMS views, abort maintain_views")
            return False
        if state.DIRECT_PATHS is True and state.ENABLE_MUSIC is True:
            # Will reboot Kodi is new library detected
            music.excludefromscan_music_folders(xml=sections)
        self.views = []
        vnodes = self.vnodes

        self.nodes = {
            v.PLEX_TYPE_MOVIE: [],
            v.PLEX_TYPE_SHOW: [],
            v.PLEX_TYPE_ARTIST: [],
            v.PLEX_TYPE_PHOTO: []
        }
        self.playlists = copy.deepcopy(self.nodes)
        self.sorted_views = []

        for view in sections:
            if (view.attrib['type'] in
                    (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW, v.PLEX_TYPE_PHOTO,
                     v.PLEX_TYPE_ARTIST)):
                self.sorted_views.append(view.attrib['title'])
        LOG.debug('Sorted views: %s', self.sorted_views)

        # total nodes for window properties
        vnodes.clearProperties()
        totalnodes = len(self.sorted_views)

        with plexdb.Get_Plex_DB() as plex_db:
            # Backup old views to delete them later, if needed (at the end
            # of this method, only unused views will be left in oldviews)
            self.old_views = plex_db.getViews()
            with kodidb.GetKodiDB('video') as kodi_db:
                for folder_item in sections:
                    totalnodes = self._process_view(folder_item,
                                                    kodi_db,
                                                    plex_db,
                                                    totalnodes)
                # Add video nodes listings
                # Plex: there seem to be no favorites/favorites tag
                # vnodes.singleNode(totalnodes,
                #                   "Favorite movies",
                #                   "movies",
                #                   "favourites")
                # totalnodes += 1
                # vnodes.singleNode(totalnodes,
                #                   "Favorite tvshows",
                #                   "tvshows",
                #                   "favourites")
                # totalnodes += 1
                # vnodes.singleNode(totalnodes,
                #                   "channels",
                #                   "movies",
                #                   "channels")
                # totalnodes += 1

        # Save total
        utils.window('Plex.nodes.total', str(totalnodes))

        # Get rid of old items (view has been deleted on Plex side)
        if self.old_views:
            self.delete_views()
        # update views for all:
        with plexdb.Get_Plex_DB() as plex_db:
            self.views = plex_db.getAllViewInfo()
        LOG.info("Finished processing views. Views saved: %s", self.views)
        return True

    def delete_views(self):
        LOG.info("Removing views: %s", self.old_views)
        delete_items = []
        with plexdb.Get_Plex_DB() as plex_db:
            for view in self.old_views:
                plex_db.removeView(view)
                delete_items.extend(plex_db.get_items_by_viewid(view))
        delete_movies = []
        delete_tv = []
        delete_music = []
        for item in delete_items:
            if item['kodi_type'] == v.KODI_TYPE_MOVIE:
                delete_movies.append(item)
            elif item['kodi_type'] in v.KODI_VIDEOTYPES:
                delete_tv.append(item)
            elif item['kodi_type'] in v.KODI_AUDIOTYPES:
                delete_music.append(item)

        utils.dialog('notification',
                     heading='{plex}',
                     message=utils.lang(30052),
                     icon='{plex}',
                     sound=False)
        with itemtypes.Movies() as movie_db:
            for item in delete_movies:
                movie_db.remove(item['plex_id'])
        with itemtypes.TVShows() as tv_db:
            for item in delete_tv:
                tv_db.remove(item['plex_id'])
        # And for the music DB:
        with itemtypes.Music() as music_db:
            for item in delete_music:
                music_db.remove(item['plex_id'])

    def get_updatelist(self, xml, item_class, method, view_name, view_id,
                       get_children=False):
        """
        THIS METHOD NEEDS TO BE FAST! => e.g. no API calls

        Adds items to self.updatelist as well as self.all_plex_ids dict

        Input:
            xml:                    PMS answer for section items
            item_class:             'Movies', 'TVShows', ... see itemtypes.py
            method:                 Method name to be called with this itemtype
                                    see itemtypes.py
            view_name:              Name of the Plex view (e.g. 'My TV shows')
            view_id:                 Id/Key of Plex library (e.g. '1')
            get_children:           will get Plex children of the item if True,
                                    e.g. for music albums

        Output: self.updatelist, self.all_plex_ids
            self.updatelist         APPENDED(!!) list itemids (Plex Keys as
                                    as received from API.plex_id())
            One item in this list is of the form:
                'itemId': xxx,
                'item_class': 'Movies','TVShows', ...
                'method': 'add_update', 'add_updateSeason', ...
                'view_name': xxx,
                'view_id': xxx,
                'title': xxx
                'plex_type': xxx, e.g. 'movie', 'episode'

            self.all_plex_ids      APPENDED(!!) dict
                = {itemid: checksum}
        """
        if self.new_items_only is True:
            # Only process Plex items that Kodi does not already have in lib
            for item in xml:
                plex_id = item.get('ratingKey')
                if not plex_id:
                    # Skipping items 'title=All episodes' without a 'ratingKey'
                    continue
                self.all_plex_ids[plex_id] = "K%s%s" % \
                    (plex_id, item.get('updatedAt', ''))
                if plex_id not in self.all_kodi_ids:
                    self.updatelist.append({
                        'plex_id': plex_id,
                        'item_class': item_class,
                        'method': method,
                        'view_name': view_name,
                        'view_id': view_id,
                        'title': item.get('title', 'Missing Title'),
                        'plex_type': item.get('type'),
                        'get_children': get_children
                    })
        elif self.compare:
            # Only process the delta - new or changed items
            for item in xml:
                plex_id = item.get('ratingKey')
                if not plex_id:
                    # Skipping items 'title=All episodes' without a 'ratingKey'
                    continue
                plex_checksum = ("K%s%s"
                                 % (plex_id, item.get('updatedAt', '')))
                self.all_plex_ids[plex_id] = plex_checksum
                kodi_checksum = self.all_kodi_ids.get(plex_id)
                # Only update if movie is not in Kodi or checksum is
                # different
                if kodi_checksum != plex_checksum:
                    self.updatelist.append({
                        'plex_id': plex_id,
                        'item_class': item_class,
                        'method': method,
                        'view_name': view_name,
                        'view_id': view_id,
                        'title': item.get('title', 'Missing Title'),
                        'plex_type': item.get('type'),
                        'get_children': get_children
                    })
        else:
            # Initial or repair sync: get all Plex movies
            for item in xml:
                plex_id = item.get('ratingKey')
                if not plex_id:
                    # Skipping items 'title=All episodes' without a 'ratingKey'
                    continue
                self.all_plex_ids[plex_id] = "K%s%s" \
                    % (plex_id, item.get('updatedAt', ''))
                self.updatelist.append({
                    'plex_id': plex_id,
                    'item_class': item_class,
                    'method': method,
                    'view_name': view_name,
                    'view_id': view_id,
                    'title': item.get('title', 'Missing Title'),
                    'plex_type': item.get('type'),
                    'get_children': get_children
                })

    def process_updatelist(self, item_class):
        """
        Downloads all XMLs for item_class (e.g. Movies, TV-Shows). Processes
        them by then calling item_classs.<item_class>()

        Input:
            item_class:             'Movies', 'TVShows', ...
            self.updatelist
        """
        # Some logging, just in case.
        item_number = len(self.updatelist)
        if item_number == 0:
            return

        # Run through self.updatelist, get XML metadata per item
        # Initiate threads
        LOG.debug("Starting sync threads")
        download_queue = Queue.Queue()
        process_queue = Queue.Queue(maxsize=100)
        # To keep track
        sync_info.GET_METADATA_COUNT = 0
        sync_info.PROCESS_METADATA_COUNT = 0
        sync_info.PROCESSING_VIEW_NAME = ''
        # Populate queue: GetMetadata
        for item in self.updatelist:
            download_queue.put(item)
        # Spawn GetMetadata threads for downloading
        threads = []
        for _ in range(min(state.SYNC_THREAD_NUMBER, item_number)):
            thread = get_metadata.ThreadedGetMetadata(download_queue,
                                                      process_queue)
            thread.setDaemon(True)
            thread.start()
            threads.append(thread)
        LOG.debug("%s download threads spawned", len(threads))
        # Spawn one more thread to process Metadata, once downloaded
        thread = process_metadata.ThreadedProcessMetadata(process_queue,
                                                          item_class)
        thread.setDaemon(True)
        thread.start()
        threads.append(thread)
        # Start one thread to show sync progress ONLY for new PMS items
        if self.new_items_only is True and (state.SYNC_DIALOG is True or
                                            self.force_dialog is True):
            thread = sync_info.ThreadedShowSyncInfo(item_number, item_class)
            thread.setDaemon(True)
            thread.start()
            threads.append(thread)

        # Wait until finished
        download_queue.join()
        process_queue.join()
        # Kill threads
        LOG.debug("Waiting to kill threads")
        for thread in threads:
            # Threads might already have quit by themselves (e.g. Kodi exit)
            try:
                thread.stop()
            except AttributeError:
                pass
        LOG.debug("Stop sent to all threads")
        # Wait till threads are indeed dead
        for thread in threads:
            try:
                thread.join(1.0)
            except:
                pass
        LOG.debug("Sync threads finished")
        if (utils.settings('FanartTV') == 'true' and
                item_class in ('Movies', 'TVShows')):
            for item in self.updatelist:
                if item['plex_type'] in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW):
                    self.fanartqueue.put({
                        'plex_id': item['plex_id'],
                        'plex_type': item['plex_type'],
                        'refresh': False
                    })
        self.updatelist = []

    @utils.log_time
    def plex_movies(self):
        # Initialize
        self.all_plex_ids = {}

        item_class = 'Movies'

        views = [x for x in self.views if x['itemtype'] == v.KODI_TYPE_MOVIE]
        LOG.info("Processing Plex %s. Libraries: %s", item_class, views)

        self.all_kodi_ids = OrderedDict()
        if self.compare:
            with plexdb.Get_Plex_DB() as plex_db:
                # Get movies from Plex server
                # Pull the list of movies and boxsets in Kodi
                try:
                    self.all_kodi_ids = OrderedDict(
                        plex_db.checksum(v.PLEX_TYPE_MOVIE))
                except ValueError:
                    self.all_kodi_ids = OrderedDict()

        # PROCESS MOVIES #####
        self.updatelist = []
        for view in views:
            if not self.install_sync_done:
                state.PATH_VERIFIED = False
            if self.suspend_item_sync():
                return False
            # Get items per view
            all_plexmovies = PF.GetPlexSectionResults(view['id'], args=None)
            if all_plexmovies is None:
                LOG.info("Couldnt get section items, aborting for view.")
                continue
            elif all_plexmovies == 401:
                return False
            # Populate self.updatelist and self.all_plex_ids
            self.get_updatelist(all_plexmovies,
                                item_class,
                                'add_update',
                                view['name'],
                                view['id'])
        self.process_updatelist(item_class)
        # Update viewstate for EVERY item
        for view in views:
            if self.suspend_item_sync():
                return False
            self.plex_update_watched(view['id'], item_class)

        # PROCESS DELETES #####
        if self.compare:
            # Manual sync, process deletes
            with itemtypes.Movies() as movie_db:
                for kodimovie in self.all_kodi_ids:
                    if kodimovie not in self.all_plex_ids:
                        movie_db.remove(kodimovie)
        LOG.info("%s sync is finished.", item_class)
        return True

    def plex_update_watched(self, viewId, item_class, lastViewedAt=None,
                            updatedAt=None):
        """
        Updates plex elements' view status ('watched' or 'unwatched') and
        also updates resume times.
        This is done by downloading one XML for ALL elements with viewId
        """
        if self.new_items_only is False:
            # Only do this once for fullsync: the first run where new items are
            # added to Kodi
            return
        xml = PF.GetAllPlexLeaves(viewId,
                                  lastViewedAt=lastViewedAt,
                                  updatedAt=updatedAt)
        # Return if there are no items in PMS reply - it's faster
        try:
            xml[0].attrib
        except (TypeError, AttributeError, IndexError):
            LOG.error('Error updating watch status. Could not get viewId: '
                      '%s of item_class %s with lastViewedAt: %s, updatedAt: '
                      '%s', viewId, item_class, lastViewedAt, updatedAt)
            return

        if item_class in ('Movies', 'TVShows'):
            self.update_kodi_video_library = True
        elif item_class == 'Music':
            self.update_kodi_music_library = True
        with getattr(itemtypes, item_class)() as itemtype:
            itemtype.updateUserdata(xml)

    @utils.log_time
    def plex_tv_show(self):
        # Initialize
        self.all_plex_ids = {}
        item_class = 'TVShows'

        views = [x for x in self.views if x['itemtype'] == 'show']
        LOG.info("Media folders for %s: %s", item_class, views)

        self.all_kodi_ids = OrderedDict()
        if self.compare:
            with plexdb.Get_Plex_DB() as plex:
                # Pull the list of TV shows already in Kodi
                for kind in (v.PLEX_TYPE_SHOW,
                             v.PLEX_TYPE_SEASON,
                             v.PLEX_TYPE_EPISODE):
                    try:
                        elements = dict(plex.checksum(kind))
                        self.all_kodi_ids.update(elements)
                    # Yet empty/not yet synched
                    except ValueError:
                        pass

        # PROCESS TV Shows #####
        self.updatelist = []
        for view in views:
            if not self.install_sync_done:
                state.PATH_VERIFIED = False
            if self.suspend_item_sync():
                return False
            # Get items per view
            view_id = view['id']
            view_name = view['name']
            all_plex_tv_shows = PF.GetPlexSectionResults(view_id)
            if all_plex_tv_shows is None:
                LOG.error("Error downloading show xml for view %s", view_id)
                continue
            elif all_plex_tv_shows == 401:
                return False
            # Populate self.updatelist and self.all_plex_ids
            self.get_updatelist(all_plex_tv_shows,
                                item_class,
                                'add_update',
                                view_name,
                                view_id)
            LOG.debug("Analyzed view %s with ID %s", view_name, view_id)

        # COPY for later use
        all_plex_tv_show_ids = self.all_plex_ids.copy()

        # Process self.updatelist
        self.process_updatelist(item_class)
        LOG.debug("process_updatelist completed for tv shows")

        # PROCESS TV Seasons #####
        # Cycle through tv shows
        for show_id in all_plex_tv_show_ids:
            if self.suspend_item_sync():
                return False
            # Grab all seasons to tvshow from PMS
            seasons = PF.GetAllPlexChildren(show_id)
            if seasons is None:
                LOG.error("Error download season xml for show %s", show_id)
                continue
            elif seasons == 401:
                return False
            # Populate self.updatelist and self.all_plex_ids
            self.get_updatelist(seasons,
                                item_class,
                                'add_updateSeason',
                                view_name,
                                view_id)
            LOG.debug("Analyzed all seasons of TV show with Plex Id %s",
                      show_id)

        # Process self.updatelist
        self.process_updatelist(item_class)
        LOG.debug("process_updatelist completed for seasons")

        # PROCESS TV Episodes #####
        # Cycle through tv shows
        for view in views:
            if self.suspend_item_sync():
                return False
            # Grab all episodes to tvshow from PMS
            episodes = PF.GetAllPlexLeaves(view['id'])
            if episodes is None:
                LOG.error("Error downloading episod xml for view %s",
                          view.get('name'))
                continue
            elif episodes == 401:
                return False
            # Populate self.updatelist and self.all_plex_ids
            self.get_updatelist(episodes,
                                item_class,
                                'add_updateEpisode',
                                view_name,
                                view_id)
            LOG.debug("Analyzed all episodes of TV show with Plex Id %s",
                      view['id'])

        # Process self.updatelist
        self.process_updatelist(item_class)
        LOG.debug("process_updatelist completed for episodes")
        # Refresh season info
        # Cycle through tv shows
        with itemtypes.TVShows() as tvshow_db:
            for show_id in all_plex_tv_show_ids:
                xml_show = PF.GetPlexMetadata(show_id)
                if xml_show is None or xml_show == 401:
                    LOG.error('Could not download xml_show')
                    continue
                tvshow_db.refreshSeasonEntry(xml_show, show_id)
        LOG.debug("Season info refreshed")

        # Update viewstate:
        for view in views:
            if self.suspend_item_sync():
                return False
            self.plex_update_watched(view['id'], item_class)

        if self.compare:
            # Manual sync, process deletes
            with itemtypes.TVShows() as tvshow_db:
                for item in self.all_kodi_ids:
                    if item not in self.all_plex_ids:
                        tvshow_db.remove(item)
        LOG.info("%s sync is finished.", item_class)
        return True

    @utils.log_time
    def plex_music(self):
        item_class = 'Music'

        views = [x for x in self.views if x['itemtype'] == v.PLEX_TYPE_ARTIST]
        LOG.info("Media folders for %s: %s", item_class, views)

        methods = {
            v.PLEX_TYPE_ARTIST: 'add_updateArtist',
            v.PLEX_TYPE_ALBUM: 'add_updateAlbum',
            v.PLEX_TYPE_SONG: 'add_updateSong'
        }
        urlArgs = {
            v.PLEX_TYPE_ARTIST: {'type': 8},
            v.PLEX_TYPE_ALBUM: {'type': 9},
            v.PLEX_TYPE_SONG: {'type': 10}
        }

        # Process artist, then album and tracks last to minimize overhead
        # Each album needs to be processed directly with its songs
        # Remaining songs without album will be processed last
        for kind in (v.PLEX_TYPE_ARTIST,
                     v.PLEX_TYPE_ALBUM,
                     v.PLEX_TYPE_SONG):
            if self.suspend_item_sync():
                return False
            LOG.debug("Start processing music %s", kind)
            self.all_kodi_ids = OrderedDict()
            self.all_plex_ids = {}
            self.updatelist = []
            if not self.process_music(views,
                                      kind,
                                      urlArgs[kind],
                                      methods[kind]):
                return False
            LOG.debug("Processing of music %s done", kind)
            self.process_updatelist(item_class)
            LOG.debug("process_updatelist for music %s completed", kind)

        # Update viewstate for EVERY item
        for view in views:
            if self.suspend_item_sync():
                return False
            self.plex_update_watched(view['id'], item_class)

        # reset stuff
        self.all_kodi_ids = OrderedDict()
        self.all_plex_ids = {}
        self.updatelist = []
        LOG.info("%s sync is finished.", item_class)
        return True

    def process_music(self, views, kind, urlArgs, method):
        # For albums, we need to look at the album's songs simultaneously
        get_children = True if kind == v.PLEX_TYPE_ALBUM else False
        # Get a list of items already existing in Kodi db
        if self.compare:
            with plexdb.Get_Plex_DB() as plex_db:
                # Pull the list of items already in Kodi
                try:
                    elements = dict(plex_db.checksum(kind))
                    self.all_kodi_ids.update(elements)
                # Yet empty/nothing yet synched
                except ValueError:
                    pass
        for view in views:
            if not self.install_sync_done:
                state.PATH_VERIFIED = False
            if self.suspend_item_sync():
                return False
            # Get items per view
            items_xml = PF.GetPlexSectionResults(view['id'], args=urlArgs)
            if items_xml is None:
                LOG.error("Error downloading xml for view %s", view['id'])
                continue
            elif items_xml == 401:
                return False
            # Populate self.updatelist and self.all_plex_ids
            self.get_updatelist(items_xml,
                                'Music',
                                method,
                                view['name'],
                                view['id'],
                                get_children=get_children)
        if self.compare:
            # Manual sync, process deletes
            with itemtypes.Music() as music_db:
                for itemid in self.all_kodi_ids:
                    if itemid not in self.all_plex_ids:
                        music_db.remove(itemid)
        return True

    def process_message(self, message):
        """
        processes json.loads() messages from websocket. Triage what we need to
        do with "process_" methods
        """
        try:
            if message['type'] == 'playing':
                self.process_playing(message['PlaySessionStateNotification'])
            elif message['type'] == 'timeline':
                self.process_timeline(message['TimelineEntry'])
            elif message['type'] == 'activity':
                self.process_activity(message['ActivityNotification'])
        except:
            LOG.error('Processing of Plex Companion message has crashed')
            LOG.error('Message was: %s', message)
            import traceback
            LOG.error("Traceback:\n%s", traceback.format_exc())

    def multi_delete(self, liste, delete_list):
        """
        Deletes the list items of liste at the positions in delete_list
        (which can be in any arbitrary order)
        """
        indexes = sorted(delete_list, reverse=True)
        for index in indexes:
            del liste[index]
        return liste

    def process_items(self):
        """
        Periodically called to process new/updated PMS items

        PMS needs a while to download info from internet AFTER it
        showed up under 'timeline' websocket messages

        data['type']:
            1:      movie
            2:      tv show??
            3:      season??
            4:      episode
            8:      artist (band)
            9:      album
            10:     track (song)
            12:     trailer, extras?

        data['state']:
            0: 'created',
            2: 'matching',
            3: 'downloading',
            4: 'loading',
            5: 'finished',
            6: 'analyzing',
            9: 'deleted'
        """
        now = utils.unix_timestamp()
        delete_list = []
        for i, item in enumerate(self.items_to_process):
            if self.stopped() or self.suspended():
                # Chances are that Kodi gets shut down
                break
            if item['state'] == 9:
                successful = self.process_deleteditems(item)
            elif now - item['timestamp'] < state.BACKGROUNDSYNC_SAFTYMARGIN:
                # We haven't waited long enough for the PMS to finish
                # processing the item. Do it later (excepting deletions)
                continue
            else:
                successful = self.process_newitems(item)
                if successful and utils.settings('FanartTV') == 'true':
                    if item['type'] in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW):
                        self.fanartqueue.put({
                            'plex_id': item['ratingKey'],
                            'plex_type': item['type'],
                            'refresh': False
                        })
            if successful is True:
                delete_list.append(i)
            else:
                # Safety net if we can't process an item
                item['attempt'] += 1
                if item['attempt'] > 3:
                    LOG.error('Repeatedly could not process item %s, abort',
                              item)
                    delete_list.append(i)

        # Get rid of the items we just processed
        if delete_list:
            self.items_to_process = self.multi_delete(self.items_to_process,
                                                      delete_list)
        # Let Kodi know of the change
        if self.update_kodi_video_library or self.update_kodi_music_library:
            update_library(video=self.update_kodi_video_library,
                           music=self.update_kodi_music_library)
            self.update_kodi_video_library = False
            self.update_kodi_music_library = False

    def process_newitems(self, item):
        xml = PF.GetPlexMetadata(item['ratingKey'])
        try:
            mediatype = xml[0].attrib['type']
        except (IndexError, KeyError, TypeError):
            LOG.error('Could not download metadata for %s', item['ratingKey'])
            return False
        LOG.debug("Processing new/updated PMS item: %s", item['ratingKey'])
        viewtag = xml.attrib.get('librarySectionTitle')
        viewid = xml.attrib.get('librarySectionID')
        if mediatype == v.PLEX_TYPE_MOVIE:
            self.update_kodi_video_library = True
            with itemtypes.Movies() as movie:
                movie.add_update(xml[0],
                                 viewtag=viewtag,
                                 viewid=viewid)
        elif mediatype == v.PLEX_TYPE_EPISODE:
            self.update_kodi_video_library = True
            with itemtypes.TVShows() as show:
                show.add_updateEpisode(xml[0],
                                       viewtag=viewtag,
                                       viewid=viewid)
        elif mediatype == v.PLEX_TYPE_SONG:
            self.update_kodi_music_library = True
            with itemtypes.Music() as music_db:
                music_db.add_updateSong(xml[0], viewtag=viewtag, viewid=viewid)
        return True

    def process_deleteditems(self, item):
        if item['type'] == v.PLEX_TYPE_MOVIE:
            LOG.debug("Removing movie %s", item['ratingKey'])
            self.update_kodi_video_library = True
            with itemtypes.Movies() as movie:
                movie.remove(item['ratingKey'])
        elif item['type'] in (v.PLEX_TYPE_SHOW,
                              v.PLEX_TYPE_SEASON,
                              v.PLEX_TYPE_EPISODE):
            LOG.debug("Removing episode/season/show with plex id %s",
                      item['ratingKey'])
            self.update_kodi_video_library = True
            with itemtypes.TVShows() as show:
                show.remove(item['ratingKey'])
        elif item['type'] in (v.PLEX_TYPE_ARTIST,
                              v.PLEX_TYPE_ALBUM,
                              v.PLEX_TYPE_SONG):
            LOG.debug("Removing song/album/artist %s", item['ratingKey'])
            self.update_kodi_music_library = True
            with itemtypes.Music() as music_db:
                music_db.remove(item['ratingKey'])
        return True

    def process_timeline(self, data):
        """
        PMS is messing with the library items, e.g. new or changed. Put in our
        "processing queue" for later
        """
        for item in data:
            if 'tv.plex' in item.get('identifier', ''):
                # Ommit Plex DVR messages - the Plex IDs are not corresponding
                # (DVR ratingKeys are not unique and might correspond to a
                # movie or episode)
                continue
            typus = v.PLEX_TYPE_FROM_WEBSOCKET[int(item['type'])]
            if typus == v.PLEX_TYPE_CLIP:
                # No need to process extras or trailers
                continue
            status = int(item['state'])
            if typus == 'playlist':
                if not PLAYLIST_SYNC_ENABLED:
                    continue
                playlists.websocket(plex_id=unicode(item['itemID']),
                                    status=status)
            elif status == 9:
                # Immediately and always process deletions (as the PMS will
                # send additional message with other codes)
                self.items_to_process.append({
                    'state': status,
                    'type': typus,
                    'ratingKey': str(item['itemID']),
                    'timestamp': utils.unix_timestamp(),
                    'attempt': 0
                })
            elif typus in (v.PLEX_TYPE_MOVIE,
                           v.PLEX_TYPE_EPISODE,
                           v.PLEX_TYPE_SONG) and status == 5:
                plex_id = str(item['itemID'])
                # Have we already added this element for processing?
                for existing_item in self.items_to_process:
                    if existing_item['ratingKey'] == plex_id:
                        break
                else:
                    # Haven't added this element to the queue yet
                    self.items_to_process.append({
                        'state': status,
                        'type': typus,
                        'ratingKey': plex_id,
                        'timestamp': utils.unix_timestamp(),
                        'attempt': 0
                    })

    def process_activity(self, data):
        """
        PMS is re-scanning an item, e.g. after having changed a movie poster.
        WATCH OUT for this if it's triggered by our PKC library scan!
        """
        for item in data:
            if item['event'] != 'ended':
                # Scan still going on, so skip for now
                continue
            elif item['Activity'].get('Context') is None:
                # Not related to any Plex element, but entire library
                continue
            elif item['Activity']['type'] != 'library.refresh.items':
                # Not the type of message relevant for us
                continue
            plex_id = PF.GetPlexKeyNumber(item['Activity']['Context']['key'])[1]
            if plex_id == '':
                # Likely a Plex id like /library/metadata/3/children
                continue
            # We're only looking at existing elements - have we synced yet?
            with plexdb.Get_Plex_DB() as plex_db:
                kodi_info = plex_db.getItem_byId(plex_id)
            if kodi_info is None:
                LOG.debug('Plex id %s not synced yet - skipping', plex_id)
                continue
            # Have we already added this element?
            for existing_item in self.items_to_process:
                if existing_item['ratingKey'] == plex_id:
                    break
            else:
                # Haven't added this element to the queue yet
                self.items_to_process.append({
                    'state': None,  # Don't need a state here
                    'type': kodi_info[5],
                    'ratingKey': plex_id,
                    'timestamp': utils.unix_timestamp(),
                    'attempt': 0
                })

    def process_playing(self, data):
        """
        Someone (not necessarily the user signed in) is playing something some-
        where
        """
        for item in data:
            status = item['state']
            if status == 'buffering' or status == 'stopped':
                # Drop buffering and stop messages immediately - no value
                continue
            plex_id = item['ratingKey']
            skip = False
            for pid in (0, 1, 2):
                if plex_id == state.PLAYER_STATES[pid]['plex_id']:
                    # Kodi is playing this item - no need to set the playstate
                    skip = True
            if skip:
                continue
            session_key = item['sessionKey']
            # Do we already have a sessionKey stored?
            if session_key not in self.session_keys:
                with plexdb.Get_Plex_DB() as plex_db:
                    kodi_info = plex_db.getItem_byId(plex_id)
                if kodi_info is None:
                    # Item not (yet) in Kodi library
                    continue
                if utils.settings('plex_serverowned') == 'false':
                    # Not our PMS, we are not authorized to get the sessions
                    # On the bright side, it must be us playing :-)
                    self.session_keys[session_key] = {}
                else:
                    # PMS is ours - get all current sessions
                    self.session_keys.update(PF.GetPMSStatus(state.PLEX_TOKEN))
                    LOG.debug('Updated current sessions. They are: %s',
                              self.session_keys)
                    if session_key not in self.session_keys:
                        LOG.info('Session key %s still unknown! Skip '
                                 'playstate update', session_key)
                        continue
                # Attach Kodi info to the session
                self.session_keys[session_key]['kodi_id'] = kodi_info[0]
                self.session_keys[session_key]['file_id'] = kodi_info[1]
                self.session_keys[session_key]['kodi_type'] = kodi_info[4]
            session = self.session_keys[session_key]
            if utils.settings('plex_serverowned') != 'false':
                # Identify the user - same one as signed on with PKC? Skip
                # update if neither session's username nor userid match
                # (Owner sometime's returns id '1', not always)
                if not state.PLEX_TOKEN and session['userId'] == '1':
                    # PKC not signed in to plex.tv. Plus owner of PMS is
                    # playing (the '1').
                    # Hence must be us (since several users require plex.tv
                    # token for PKC)
                    pass
                elif not (session['userId'] == state.PLEX_USER_ID or
                          session['username'] == state.PLEX_USERNAME):
                    LOG.debug('Our username %s, userid %s did not match '
                              'the session username %s with userid %s',
                              state.PLEX_USERNAME,
                              state.PLEX_USER_ID,
                              session['username'],
                              session['userId'])
                    continue
            # Get an up-to-date XML from the PMS because PMS will NOT directly
            # tell us: duration of item viewCount
            if session.get('duration') is None:
                xml = PF.GetPlexMetadata(plex_id)
                if xml in (None, 401):
                    LOG.error('Could not get up-to-date xml for item %s',
                              plex_id)
                    continue
                api = API(xml[0])
                userdata = api.userdata()
                session['duration'] = userdata['Runtime']
                session['viewCount'] = userdata['PlayCount']
            # Sometimes, Plex tells us resume points in milliseconds and
            # not in seconds - thank you very much!
            if item['viewOffset'] > session['duration']:
                resume = item['viewOffset'] / 1000
            else:
                resume = item['viewOffset']
            if resume < v.IGNORE_SECONDS_AT_START:
                continue
            try:
                completed = float(resume) / float(session['duration'])
            except (ZeroDivisionError, TypeError):
                LOG.error('Could not mark playstate for %s and session %s',
                          data, session)
                continue
            if completed >= v.MARK_PLAYED_AT:
                # Only mark completely watched ONCE
                if session.get('marked_played') is None:
                    session['marked_played'] = True
                    mark_played = True
                else:
                    # Don't mark it as completely watched again
                    continue
            else:
                mark_played = False
            LOG.debug('Update playstate for user %s with id %s for plex id %s',
                      state.PLEX_USERNAME, state.PLEX_USER_ID, plex_id)
            item_fkt = getattr(itemtypes,
                               v.ITEMTYPE_FROM_KODITYPE[session['kodi_type']])
            with item_fkt() as fkt:
                plex_type = v.PLEX_TYPE_FROM_KODI_TYPE[session['kodi_type']]
                fkt.updatePlaystate(mark_played,
                                    session['viewCount'],
                                    resume,
                                    session['duration'],
                                    session['file_id'],
                                    utils.unix_date_to_kodi(
                                        utils.unix_timestamp()),
                                    plex_type)

    def sync_fanart(self, missing_only=True, refresh=False):
        """
        Throw items to the fanart queue in order to download missing (or all)
        additional fanart.

        missing_only=True    False will start look-up for EVERY item
        refresh=False        True will force refresh all external fanart
        """
        if utils.settings('FanartTV') == 'false':
            return
        with plexdb.Get_Plex_DB() as plex_db:
            if missing_only:
                with plexdb.Get_Plex_DB() as plex_db:
                    items = plex_db.get_missing_fanart()
                LOG.info('Trying to get %s additional fanart', len(items))
            else:
                items = []
                for plex_type in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW):
                    items.extend(plex_db.itemsByType(plex_type))
                LOG.info('Trying to get ALL additional fanart for %s items',
                         len(items))
        if not items:
            return
        # Shuffle the list to not always start out identically
        shuffle(items)
        # Checking FanartTV for %s items
        self.fanartqueue.put(artwork.ArtworkSyncMessage(
            utils.lang(30018) % len(items)))
        for item in items:
            self.fanartqueue.put({
                'plex_id': item['plex_id'],
                'plex_type': item['plex_type'],
                'refresh': refresh
            })
        # FanartTV lookup completed
        self.fanartqueue.put(artwork.ArtworkSyncMessage(utils.lang(30019)))

    def triage_lib_scans(self):
        """
        Decides what to do if state.RUN_LIB_SCAN has been set. E.g. manually
        triggered full or repair syncs
        """
        if state.RUN_LIB_SCAN in ("full", "repair"):
            LOG.info('Full library scan requested, starting')
            utils.window('plex_dbScan', value="true")
            state.DB_SCAN = True
            success = self.maintain_views()
            if success and state.RUN_LIB_SCAN == "full":
                success = self.full_sync()
            elif success:
                success = self.full_sync(repair=True)
            utils.window('plex_dbScan', clear=True)
            state.DB_SCAN = False
            if success:
                # Full library sync finished
                self.show_kodi_note(utils.lang(39407))
            elif not self.suspend_item_sync():
                self.force_dialog = True
                # ERROR in library sync
                self.show_kodi_note(utils.lang(39410), icon='error')
                self.force_dialog = False
        # Reset views was requested from somewhere else
        elif state.RUN_LIB_SCAN == "views":
            LOG.info('Refresh playlist and nodes requested, starting')
            utils.window('plex_dbScan', value="true")
            state.DB_SCAN = True
            # First remove playlists
            utils.delete_playlists()
            # Remove video nodes
            utils.delete_nodes()
            # Kick off refresh
            if self.maintain_views() is True:
                # Ran successfully
                LOG.info("Refresh playlists/nodes completed")
                # "Plex playlists/nodes refreshed"
                self.show_kodi_note(utils.lang(39405))
            else:
                # Failed
                LOG.error("Refresh playlists/nodes failed")
                # "Plex playlists/nodes refresh failed"
                self.show_kodi_note(utils.lang(39406), icon="error")
            utils.window('plex_dbScan', clear=True)
            state.DB_SCAN = False
        elif state.RUN_LIB_SCAN == 'fanart':
            # Only look for missing fanart (No)
            # or refresh all fanart (Yes)
            from .windows import optionsdialog
            refresh = optionsdialog.show(utils.lang(29999),
                                         utils.lang(39223),
                                         utils.lang(39224),  # refresh all
                                         utils.lang(39225)) == 0
            self.sync_fanart(missing_only=not refresh, refresh=refresh)
        elif state.RUN_LIB_SCAN == 'textures':
            state.DB_SCAN = True
            utils.window('plex_dbScan', value="true")
            artwork.Artwork().fullTextureCacheSync()
            utils.window('plex_dbScan', clear=True)
            state.DB_SCAN = False
        else:
            raise NotImplementedError('Library scan not defined: %s'
                                      % state.RUN_LIB_SCAN)
        # Reset
        state.RUN_LIB_SCAN = None

    def run(self):
        try:
            self._run_internal()
        except Exception as e:
            state.DB_SCAN = False
            utils.window('plex_dbScan', clear=True)
            LOG.error('LibrarySync thread crashed. Error message: %s', e)
            import traceback
            LOG.error("Traceback:\n%s", traceback.format_exc())
            # Library sync thread has crashed
            utils.messageDialog(utils.lang(29999), utils.lang(39400))
            raise

    def _run_internal(self):
        LOG.info("---===### Starting LibrarySync ###===---")
        initial_sync_done = False
        kodi_db_version_checked = False
        last_sync = 0
        last_processing = 0
        last_time_sync = 0
        one_day_in_seconds = 60 * 60 * 24
        # Link to Websocket queue
        queue = state.WEBSOCKET_QUEUE

        if (not exists(utils.try_encode(v.DB_VIDEO_PATH)) or
                not exists(utils.try_encode(v.DB_TEXTURE_PATH)) or
                (state.ENABLE_MUSIC and
                 not exists(utils.try_encode(v.DB_MUSIC_PATH)))):
            # Database does not exists
            LOG.error("The current Kodi version is incompatible "
                      "to know which Kodi versions are supported.")
            LOG.error('Current Kodi version: %s', utils.try_decode(
                xbmc.getInfoLabel('System.BuildVersion')))
            # "Current Kodi version is unsupported, cancel lib sync"
            utils.messageDialog(utils.lang(29999), utils.lang(39403))
            return

        # Do some initializing
        # Ensure that DBs exist if called for very first time
        self.initialize_plex_db()
        # Run start up sync
        state.DB_SCAN = True
        utils.window('plex_dbScan', value="true")
        LOG.info("Db version: %s", utils.settings('dbCreatedWithVersion'))

        LOG.info('Refreshing video nodes and playlists now')
        with kodidb.GetKodiDB('video') as kodi_db:
            # Setup the paths for addon-paths (even when using direct paths)
            kodi_db.setup_path_table()
        with kodidb.GetKodiDB('music') as kodi_db:
            # Hack for a dummy genre entry - even when we're not using
            # Plex Music
            kodi_db.setup_music_db_dummy_entries()
        utils.window('plex_dbScan', clear=True)
        state.DB_SCAN = False
        playlist_monitor = None

        while not self.stopped():
            # In the event the server goes offline
            while self.suspended():
                if self.stopped():
                    # Abort was requested while waiting. We should exit
                    LOG.info("###===--- LibrarySync Stopped ---===###")
                    return
                xbmc.sleep(1000)

            if not self.install_sync_done:
                # Very first sync upon installation or reset of Kodi DB
                state.DB_SCAN = True
                utils.window('plex_dbScan', value='true')
                # Initialize time offset Kodi - PMS
                self.sync_pms_time()
                last_time_sync = utils.unix_timestamp()
                LOG.info('Initial start-up full sync starting')
                xbmc.executebuiltin('InhibitIdleShutdown(true)')
                # Completely refresh Kodi playlists and video nodes
                utils.delete_playlists()
                utils.delete_nodes()
                if not self.maintain_views():
                    LOG.error('Initial maintain_views not successful')
                elif self.full_sync():
                    LOG.info('Initial start-up full sync successful')
                    utils.settings('SyncInstallRunDone', value='true')
                    self.install_sync_done = True
                    utils.settings('dbCreatedWithVersion', v.ADDON_VERSION)
                    self.force_dialog = False
                    initial_sync_done = True
                    kodi_db_version_checked = True
                    last_sync = utils.unix_timestamp()
                    if PLAYLIST_SYNC_ENABLED:
                        playlist_monitor = playlists.kodi_playlist_monitor()
                    self.sync_fanart()
                    self.fanartthread.start()
                else:
                    LOG.error('Initial start-up full sync unsuccessful')
                xbmc.executebuiltin('InhibitIdleShutdown(false)')
                utils.window('plex_dbScan', clear=True)
                state.DB_SCAN = False

            elif not kodi_db_version_checked:
                # Install sync was already done, don't force-show dialogs
                self.force_dialog = False
                # Verify the validity of the database
                current_version = utils.settings('dbCreatedWithVersion')
                if not utils.compare_version(current_version,
                                             v.MIN_DB_VERSION):
                    LOG.warn("Db version out of date: %s minimum version "
                             "required: %s", current_version, v.MIN_DB_VERSION)
                    # DB out of date. Proceed to recreate?
                    if not utils.yesno_dialog(utils.lang(29999),
                                              utils.lang(39401)):
                        LOG.warn("Db version out of date! USER IGNORED!")
                        # PKC may not work correctly until reset
                        utils.messageDialog(utils.lang(29999),
                                            '%s%s' % (utils.lang(29999),
                                                      utils.lang(39402)))
                    else:
                        utils.reset(ask_user=False)
                    break
                kodi_db_version_checked = True

            elif not initial_sync_done:
                # First sync upon PKC restart. Skipped if very first sync upon
                # PKC installation has been completed
                state.DB_SCAN = True
                utils.window('plex_dbScan', value="true")
                LOG.info('Doing initial sync on Kodi startup')
                if state.SUSPEND_SYNC:
                    LOG.warning('Forcing startup sync even if Kodi is playing')
                    state.SUSPEND_SYNC = False
                # Completely refresh Kodi playlists and video nodes
                utils.delete_playlists()
                utils.delete_nodes()
                if not self.maintain_views():
                    LOG.info('Initial maintain_views on startup unsuccessful')
                elif self.full_sync():
                    initial_sync_done = True
                    last_sync = utils.unix_timestamp()
                    LOG.info('Done initial sync on Kodi startup')
                    if PLAYLIST_SYNC_ENABLED:
                        playlist_monitor = playlists.kodi_playlist_monitor()
                    artwork.Artwork().cache_major_artwork()
                    self.sync_fanart()
                    self.fanartthread.start()
                else:
                    LOG.info('Startup sync has not yet been successful')
                utils.window('plex_dbScan', clear=True)
                state.DB_SCAN = False

            # Currently no db scan, so we can start a new scan
            elif state.DB_SCAN is False:
                # Full scan was requested from somewhere else, e.g. userclient
                if state.RUN_LIB_SCAN is not None:
                    # Force-show dialogs since they are user-initiated
                    self.force_dialog = True
                    self.triage_lib_scans()
                    self.force_dialog = False
                    continue
                now = utils.unix_timestamp()
                # Standard syncs - don't force-show dialogs
                self.force_dialog = False
                if (now - last_sync > state.FULL_SYNC_INTERVALL and
                        not self.suspend_item_sync()):
                    LOG.info('Doing scheduled full library scan')
                    state.DB_SCAN = True
                    utils.window('plex_dbScan', value="true")
                    success = self.maintain_views()
                    if success:
                        success = self.full_sync()
                    if not success and not self.suspend_item_sync():
                        LOG.error('Could not finish scheduled full sync')
                        self.force_dialog = True
                        self.show_kodi_note(utils.lang(39410),
                                            icon='error')
                        self.force_dialog = False
                    elif success:
                        last_sync = now
                        # Full library sync finished successfully
                        self.show_kodi_note(utils.lang(39407))
                    else:
                        LOG.info('Full sync interrupted')
                    utils.window('plex_dbScan', clear=True)
                    state.DB_SCAN = False
                elif now - last_time_sync > one_day_in_seconds:
                    LOG.info('Starting daily time sync')
                    self.sync_pms_time()
                    last_time_sync = now
                elif not state.BACKGROUND_SYNC_DISABLED:
                    # Check back whether we should process something
                    # Only do this once every while (otherwise, potentially
                    # many screen refreshes lead to flickering)
                    if now - last_processing > 5:
                        last_processing = now
                        self.process_items()
                    # See if there is a PMS message we need to handle
                    try:
                        message = queue.get(block=False)
                    except Queue.Empty:
                        pass
                    # Got a message from PMS; process it
                    else:
                        self.process_message(message)
                        queue.task_done()
                        # Sleep just a bit
                        xbmc.sleep(10)
                        continue
            xbmc.sleep(100)
        # Shut down playlist monitoring
        if playlist_monitor:
            playlist_monitor.stop()
        # doUtils could still have a session open due to interrupted sync
        try:
            DU().stopSession()
        except:
            pass
        LOG.info("###===--- LibrarySync Stopped ---===###")
