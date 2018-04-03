# -*- coding: utf-8 -*-
###############################################################################
from logging import getLogger
from threading import Thread
import Queue
from random import shuffle

import xbmc
from xbmcvfs import exists

from utils import window, settings, unix_timestamp, thread_methods, \
    create_actor_db_index, dialog, log_time, playlist_xsp, language as lang, \
    unix_date_to_kodi, reset, try_decode, delete_playlists, delete_nodes, \
    try_encode, compare_version
import downloadutils
import itemtypes
import plexdb_functions as plexdb
import kodidb_functions as kodidb
import userclient
import videonodes
import json_rpc as js
import variables as v

from PlexFunctions import GetPlexMetadata, GetAllPlexLeaves, scrobble, \
    GetPlexSectionResults, GetPlexKeyNumber, GetPMSStatus, get_plex_sections, \
    GetAllPlexChildren
import PlexAPI
from library_sync.get_metadata import Threaded_Get_Metadata
from library_sync.process_metadata import Threaded_Process_Metadata
import library_sync.sync_info as sync_info
from library_sync.fanart import Process_Fanart_Thread
import music
import state

###############################################################################

log = getLogger("PLEX."+__name__)

###############################################################################


@thread_methods(add_suspends=['SUSPEND_LIBRARY_THREAD', 'STOP_SYNC'])
class LibrarySync(Thread):
    """
    """
    def __init__(self):
        self.itemsToProcess = []
        self.sessionKeys = {}
        self.fanartqueue = Queue.Queue()
        if settings('FanartTV') == 'true':
            self.fanartthread = Process_Fanart_Thread(self.fanartqueue)
        # How long should we wait at least to process new/changed PMS items?
        self.user = userclient.UserClient()
        self.vnodes = videonodes.VideoNodes()
        self.xbmcplayer = xbmc.Player()
        self.installSyncDone = settings('SyncInstallRunDone') == 'true'
        # Show sync dialog even if user deactivated?
        self.force_dialog = True
        Thread.__init__(self)

    def showKodiNote(self, message, icon="plex"):
        """
        Shows a Kodi popup, if user selected to do so. Pass message in unicode
        or string

        icon:   "plex": shows Plex icon
                "error": shows Kodi error icon
        """
        if self.xbmcplayer.isPlaying():
            # Don't show any dialog if media is playing
            return
        if state.SYNC_DIALOG is not True and self.force_dialog is not True:
            return
        if icon == "plex":
            dialog('notification',
                   heading='{plex}',
                   message=message,
                   icon='{plex}',
                   sound=False)
        elif icon == "error":
            dialog('notification',
                   heading='{plex}',
                   message=message,
                   icon='{error}')

    def syncPMStime(self):
        """
        PMS does not provide a means to get a server timestamp. This is a work-
        around.

        In general, everything saved to Kodi shall be in Kodi time.

        Any info with a PMS timestamp is in Plex time, naturally
        """
        log.info('Synching time with PMS server')
        # Find a PMS item where we can toggle the view state to enforce a
        # change in lastViewedAt

        # Get all Plex libraries
        sections = get_plex_sections()
        try:
            sections.attrib
        except AttributeError:
            log.error("Error download PMS views, abort syncPMStime")
            return False

        plexId = None
        for mediatype in (v.PLEX_TYPE_MOVIE,
                          v.PLEX_TYPE_SHOW,
                          v.PLEX_TYPE_ARTIST):
            if plexId is not None:
                break
            for view in sections:
                if plexId is not None:
                    break
                if not view.attrib['type'] == mediatype:
                    continue
                libraryId = view.attrib['key']
                items = GetAllPlexLeaves(libraryId)
                if items in (None, 401):
                    log.error("Could not download section %s"
                              % view.attrib['key'])
                    continue
                for item in items:
                    if item.attrib.get('viewCount') is not None:
                        # Don't want to mess with items that have playcount>0
                        continue
                    if item.attrib.get('viewOffset') is not None:
                        # Don't mess with items with a resume point
                        continue
                    plexId = item.attrib.get('ratingKey')
                    log.info('Found an item to sync with: %s' % plexId)
                    break

        if plexId is None:
            log.error("Could not find an item to sync time with")
            log.error("Aborting PMS-Kodi time sync")
            return False

        # Get the Plex item's metadata
        xml = GetPlexMetadata(plexId)
        if xml in (None, 401):
            log.error("Could not download metadata, aborting time sync")
            return False

        timestamp = xml[0].attrib.get('lastViewedAt')
        if timestamp is None:
            timestamp = xml[0].attrib.get('updatedAt')
            log.debug('Using items updatedAt=%s' % timestamp)
            if timestamp is None:
                timestamp = xml[0].attrib.get('addedAt')
                log.debug('Using items addedAt=%s' % timestamp)
                if timestamp is None:
                    timestamp = 0
                    log.debug('No timestamp; using 0')

        # Set the timer
        koditime = unix_timestamp()
        # Toggle watched state
        scrobble(plexId, 'watched')
        # Let the PMS process this first!
        xbmc.sleep(1000)
        # Get PMS items to find the item we just changed
        items = GetAllPlexLeaves(libraryId, lastViewedAt=timestamp)
        # Toggle watched state back
        scrobble(plexId, 'unwatched')
        if items in (None, 401):
            log.error("Could not download metadata, aborting time sync")
            return False

        plextime = None
        for item in items:
            if item.attrib['ratingKey'] == plexId:
                plextime = item.attrib.get('lastViewedAt')
                break

        if plextime is None:
            log.error('Could not get lastViewedAt - aborting')
            return False

        # Calculate time offset Kodi-PMS
        state.KODI_PLEX_TIME_OFFSET = float(koditime) - float(plextime)
        settings('kodiplextimeoffset', value=str(state.KODI_PLEX_TIME_OFFSET))
        log.info("Time offset Koditime - Plextime in seconds: %s"
                 % str(state.KODI_PLEX_TIME_OFFSET))
        return True

    def initializeDBs(self):
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
        # Create an index for actors to speed up sync
        create_actor_db_index()

    @log_time
    def fullSync(self, repair=False):
        """
        repair=True: force sync EVERY item
        """
        # Reset our keys
        self.sessionKeys = {}
        # self.compare == False: we're syncing EVERY item
        # True: we're syncing only the delta, e.g. different checksum
        self.compare = not repair

        self.new_items_only = True
        # This will also update playstates and userratings!
        log.info('Running fullsync for NEW PMS items with repair=%s' % repair)
        if self._fullSync() is False:
            return False
        self.new_items_only = False
        # This will NOT update playstates and userratings!
        log.info('Running fullsync for CHANGED PMS items with repair=%s'
                 % repair)
        if self._fullSync() is False:
            return False
        return True

    def _fullSync(self):
        if self.new_items_only is True:
            # Set views. Abort if unsuccessful
            if not self.maintainViews():
                return False
            # Delete all existing resume points first
            with kodidb.GetKodiDB('video') as kodi_db:
                # Setup the paths for addon-paths (even when using direct paths)
                kodi_db.setup_path_table()

        process = {
            'movies': self.PlexMovies,
            'tvshows': self.PlexTVShows,
        }
        if state.ENABLE_MUSIC:
            process['music'] = self.PlexMusic

        # Do the processing
        for itemtype in process:
            if (self.stopped() or
                    self.suspended() or
                    not process[itemtype]()):
                return False

        # Let kodi update the views in any case, since we're doing a full sync
        xbmc.executebuiltin('UpdateLibrary(video)')
        if state.ENABLE_MUSIC:
            xbmc.executebuiltin('UpdateLibrary(music)')

        window('plex_initialScan', clear=True)
        if window('plex_scancrashed') == 'true':
            # Show warning if itemtypes.py crashed at some point
            dialog('ok', heading='{plex}', line1=lang(39408))
            window('plex_scancrashed', clear=True)
        elif window('plex_scancrashed') == '401':
            window('plex_scancrashed', clear=True)
            if state.PMS_STATUS not in ('401', 'Auth'):
                # Plex server had too much and returned ERROR
                dialog('ok', heading='{plex}', line1=lang(39409))
        return True

    def processView(self, folderItem, kodi_db, plex_db, totalnodes):
        vnodes = self.vnodes
        folder = folderItem.attrib
        mediatype = folder['type']
        # Only process supported formats
        if mediatype not in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW,
                             v.PLEX_TYPE_ARTIST, v.PLEX_TYPE_PHOTO):
            return totalnodes

        # Prevent duplicate for nodes of the same type
        nodes = self.nodes[mediatype]
        # Prevent duplicate for playlists of the same type
        playlists = self.playlists[mediatype]
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
            log.info("Creating viewid: %s in Plex database." % folderid)
            tagid = kodi_db.createTag(foldername)
            # Create playlist for the video library
            if (foldername not in playlists and
                    mediatype in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)):
                playlist_xsp(mediatype, foldername, folderid, viewtype)
                playlists.append(foldername)
            # Create the video node
            if (foldername not in nodes and
                    mediatype != v.PLEX_TYPE_ARTIST):
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
            log.info(' '.join((
                "Found viewid: %s" % folderid,
                "viewname: %s" % current_viewname,
                "viewtype: %s" % current_viewtype,
                "tagid: %s" % current_tagid)))

            # Remove views that are still valid to delete rest later
            try:
                self.old_views.remove(folderid)
            except ValueError:
                # View was just created, nothing to remove
                pass

            # View was modified, update with latest info
            if current_viewname != foldername:
                log.info("viewid: %s new viewname: %s"
                         % (folderid, foldername))
                tagid = kodi_db.createTag(foldername)

                # Update view with new info
                plex_db.updateView(foldername, tagid, folderid)

                if mediatype != "artist":
                    if plex_db.getView_byName(current_viewname) is None:
                        # The tag could be a combined view. Ensure there's
                        # no other tags with the same name before deleting
                        # playlist.
                        playlist_xsp(mediatype,
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
                    if (foldername not in playlists and mediatype in
                            (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)):
                        playlist_xsp(mediatype,
                                    foldername,
                                    folderid,
                                    viewtype)
                        playlists.append(foldername)
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
                    kodi_db.updateTag(
                        current_tagid, tagid, item[0], current_viewtype[:-1])
            else:
                # Validate the playlist exists or recreate it
                if mediatype != v.PLEX_TYPE_ARTIST:
                    if (foldername not in playlists and mediatype in
                            (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)):
                        playlist_xsp(mediatype,
                                    foldername,
                                    folderid,
                                    viewtype)
                        playlists.append(foldername)
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

    def maintainViews(self):
        """
        Compare the views to Plex
        """
        if state.DIRECT_PATHS is True and state.ENABLE_MUSIC is True:
            # Will reboot Kodi is new library detected
            music.excludefromscan_music_folders()

        self.views = []
        vnodes = self.vnodes

        # Get views
        sections = get_plex_sections()
        try:
            sections.attrib
        except AttributeError:
            log.error("Error download PMS views, abort maintainViews")
            return False

        # For whatever freaking reason, .copy() or dict() does NOT work?!?!?!
        self.nodes = {
            v.PLEX_TYPE_MOVIE: [],
            v.PLEX_TYPE_SHOW: [],
            v.PLEX_TYPE_ARTIST: [],
            v.PLEX_TYPE_PHOTO: []
        }
        self.playlists = {
            v.PLEX_TYPE_MOVIE: [],
            v.PLEX_TYPE_SHOW: [],
            v.PLEX_TYPE_ARTIST: [],
            v.PLEX_TYPE_PHOTO: []
        }
        self.sorted_views = []

        for view in sections:
            itemType = view.attrib['type']
            if (itemType in
                    (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW, v.PLEX_TYPE_PHOTO)):
                self.sorted_views.append(view.attrib['title'])
        log.debug('Sorted views: %s' % self.sorted_views)

        # total nodes for window properties
        vnodes.clearProperties()
        totalnodes = len(self.sorted_views)

        with plexdb.Get_Plex_DB() as plex_db:
            # Backup old views to delete them later, if needed (at the end
            # of this method, only unused views will be left in oldviews)
            self.old_views = plex_db.getViews()
            with kodidb.GetKodiDB('video') as kodi_db:
                for folderItem in sections:
                    totalnodes = self.processView(folderItem,
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
        window('Plex.nodes.total', str(totalnodes))

        # Get rid of old items (view has been deleted on Plex side)
        if self.old_views:
            self.delete_views()
        # update views for all:
        with plexdb.Get_Plex_DB() as plex_db:
            self.views = plex_db.getAllViewInfo()
        log.info("Finished processing views. Views saved: %s" % self.views)
        return True

    def delete_views(self):
        log.info("Removing views: %s" % self.old_views)
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

        dialog('notification',
               heading='{plex}',
               message=lang(30052),
               icon='{plex}',
               sound=False)
        for item in delete_movies:
            with itemtypes.Movies() as movie:
                movie.remove(item['plex_id'])
        for item in delete_tv:
            with itemtypes.TVShows() as tv:
                tv.remove(item['plex_id'])
        # And for the music DB:
        for item in delete_music:
            with itemtypes.Music() as music:
                music.remove(item['plex_id'])

    def GetUpdatelist(self, xml, itemType, method, viewName, viewId,
                      get_children=False):
        """
        THIS METHOD NEEDS TO BE FAST! => e.g. no API calls

        Adds items to self.updatelist as well as self.allPlexElementsId dict

        Input:
            xml:                    PMS answer for section items
            itemType:               'Movies', 'TVShows', ...
            method:                 Method name to be called with this itemtype
                                    see itemtypes.py
            viewName:               Name of the Plex view (e.g. 'My TV shows')
            viewId:                 Id/Key of Plex library (e.g. '1')
            get_children:           will get Plex children of the item if True,
                                    e.g. for music albums

        Output: self.updatelist, self.allPlexElementsId
            self.updatelist         APPENDED(!!) list itemids (Plex Keys as
                                    as received from API.plex_id())
            One item in this list is of the form:
                'itemId': xxx,
                'itemType': 'Movies','TVShows', ...
                'method': 'add_update', 'add_updateSeason', ...
                'viewName': xxx,
                'viewId': xxx,
                'title': xxx
                'mediaType': xxx, e.g. 'movie', 'episode'

            self.allPlexElementsId      APPENDED(!!) dict
                = {itemid: checksum}
        """
        if self.new_items_only is True:
            # Only process Plex items that Kodi does not already have in lib
            for item in xml:
                itemId = item.attrib.get('ratingKey')
                if not itemId:
                    # Skipping items 'title=All episodes' without a 'ratingKey'
                    continue
                self.allPlexElementsId[itemId] = "K%s%s" % \
                    (itemId, item.attrib.get('updatedAt', ''))
                if itemId not in self.allKodiElementsId:
                    self.updatelist.append({
                        'itemId': itemId,
                        'itemType': itemType,
                        'method': method,
                        'viewName': viewName,
                        'viewId': viewId,
                        'title': item.attrib.get('title', 'Missing Title'),
                        'mediaType': item.attrib.get('type'),
                        'get_children': get_children
                    })
            return
        elif self.compare:
            # Only process the delta - new or changed items
            for item in xml:
                itemId = item.attrib.get('ratingKey')
                if not itemId:
                    # Skipping items 'title=All episodes' without a 'ratingKey'
                    continue
                plex_checksum = ("K%s%s"
                                 % (itemId, item.attrib.get('updatedAt', '')))
                self.allPlexElementsId[itemId] = plex_checksum
                kodi_checksum = self.allKodiElementsId.get(itemId)
                # Only update if movie is not in Kodi or checksum is
                # different
                if kodi_checksum != plex_checksum:
                    self.updatelist.append({
                        'itemId': itemId,
                        'itemType': itemType,
                        'method': method,
                        'viewName': viewName,
                        'viewId': viewId,
                        'title': item.attrib.get('title', 'Missing Title'),
                        'mediaType': item.attrib.get('type'),
                        'get_children': get_children
                    })
        else:
            # Initial or repair sync: get all Plex movies
            for item in xml:
                itemId = item.attrib.get('ratingKey')
                if not itemId:
                    # Skipping items 'title=All episodes' without a 'ratingKey'
                    continue
                self.allPlexElementsId[itemId] = "K%s%s" \
                    % (itemId, item.attrib.get('updatedAt', ''))
                self.updatelist.append({
                    'itemId': itemId,
                    'itemType': itemType,
                    'method': method,
                    'viewName': viewName,
                    'viewId': viewId,
                    'title': item.attrib.get('title', 'Missing Title'),
                    'mediaType': item.attrib.get('type'),
                    'get_children': get_children
                })

    def GetAndProcessXMLs(self, itemType):
        """
        Downloads all XMLs for itemType (e.g. Movies, TV-Shows). Processes them
        by then calling itemtypes.<itemType>()

        Input:
            itemType:               'Movies', 'TVShows', ...
            self.updatelist
            showProgress            If False, NEVER shows sync progress
        """
        # Some logging, just in case.
        log.debug("self.updatelist: %s" % self.updatelist)
        itemNumber = len(self.updatelist)
        if itemNumber == 0:
            return

        # Run through self.updatelist, get XML metadata per item
        # Initiate threads
        log.info("Starting sync threads")
        getMetadataQueue = Queue.Queue()
        processMetadataQueue = Queue.Queue(maxsize=100)
        # To keep track
        sync_info.GET_METADATA_COUNT = 0
        sync_info.PROCESS_METADATA_COUNT = 0
        sync_info.PROCESSING_VIEW_NAME = ''
        # Populate queue: GetMetadata
        for updateItem in self.updatelist:
            getMetadataQueue.put(updateItem)
        # Spawn GetMetadata threads for downloading
        threads = []
        for i in range(min(state.SYNC_THREAD_NUMBER, itemNumber)):
            thread = Threaded_Get_Metadata(getMetadataQueue,
                                           processMetadataQueue)
            thread.setDaemon(True)
            thread.start()
            threads.append(thread)
        log.info("%s download threads spawned" % len(threads))
        # Spawn one more thread to process Metadata, once downloaded
        thread = Threaded_Process_Metadata(processMetadataQueue,
                                           itemType)
        thread.setDaemon(True)
        thread.start()
        threads.append(thread)
        # Start one thread to show sync progress ONLY for new PMS items
        if self.new_items_only is True and (state.SYNC_DIALOG is True or
                                            self.force_dialog is True):
            thread = sync_info.Threaded_Show_Sync_Info(itemNumber, itemType)
            thread.setDaemon(True)
            thread.start()
            threads.append(thread)

        # Wait until finished
        getMetadataQueue.join()
        processMetadataQueue.join()
        # Kill threads
        log.info("Waiting to kill threads")
        for thread in threads:
            # Threads might already have quit by themselves (e.g. Kodi exit)
            try:
                thread.stop()
            except AttributeError:
                pass
        log.debug("Stop sent to all threads")
        # Wait till threads are indeed dead
        for thread in threads:
            try:
                thread.join(1.0)
            except:
                pass
        log.info("Sync threads finished")
        if (settings('FanartTV') == 'true' and
                itemType in ('Movies', 'TVShows')):
            for item in self.updatelist:
                if item['mediaType'] in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW):
                    self.fanartqueue.put({
                        'plex_id': item['itemId'],
                        'plex_type': item['mediaType'],
                        'refresh': False
                    })
        self.updatelist = []

    @log_time
    def PlexMovies(self):
        # Initialize
        self.allPlexElementsId = {}

        itemType = 'Movies'

        views = [x for x in self.views if x['itemtype'] == v.KODI_TYPE_MOVIE]
        log.info("Processing Plex %s. Libraries: %s" % (itemType, views))

        self.allKodiElementsId = {}
        if self.compare:
            with plexdb.Get_Plex_DB() as plex_db:
                # Get movies from Plex server
                # Pull the list of movies and boxsets in Kodi
                try:
                    self.allKodiElementsId = dict(
                        plex_db.checksum(v.PLEX_TYPE_MOVIE))
                except ValueError:
                    self.allKodiElementsId = {}

        # PROCESS MOVIES #####
        self.updatelist = []
        for view in views:
            if self.installSyncDone is not True:
                state.PATH_VERIFIED = False
            if self.stopped() or self.suspended():
                return False
            # Get items per view
            viewId = view['id']
            viewName = view['name']
            all_plexmovies = GetPlexSectionResults(viewId, args=None)
            if all_plexmovies is None:
                log.info("Couldnt get section items, aborting for view.")
                continue
            elif all_plexmovies == 401:
                return False
            # Populate self.updatelist and self.allPlexElementsId
            self.GetUpdatelist(all_plexmovies,
                               itemType,
                               'add_update',
                               viewName,
                               viewId)
        self.GetAndProcessXMLs(itemType)
        # Update viewstate for EVERY item
        for view in views:
            if self.stopped() or self.suspended():
                return False
            self.PlexUpdateWatched(view['id'], itemType)

        # PROCESS DELETES #####
        if self.compare:
            # Manual sync, process deletes
            with itemtypes.Movies() as Movie:
                for kodimovie in self.allKodiElementsId:
                    if kodimovie not in self.allPlexElementsId:
                        Movie.remove(kodimovie)
        log.info("%s sync is finished." % itemType)
        return True

    def PlexUpdateWatched(self, viewId, itemType,
                          lastViewedAt=None, updatedAt=None):
        """
        Updates plex elements' view status ('watched' or 'unwatched') and
        also updates resume times.
        This is done by downloading one XML for ALL elements with viewId
        """
        if self.new_items_only is False:
            # Only do this once for fullsync: the first run where new items are
            # added to Kodi
            return
        xml = GetAllPlexLeaves(viewId,
                               lastViewedAt=lastViewedAt,
                               updatedAt=updatedAt)
        # Return if there are no items in PMS reply - it's faster
        try:
            xml[0].attrib
        except (TypeError, AttributeError, IndexError):
            log.error('Error updating watch status. Could not get viewId: '
                      '%s of itemType %s with lastViewedAt: %s, updatedAt: '
                      '%s' % (viewId, itemType, lastViewedAt, updatedAt))
            return

        if itemType in ('Movies', 'TVShows'):
            self.updateKodiVideoLib = True
        elif itemType in ('Music'):
            self.updateKodiMusicLib = True

        itemMth = getattr(itemtypes, itemType)
        with itemMth() as method:
            method.updateUserdata(xml)

    @log_time
    def PlexTVShows(self):
        # Initialize
        self.allPlexElementsId = {}
        itemType = 'TVShows'

        views = [x for x in self.views if x['itemtype'] == 'show']
        log.info("Media folders for %s: %s" % (itemType, views))

        self.allKodiElementsId = {}
        if self.compare:
            with plexdb.Get_Plex_DB() as plex:
                # Pull the list of TV shows already in Kodi
                for kind in (v.PLEX_TYPE_SHOW,
                             v.PLEX_TYPE_SEASON,
                             v.PLEX_TYPE_EPISODE):
                    try:
                        elements = dict(plex.checksum(kind))
                        self.allKodiElementsId.update(elements)
                    # Yet empty/not yet synched
                    except ValueError:
                        pass

        # PROCESS TV Shows #####
        self.updatelist = []
        for view in views:
            if self.installSyncDone is not True:
                state.PATH_VERIFIED = False
            if self.stopped() or self.suspended():
                return False
            # Get items per view
            viewId = view['id']
            viewName = view['name']
            allPlexTvShows = GetPlexSectionResults(viewId)
            if allPlexTvShows is None:
                log.error("Error downloading show xml for view %s" % viewId)
                continue
            elif allPlexTvShows == 401:
                return False
            # Populate self.updatelist and self.allPlexElementsId
            self.GetUpdatelist(allPlexTvShows,
                               itemType,
                               'add_update',
                               viewName,
                               viewId)
            log.debug("Analyzed view %s with ID %s" % (viewName, viewId))

        # COPY for later use
        allPlexTvShowsId = self.allPlexElementsId.copy()

        # Process self.updatelist
        self.GetAndProcessXMLs(itemType)
        log.debug("GetAndProcessXMLs completed for tv shows")

        # PROCESS TV Seasons #####
        # Cycle through tv shows
        for tvShowId in allPlexTvShowsId:
            if self.stopped() or self.suspended():
                return False
            # Grab all seasons to tvshow from PMS
            seasons = GetAllPlexChildren(tvShowId)
            if seasons is None:
                log.error("Error download season xml for show %s" % tvShowId)
                continue
            elif seasons == 401:
                return False
            # Populate self.updatelist and self.allPlexElementsId
            self.GetUpdatelist(seasons,
                               itemType,
                               'add_updateSeason',
                               viewName,
                               viewId)
            log.debug("Analyzed all seasons of TV show with Plex Id %s"
                      % tvShowId)

        # Process self.updatelist
        self.GetAndProcessXMLs(itemType)
        log.debug("GetAndProcessXMLs completed for seasons")

        # PROCESS TV Episodes #####
        # Cycle through tv shows
        for view in views:
            if self.stopped() or self.suspended():
                return False
            # Grab all episodes to tvshow from PMS
            episodes = GetAllPlexLeaves(view['id'])
            if episodes is None:
                log.error("Error downloading episod xml for view %s"
                          % view.get('name'))
                continue
            elif episodes == 401:
                return False
            # Populate self.updatelist and self.allPlexElementsId
            self.GetUpdatelist(episodes,
                               itemType,
                               'add_updateEpisode',
                               viewName,
                               viewId)
            log.debug("Analyzed all episodes of TV show with Plex Id %s"
                      % view['id'])

        # Process self.updatelist
        self.GetAndProcessXMLs(itemType)
        log.debug("GetAndProcessXMLs completed for episodes")
        # Refresh season info
        # Cycle through tv shows
        with itemtypes.TVShows() as TVshow:
            for tvShowId in allPlexTvShowsId:
                XMLtvshow = GetPlexMetadata(tvShowId)
                if XMLtvshow is None or XMLtvshow == 401:
                    log.error('Could not download XMLtvshow')
                    continue
                TVshow.refreshSeasonEntry(XMLtvshow, tvShowId)
        log.debug("Season info refreshed")

        # Update viewstate:
        for view in views:
            if self.stopped() or self.suspended():
                return False
            self.PlexUpdateWatched(view['id'], itemType)

        if self.compare:
            # Manual sync, process deletes
            with itemtypes.TVShows() as TVShow:
                for kodiTvElement in self.allKodiElementsId:
                    if kodiTvElement not in self.allPlexElementsId:
                        TVShow.remove(kodiTvElement)
        log.info("%s sync is finished." % itemType)
        return True

    @log_time
    def PlexMusic(self):
        itemType = 'Music'

        views = [x for x in self.views if x['itemtype'] == v.PLEX_TYPE_ARTIST]
        log.info("Media folders for %s: %s" % (itemType, views))

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
            if self.stopped() or self.suspended():
                return False
            log.debug("Start processing music %s" % kind)
            self.allKodiElementsId = {}
            self.allPlexElementsId = {}
            self.updatelist = []
            if self.ProcessMusic(views,
                                 kind,
                                 urlArgs[kind],
                                 methods[kind]) is False:
                return False
            log.debug("Processing of music %s done" % kind)
            self.GetAndProcessXMLs(itemType)
            log.debug("GetAndProcessXMLs for music %s completed" % kind)

        # Update viewstate for EVERY item
        for view in views:
            if self.stopped() or self.suspended():
                return False
            self.PlexUpdateWatched(view['id'], itemType)

        # reset stuff
        self.allKodiElementsId = {}
        self.allPlexElementsId = {}
        self.updatelist = []
        log.info("%s sync is finished." % itemType)
        return True

    def ProcessMusic(self, views, kind, urlArgs, method):
        # For albums, we need to look at the album's songs simultaneously
        get_children = True if kind == v.PLEX_TYPE_ALBUM else False
        # Get a list of items already existing in Kodi db
        if self.compare:
            with plexdb.Get_Plex_DB() as plex_db:
                # Pull the list of items already in Kodi
                try:
                    elements = dict(plex_db.checksum(kind))
                    self.allKodiElementsId.update(elements)
                # Yet empty/nothing yet synched
                except ValueError:
                    pass
        for view in views:
            if self.installSyncDone is not True:
                state.PATH_VERIFIED = False
            if self.stopped() or self.suspended():
                return False
            # Get items per view
            itemsXML = GetPlexSectionResults(view['id'], args=urlArgs)
            if itemsXML is None:
                log.error("Error downloading xml for view %s" % view['id'])
                continue
            elif itemsXML == 401:
                return False
            # Populate self.updatelist and self.allPlexElementsId
            self.GetUpdatelist(itemsXML,
                               'Music',
                               method,
                               view['name'],
                               view['id'],
                               get_children=get_children)
        if self.compare:
            # Manual sync, process deletes
            with itemtypes.Music() as Music:
                for itemid in self.allKodiElementsId:
                    if itemid not in self.allPlexElementsId:
                        Music.remove(itemid)

    def processMessage(self, message):
        """
        processes json.loads() messages from websocket. Triage what we need to
        do with "process_" methods
        """
        if message['type'] == 'playing':
            try:
                self.process_playing(message['PlaySessionStateNotification'])
            except KeyError:
                log.error('Received invalid PMS message for playstate: %s'
                          % message)
        elif message['type'] == 'timeline':
            try:
                self.process_timeline(message['TimelineEntry'])
            except (KeyError, ValueError):
                log.error('Received invalid PMS message for timeline: %s'
                          % message)
        elif message['type'] == 'activity':
            try:
                self.process_activity(message['ActivityNotification'])
            except KeyError:
                log.error('Received invalid PMS message for activity: %s'
                          % message)

    def multi_delete(self, liste, deleteListe):
        """
        Deletes the list items of liste at the positions in deleteListe
        (which can be in any arbitrary order)
        """
        indexes = sorted(deleteListe, reverse=True)
        for index in indexes:
            del liste[index]
        return liste

    def processItems(self):
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
        self.videoLibUpdate = False
        self.musicLibUpdate = False
        now = unix_timestamp()
        deleteListe = []
        for i, item in enumerate(self.itemsToProcess):
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
                if successful and settings('FanartTV') == 'true':
                    if item['type'] in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW):
                        self.fanartqueue.put({
                            'plex_id': item['ratingKey'],
                            'plex_type': item['type'],
                            'refresh': False
                        })
            if successful is True:
                deleteListe.append(i)
            else:
                # Safety net if we can't process an item
                item['attempt'] += 1
                if item['attempt'] > 3:
                    log.error('Repeatedly could not process item %s, abort'
                              % item)
                    deleteListe.append(i)

        # Get rid of the items we just processed
        if len(deleteListe) > 0:
            self.itemsToProcess = self.multi_delete(
                self.itemsToProcess, deleteListe)
        # Let Kodi know of the change
        if self.videoLibUpdate is True:
            log.info("Doing Kodi Video Lib update")
            xbmc.executebuiltin('UpdateLibrary(video)')
        if self.musicLibUpdate is True:
            log.info("Doing Kodi Music Lib update")
            xbmc.executebuiltin('UpdateLibrary(music)')

    def process_newitems(self, item):
        xml = GetPlexMetadata(item['ratingKey'])
        try:
            mediatype = xml[0].attrib['type']
        except (IndexError, KeyError, TypeError):
            log.error('Could not download metadata for %s' % item['ratingKey'])
            return False
        log.debug("Processing new/updated PMS item: %s" % item['ratingKey'])
        viewtag = xml.attrib.get('librarySectionTitle')
        viewid = xml.attrib.get('librarySectionID')
        if mediatype == v.PLEX_TYPE_MOVIE:
            self.videoLibUpdate = True
            with itemtypes.Movies() as movie:
                movie.add_update(xml[0],
                                 viewtag=viewtag,
                                 viewid=viewid)
        elif mediatype == v.PLEX_TYPE_EPISODE:
            self.videoLibUpdate = True
            with itemtypes.TVShows() as show:
                show.add_updateEpisode(xml[0],
                                       viewtag=viewtag,
                                       viewid=viewid)
        elif mediatype == v.PLEX_TYPE_SONG:
            self.musicLibUpdate = True
            with itemtypes.Music() as music:
                music.add_updateSong(xml[0],
                                     viewtag=viewtag,
                                     viewid=viewid)
        return True

    def process_deleteditems(self, item):
        if item['type'] == v.PLEX_TYPE_MOVIE:
            log.debug("Removing movie %s" % item['ratingKey'])
            self.videoLibUpdate = True
            with itemtypes.Movies() as movie:
                movie.remove(item['ratingKey'])
        elif item['type'] in (v.PLEX_TYPE_SHOW,
                              v.PLEX_TYPE_SEASON,
                              v.PLEX_TYPE_EPISODE):
            log.debug("Removing episode/season/show with plex id %s",
                      item['ratingKey'])
            self.videoLibUpdate = True
            with itemtypes.TVShows() as show:
                show.remove(item['ratingKey'])
        elif item['type'] in (v.PLEX_TYPE_ARTIST,
                              v.PLEX_TYPE_ALBUM,
                              v.PLEX_TYPE_SONG):
            log.debug("Removing song/album/artist %s" % item['ratingKey'])
            self.musicLibUpdate = True
            with itemtypes.Music() as music:
                music.remove(item['ratingKey'])
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
            if status == 9:
                # Immediately and always process deletions (as the PMS will
                # send additional message with other codes)
                self.itemsToProcess.append({
                    'state': status,
                    'type': typus,
                    'ratingKey': str(item['itemID']),
                    'timestamp': unix_timestamp(),
                    'attempt': 0
                })
            elif typus in (v.PLEX_TYPE_MOVIE,
                           v.PLEX_TYPE_EPISODE,
                           v.PLEX_TYPE_SONG) and status == 5:
                plex_id = str(item['itemID'])
                # Have we already added this element for processing?
                for existingItem in self.itemsToProcess:
                    if existingItem['ratingKey'] == plex_id:
                        break
                else:
                    # Haven't added this element to the queue yet
                    self.itemsToProcess.append({
                        'state': status,
                        'type': typus,
                        'ratingKey': plex_id,
                        'timestamp': unix_timestamp(),
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
            plex_id = GetPlexKeyNumber(item['Activity']['Context']['key'])[1]
            if plex_id == '':
                # Likely a Plex id like /library/metadata/3/children
                continue
            # We're only looking at existing elements - have we synced yet?
            with plexdb.Get_Plex_DB() as plex_db:
                kodi_info = plex_db.getItem_byId(plex_id)
            if kodi_info is None:
                log.debug('Plex id %s not synced yet - skipping' % plex_id)
                continue
            # Have we already added this element?
            for existingItem in self.itemsToProcess:
                if existingItem['ratingKey'] == plex_id:
                    break
            else:
                # Haven't added this element to the queue yet
                self.itemsToProcess.append({
                    'state': None,  # Don't need a state here
                    'type': kodi_info[5],
                    'ratingKey': plex_id,
                    'timestamp': unix_timestamp(),
                    'attempt': 0
                })

    def process_playing(self, data):
        """
        Someone (not necessarily the user signed in) is playing something some-
        where
        """
        for item in data:
            status = item['state']
            if status == 'buffering':
                # Drop buffering messages immediately
                continue
            plex_id = item['ratingKey']
            skip = False
            for pid in (0, 1, 2):
                if plex_id == state.PLAYER_STATES[pid]['plex_id']:
                    # Kodi is playing this item - no need to set the playstate
                    skip = True
            if skip:
                continue
            sessionKey = item['sessionKey']
            # Do we already have a sessionKey stored?
            if sessionKey not in self.sessionKeys:
                with plexdb.Get_Plex_DB() as plex_db:
                    kodi_info = plex_db.getItem_byId(plex_id)
                if kodi_info is None:
                    # Item not (yet) in Kodi library
                    continue
                if settings('plex_serverowned') == 'false':
                    # Not our PMS, we are not authorized to get the sessions
                    # On the bright side, it must be us playing :-)
                    self.sessionKeys[sessionKey] = {}
                else:
                    # PMS is ours - get all current sessions
                    self.sessionKeys.update(GetPMSStatus(state.PLEX_TOKEN))
                    log.debug('Updated current sessions. They are: %s',
                              self.sessionKeys)
                    if sessionKey not in self.sessionKeys:
                        log.info('Session key %s still unknown! Skip '
                                 'playstate update', sessionKey)
                        continue
                # Attach Kodi info to the session
                self.sessionKeys[sessionKey]['kodi_id'] = kodi_info[0]
                self.sessionKeys[sessionKey]['file_id'] = kodi_info[1]
                self.sessionKeys[sessionKey]['kodi_type'] = kodi_info[4]
            session = self.sessionKeys[sessionKey]
            if settings('plex_serverowned') != 'false':
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
                    log.debug('Our username %s, userid %s did not match '
                              'the session username %s with userid %s',
                              state.PLEX_USERNAME,
                              state.PLEX_USER_ID,
                              session['username'],
                              session['userId'])
                    continue
            # Get an up-to-date XML from the PMS because PMS will NOT directly
            # tell us: duration of item viewCount
            if session.get('duration') is None:
                xml = GetPlexMetadata(plex_id)
                if xml in (None, 401):
                    log.error('Could not get up-to-date xml for item %s',
                              plex_id)
                    continue
                api = PlexAPI.API(xml[0])
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
                log.error('Could not mark playstate for %s and session %s',
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
            log.debug('Update playstate for user %s with id %s for plex id %s',
                      state.PLEX_USERNAME, state.PLEX_USER_ID, plex_id)
            item_fkt = getattr(itemtypes,
                               v.ITEMTYPE_FROM_KODITYPE[session['kodi_type']])
            with item_fkt() as fkt:
                fkt.updatePlaystate(mark_played,
                                    session['viewCount'],
                                    resume,
                                    session['duration'],
                                    session['file_id'],
                                    unix_date_to_kodi(unix_timestamp()))

    def fanartSync(self, refresh=False):
        """
        Checks all Plex movies and TV shows whether they still need fanart

        refresh=True        Force refresh all external fanart
        """
        items = []
        with plexdb.Get_Plex_DB() as plex_db:
            for plex_type in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW):
                items.extend(plex_db.itemsByType(plex_type))
        # Shuffle the list to not always start out identically
        shuffle(items)
        for item in items:
            self.fanartqueue.put({
                'plex_id': item['plex_id'],
                'plex_type': item['plex_type'],
                'refresh': refresh
            })

    def triage_lib_scans(self):
        """
        Decides what to do if state.RUN_LIB_SCAN has been set. E.g. manually
        triggered full or repair syncs
        """
        if state.RUN_LIB_SCAN in ("full", "repair"):
            log.info('Full library scan requested, starting')
            window('plex_dbScan', value="true")
            state.DB_SCAN = True
            if state.RUN_LIB_SCAN == "full":
                self.fullSync()
            else:
                self.fullSync(repair=True)
            window('plex_dbScan', clear=True)
            state.DB_SCAN = False
            # Full library sync finished
            self.showKodiNote(lang(39407))
        # Reset views was requested from somewhere else
        elif state.RUN_LIB_SCAN == "views":
            log.info('Refresh playlist and nodes requested, starting')
            window('plex_dbScan', value="true")
            state.DB_SCAN = True
            # First remove playlists
            delete_playlists()
            # Remove video nodes
            delete_nodes()
            # Kick off refresh
            if self.maintainViews() is True:
                # Ran successfully
                log.info("Refresh playlists/nodes completed")
                # "Plex playlists/nodes refreshed"
                self.showKodiNote(lang(39405))
            else:
                # Failed
                log.error("Refresh playlists/nodes failed")
                # "Plex playlists/nodes refresh failed"
                self.showKodiNote(lang(39406),
                                  icon="error")
            window('plex_dbScan', clear=True)
            state.DB_SCAN = False
        elif state.RUN_LIB_SCAN == 'fanart':
            # Only look for missing fanart (No)
            # or refresh all fanart (Yes)
            self.fanartSync(refresh=dialog(
                'yesno',
                heading='{plex}',
                line1=lang(39223),
                nolabel=lang(39224),
                yeslabel=lang(39225)))
        elif state.RUN_LIB_SCAN == 'textures':
            state.DB_SCAN = True
            window('plex_dbScan', value="true")
            import artwork
            artwork.Artwork().fullTextureCacheSync()
            window('plex_dbScan', clear=True)
            state.DB_SCAN = False
        else:
            raise NotImplementedError('Library scan not defined: %s'
                                      % state.RUN_LIB_SCAN)
        # Reset
        state.RUN_LIB_SCAN = None

    def run(self):
        try:
            self.run_internal()
        except Exception as e:
            state.DB_SCAN = False
            window('plex_dbScan', clear=True)
            log.error('LibrarySync thread crashed. Error message: %s' % e)
            import traceback
            log.error("Traceback:\n%s" % traceback.format_exc())
            # Library sync thread has crashed
            dialog('ok', heading='{plex}', line1=lang(39400))
            raise

    def run_internal(self):
        # Re-assign handles to have faster calls
        stopped = self.stopped
        suspended = self.suspended
        installSyncDone = self.installSyncDone
        fullSync = self.fullSync
        processMessage = self.processMessage
        processItems = self.processItems
        lastSync = 0
        lastTimeSync = 0
        lastProcessing = 0
        oneDay = 60*60*24

        # Link to Websocket queue
        queue = state.WEBSOCKET_QUEUE

        startupComplete = False
        self.views = []

        log.info("---===### Starting LibrarySync ###===---")

        # Ensure that DBs exist if called for very first time
        self.initializeDBs()

        if settings('FanartTV') == 'true':
            self.fanartthread.start()

        while not stopped():

            # In the event the server goes offline
            while suspended():
                # Set in service.py
                if stopped():
                    # Abort was requested while waiting. We should exit
                    log.info("###===--- LibrarySync Stopped ---===###")
                    return
                xbmc.sleep(1000)

            if state.KODI_DB_CHECKED is False and installSyncDone:
                # Install sync was already done, don't force-show dialogs
                self.force_dialog = False
                # Verify the validity of the database
                currentVersion = settings('dbCreatedWithVersion')
                if not compare_version(currentVersion, v.MIN_DB_VERSION):
                    log.warn("Db version out of date: %s minimum version "
                             "required: %s", currentVersion, v.MIN_DB_VERSION)
                    # DB out of date. Proceed to recreate?
                    resp = dialog('yesno',
                                  heading=lang(29999),
                                  line1=lang(39401))
                    if not resp:
                        log.warn("Db version out of date! USER IGNORED!")
                        # PKC may not work correctly until reset
                        dialog('ok',
                               heading='{plex}',
                               line1=lang(29999) + lang(39402))
                    else:
                        reset()
                    break
                state.KODI_DB_CHECKED = True

            if not startupComplete:
                # Also runs when first installed
                # Verify the video database can be found
                videoDb = v.DB_VIDEO_PATH
                if not exists(try_encode(videoDb)):
                    # Database does not exists
                    log.error("The current Kodi version is incompatible "
                              "to know which Kodi versions are supported.")
                    log.error('Current Kodi version: %s' % try_decode(
                        xbmc.getInfoLabel('System.BuildVersion')))
                    # "Current Kodi version is unsupported, cancel lib sync"
                    dialog('ok', heading='{plex}', line1=lang(39403))
                    break
                # Run start up sync
                state.DB_SCAN = True
                window('plex_dbScan', value="true")
                log.info("Db version: %s" % settings('dbCreatedWithVersion'))
                lastTimeSync = unix_timestamp()
                # Initialize time offset Kodi - PMS
                self.syncPMStime()
                lastSync = unix_timestamp()
                if settings('FanartTV') == 'true':
                    # Start getting additional missing artwork
                    with plexdb.Get_Plex_DB() as plex_db:
                        missing_fanart = plex_db.get_missing_fanart()
                        log.info('Trying to get %s additional fanart'
                                 % len(missing_fanart))
                        for item in missing_fanart:
                            self.fanartqueue.put({
                                'plex_id': item['plex_id'],
                                'plex_type': item['plex_type'],
                                'refresh': True
                            })
                log.info('Refreshing video nodes and playlists now')
                delete_playlists()
                delete_nodes()
                log.info("Initial start-up full sync starting")
                xbmc.executebuiltin('InhibitIdleShutdown(true)')
                librarySync = fullSync()
                xbmc.executebuiltin('InhibitIdleShutdown(false)')
                window('plex_dbScan', clear=True)
                state.DB_SCAN = False
                if librarySync:
                    log.info("Initial start-up full sync successful")
                    startupComplete = True
                    settings('SyncInstallRunDone', value="true")
                    settings("dbCreatedWithVersion", v.ADDON_VERSION)
                    installSyncDone = True
                    self.force_dialog = False
                else:
                    log.error("Initial start-up full sync unsuccessful")

            # Currently no db scan, so we can start a new scan
            elif state.DB_SCAN is False:
                # Full scan was requested from somewhere else, e.g. userclient
                if state.RUN_LIB_SCAN is not None:
                    # Force-show dialogs since they are user-initiated
                    self.force_dialog = True
                    self.triage_lib_scans()
                    self.force_dialog = False
                    continue
                now = unix_timestamp()
                # Standard syncs - don't force-show dialogs
                self.force_dialog = False
                if (now - lastSync > state.FULL_SYNC_INTERVALL and
                        not self.xbmcplayer.isPlaying()):
                    lastSync = now
                    log.info('Doing scheduled full library scan')
                    state.DB_SCAN = True
                    window('plex_dbScan', value="true")
                    if fullSync() is False and not stopped():
                        log.error('Could not finish scheduled full sync')
                        self.force_dialog = True
                        self.showKodiNote(lang(39410),
                                          icon='error')
                        self.force_dialog = False
                    window('plex_dbScan', clear=True)
                    state.DB_SCAN = False
                    # Full library sync finished
                    self.showKodiNote(lang(39407))
                elif now - lastTimeSync > oneDay:
                    lastTimeSync = now
                    log.info('Starting daily time sync')
                    state.DB_SCAN = True
                    window('plex_dbScan', value="true")
                    self.syncPMStime()
                    window('plex_dbScan', clear=True)
                    state.DB_SCAN = False
                elif not state.BACKGROUND_SYNC_DISABLED:
                    # Check back whether we should process something
                    # Only do this once every while (otherwise, potentially
                    # many screen refreshes lead to flickering)
                    if now - lastProcessing > 5:
                        lastProcessing = now
                        processItems()
                    # See if there is a PMS message we need to handle
                    try:
                        message = queue.get(block=False)
                    except Queue.Empty:
                        xbmc.sleep(100)
                        continue
                    # Got a message from PMS; process it
                    else:
                        processMessage(message)
                        queue.task_done()
                        # NO sleep!
                        continue
                else:
                    # Still sleep if backgroundsync disabled
                    xbmc.sleep(100)

            xbmc.sleep(100)

        # doUtils could still have a session open due to interrupted sync
        try:
            downloadutils.DownloadUtils().stopSession()
        except:
            pass
        log.info("###===--- LibrarySync Stopped ---===###")
