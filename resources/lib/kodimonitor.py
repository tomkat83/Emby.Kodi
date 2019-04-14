#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PKC Kodi Monitoring implementation
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from json import loads
import copy

import xbmc
import xbmcgui

from .plex_db import PlexDB
from . import kodi_db
from .downloadutils import DownloadUtils as DU
from . import utils, timing, plex_functions as PF, playback
from . import json_rpc as js, playqueue as PQ, playlist_func as PL
from . import backgroundthread, app, variables as v

LOG = getLogger('PLEX.kodimonitor')

# "Start from beginning", "Play from beginning"
STRINGS = (utils.lang(12021).encode('utf-8'),
           utils.lang(12023).encode('utf-8'))


class MonitorError(Exception):
    """
    Exception we raise for all errors associated with xbmc.Monitor
    """
    pass


class KodiMonitor(xbmc.Monitor):
    """
    PKC implementation of the Kodi Monitor class. Invoke only once.
    """
    def __init__(self):
        self._already_slept = False
        self.hack_replay = None
        # Info to the currently playing item
        self.playerid = None
        self.playlistid = None
        self.playqueue = None
        for playerid in app.PLAYSTATE.player_states:
            app.PLAYSTATE.player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
            app.PLAYSTATE.old_player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
        xbmc.Monitor.__init__(self)
        LOG.info("Kodi monitor started.")

    def onScanStarted(self, library):
        """
        Will be called when Kodi starts scanning the library
        """
        LOG.debug("Kodi library scan %s running.", library)

    def onScanFinished(self, library):
        """
        Will be called when Kodi finished scanning the library
        """
        LOG.debug("Kodi library scan %s finished.", library)

    def onSettingsChanged(self):
        """
        Monitor the PKC settings for changes made by the user
        """
        LOG.debug('PKC settings change detected')
        # Assume that the user changed something so we can try to reconnect
        # app.APP.suspend = False
        # app.APP.resume_threads(block=False)

    def onNotification(self, sender, method, data):
        """
        Called when a bunch of different stuff happens on the Kodi side
        """
        if data:
            data = loads(data, 'utf-8')
            LOG.debug("Method: %s Data: %s", method, data)

        # Hack
        if not method == 'Player.OnStop':
            self.hack_replay = None

        if method == "Player.OnPlay":
            with app.APP.lock_playqueues:
                self.on_play(data)
        elif method == "Player.OnStop":
            # Should refresh our video nodes, e.g. on deck
            # xbmc.executebuiltin('ReloadSkin()')
            if (self.hack_replay and not data.get('end') and
                    self.hack_replay == data['item']):
                # Hack for add-on paths
                self.hack_replay = None
                with app.APP.lock_playqueues:
                    self._hack_addon_paths_replay_video()
            elif data.get('end'):
                with app.APP.lock_playqueues:
                    _playback_cleanup(ended=True)
            else:
                with app.APP.lock_playqueues:
                    _playback_cleanup()
        elif method == 'Playlist.OnAdd':
            if 'item' in data and data['item'].get('type') == v.KODI_TYPE_SHOW:
                # Hitting the "browse" button on tv show info dialog
                # Hence show the tv show directly
                xbmc.executebuiltin("Dialog.Close(all, true)")
                js.activate_window('videos',
                                   'videodb://tvshows/titles/%s/' % data['item']['id'])
            with app.APP.lock_playqueues:
                self._playlist_onadd(data)
        elif method == 'Playlist.OnRemove':
            self._playlist_onremove(data)
        elif method == 'Playlist.OnClear':
            with app.APP.lock_playqueues:
                self._playlist_onclear(data)
        elif method == "VideoLibrary.OnUpdate":
            # Manually marking as watched/unwatched
            playcount = data.get('playcount')
            item = data.get('item')
            if playcount is None or item is None:
                return
            try:
                kodi_id = item['id']
                kodi_type = item['type']
            except (KeyError, TypeError):
                LOG.info("Item is invalid for playstate update.")
                return
            # Send notification to the server.
            with PlexDB() as plexdb:
                db_item = plexdb.item_by_kodi_id(kodi_id, kodi_type)
            if not db_item:
                LOG.error("Could not find plex_id in plex database for a "
                          "video library update")
            else:
                # notify the server
                if playcount > 0:
                    PF.scrobble(db_item['plex_id'], 'watched')
                else:
                    PF.scrobble(db_item['plex_id'], 'unwatched')
        elif method == "VideoLibrary.OnRemove":
            pass
        elif method == "System.OnSleep":
            # Connection is going to sleep
            LOG.info("Marking the server as offline. SystemOnSleep activated.")
        elif method == "System.OnWake":
            # Allow network to wake up
            self.waitForAbort(10)
            app.CONN.online = False
        elif method == "GUI.OnScreensaverDeactivated":
            if utils.settings('dbSyncScreensaver') == "true":
                self.waitForAbort(5)
                app.SYNC.run_lib_scan = 'full'
        elif method == "System.OnQuit":
            LOG.info('Kodi OnQuit detected - shutting down')
            app.APP.stop_pkc = True

    @staticmethod
    def _hack_addon_paths_replay_video():
        """
        Hack we need for RESUMABLE items because Kodi lost the path of the
        last played item that is now being replayed (see playback.py's
        Player().play()) Also see playqueue.py _compare_playqueues()

        Needed if user re-starts the same video from the library using addon
        paths. (Video is only added to playqueue, then immediately stoppen.
        There is no playback initialized by Kodi.) Log excerpts:
          Method: Playlist.OnAdd Data:
              {u'item': {u'type': u'movie', u'id': 4},
               u'playlistid': 1,
               u'position': 0}
          Now we would hack!
          Method: Player.OnStop Data:
              {u'item': {u'type': u'movie', u'id': 4},
               u'end': False}
        (within the same micro-second!)
        """
        LOG.info('Detected re-start of playback of last item')
        old = app.PLAYSTATE.old_player_states[1]
        kwargs = {
            'plex_id': old['plex_id'],
            'plex_type': old['plex_type'],
            'path': old['file'],
            'resolve': False
        }
        task = backgroundthread.FunctionAsTask(playback.playback_triage,
                                               None,
                                               **kwargs)
        backgroundthread.BGThreader.addTasksToFront([task])

    def _playlist_onadd(self, data):
        '''
        Detect widget playback. Widget for some reason, use audio playlists.
        '''
        if data['position'] == 0:
            if data['playlistid'] == 0:
                app.PLAYSTATE.audioplaylist = True
            else:
                app.PLAYSTATE.audioplaylist = False
            self.playlistid = data['playlistid']
        if utils.window('plex.playlist.start') and data['position'] == int(utils.window('plex.playlist.start')) + 1:
            LOG.info('Playlist ready')
            utils.window('plex.playlist.ready', value='true')
            utils.window('plex.playlist.start', clear=True)

    def _playlist_onremove(self, data):
        """
        Called if an item is removed from a Kodi playlist. Example data dict:
        {
            u'playlistid': 1,
            u'position': 0
        }
        """
        pass

    def _playlist_onclear(self, data):
        """
        Called if a Kodi playlist is cleared. Example data dict:
        {
            u'playlistid': 1,
        }
        """
        if self.playlistid == data['playlistid']:
            LOG.debug('Resetting autoplay')
            app.PLAYSTATE.autoplay = False
        playqueue = PQ.PLAYQUEUES[data['playlistid']]
        if not playqueue.is_pkc_clear():
            playqueue.pkc_edit = True
            playqueue.clear(kodi=False)
        else:
            LOG.debug('Detected PKC clear - ignoring')

    @staticmethod
    def _get_ids(kodi_id, kodi_type, path):
        """
        Returns the tuple (plex_id, plex_type) or (None, None)
        """
        # No Kodi id returned by Kodi, even if there is one. Ex: Widgets
        plex_id = None
        plex_type = None
        # If using direct paths and starting playback from a widget
        if not kodi_id and kodi_type and path:
            kodi_id, _ = kodi_db.kodiid_from_filename(path, kodi_type)
        if kodi_id:
            with PlexDB() as plexdb:
                db_item = plexdb.item_by_kodi_id(kodi_id, kodi_type)
            if db_item:
                plex_id = db_item['plex_id']
                plex_type = db_item['plex_type']
        return plex_id, plex_type

    @staticmethod
    def _add_remaining_items_to_playlist(playqueue):
        """
        Adds all but the very first item of the Kodi playlist to the Plex
        playqueue
        """
        items = js.playlist_get_items(playqueue.playlistid)
        if not items:
            LOG.error('Could not retrieve Kodi playlist items')
            return
        # Remove first item
        items.pop(0)
        try:
            for i, item in enumerate(items):
                PL.add_item_to_plex_playqueue(playqueue, i + 1, kodi_item=item)
        except PL.PlaylistError:
            LOG.info('Could not build Plex playlist for: %s', items)

    def _json_item(self, playerid):
        """
        Uses JSON RPC to get the playing item's info and returns the tuple
            kodi_id, kodi_type, path
        or None each time if not found.
        """
        if not self._already_slept:
            # SLEEP before calling this for the first time just after playback
            # start as Kodi updates this info very late!! Might get previous
            # element otherwise
            self._already_slept = True
            self.waitForAbort(1)
        try:
            json_item = js.get_item(playerid)
        except KeyError:
            LOG.debug('No playing item returned by Kodi')
            return None, None, None
        LOG.debug('Kodi playing item properties: %s', json_item)
        return (json_item.get('id'),
                json_item.get('type'),
                json_item.get('file'))

    def _get_playerid(self, data):
        """
        Sets self.playerid with an int 0, 1 [or 2] or raises MonitorError
            0: usually video
            1: usually audio
        """
        try:
            self.playerid = data['player']['playerid']
        except (TypeError, KeyError):
            LOG.info('Aborting playback report - data invalid for updates: %s',
                     data)
            raise MonitorError()
        if self.playerid == -1:
            # Kodi might return -1 for "last player"
            try:
                self.playerid = js.get_player_ids()[0]
            except IndexError:
                LOG.error('Coud not get playerid for data: %s', data)
                raise MonitorError()

    def _check_playing_item(self, data):
        """
        Returns a PF.Playlist_Item() for the currently playing item
        Raises MonitorError or IndexError if we need to init the PKC playqueue
        """
        info = js.get_player_props(self.playerid)
        LOG.debug('Current info for player %s: %s', self.playerid, info)
        position = info['position'] if info['position'] != -1 else 0
        kodi_playlist = js.playlist_get_items(self.playerid)
        LOG.debug('Current Kodi playlist: %s', kodi_playlist)
        kodi_item = PL.playlist_item_from_kodi(kodi_playlist[position])
        if (position == 1 and
                len(kodi_playlist) == len(self.playqueue.items) + 1 and
                kodi_playlist[0].get('type') == 'unknown' and
                kodi_playlist[0].get('file') and
                kodi_playlist[0].get('file').startswith('http://127.0.0.1')):
            if kodi_item == self.playqueue.items[0]:
                # Delete the very first item that we used to start playback:
                # {
                #     u'title': u'',
                #     u'type': u'unknown',
                #     u'file': u'http://127.0.0.1:57578/plex/kodi/....',
                #     u'label': u''
                # }
                LOG.debug('Deleting the very first playqueue item')
                js.playlist_remove(self.playqueue.playlistid, 0)
                position = 0
            else:
                LOG.debug('Different item in PKC playlist: %s vs. %s',
                          self.playqueue.items[0], kodi_item)
                raise MonitorError()
        elif kodi_item != self.playqueue.items[position]:
            LOG.debug('Different playqueue items: %s vs. %s ',
                      kodi_item, self.playqueue.items[position])
            raise MonitorError()
        # Return the PKC playqueue item - contains more info
        return self.playqueue.items[position]

    def _load_playerstate(self, item):
        """
        Pass in a PF.Playlist_Item(). Will then set the currently playing
        state with app.PLAYSTATE.player_states[self.playerid]
        """
        if self.playqueue.id:
            container_key = '/playQueues/%s' % self.playqueue.id
        else:
            container_key = '/library/metadata/%s' % item.plex_id
        status = app.PLAYSTATE.player_states[self.playerid]
        # Remember that this player has been active
        app.PLAYSTATE.active_players.add(self.playerid)
        status.update(js.get_player_props(self.playerid))
        status['container_key'] = container_key
        status['file'] = item.file
        status['kodi_id'] = item.kodi_id
        status['kodi_type'] = item.kodi_type
        status['plex_id'] = item.plex_id
        status['plex_type'] = item.plex_type
        status['playmethod'] = item.playmethod
        status['playcount'] = item.playcount
        LOG.debug('Set player state for player %s: %s', self.playerid, status)

    def on_play(self, data):
        """
        Called whenever playback is started. Example data:
        {
            u'item': {u'type': u'movie', u'title': u''},
            u'player': {u'playerid': 1, u'speed': 1}
        }
        Unfortunately when using Widgets, Kodi doesn't tell us shit
        """
        # Some init
        self._already_slept = False
        self.playerid = None
        # Get the type of media we're playing
        try:
            self._get_playerid(data)
        except MonitorError:
            return
        self.playqueue = PQ.PLAYQUEUES[self.playerid]
        LOG.debug('Current PKC playqueue: %s', self.playqueue)
        item = None
        try:
            item = self._check_playing_item(data)
        except (MonitorError, IndexError):
            LOG.debug('Detected that we need to initialize the PKC playqueue')

        if not item:
            # Initialize the PKC playqueue
            # Yet TODO
            LOG.debug('Need to initialize Plex and PKC playqueue')
            if not kodi_id or not kodi_type:
                kodi_id, kodi_type, path = self._json_item(playerid)
            plex_id, plex_type = self._get_ids(kodi_id, kodi_type, path)
            if not plex_id:
                LOG.debug('No Plex id obtained - aborting playback report')
                app.PLAYSTATE.player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
                return
            item = PL.init_plex_playqueue(playqueue, plex_id=plex_id)
            item.file = path
            # Set the Plex container key (e.g. using the Plex playqueue)
            container_key = None
            if info['playlistid'] != -1:
                # -1 is Kodi's answer if there is no playlist
                container_key = PQ.PLAYQUEUES[playerid].id
            if container_key is not None:
                container_key = '/playQueues/%s' % container_key
            elif plex_id is not None:
                container_key = '/library/metadata/%s' % plex_id
        self._load_playerstate(item)


def _playback_cleanup(ended=False):
    """
    PKC cleanup after playback ends/is stopped. Pass ended=True if Kodi
    completely finished playing an item (because we will get and use wrong
    timing data otherwise)
    """
    LOG.debug('playback_cleanup called. Active players: %s',
              app.PLAYSTATE.active_players)
    # We might have saved a transient token from a user flinging media via
    # Companion (if we could not use the playqueue to store the token)
    app.CONN.plex_transient_token = None
    for playerid in app.PLAYSTATE.active_players:
        status = app.PLAYSTATE.player_states[playerid]
        # Remember the last played item later
        app.PLAYSTATE.old_player_states[playerid] = copy.deepcopy(status)
        # Stop transcoding
        if status['playmethod'] == 'Transcode':
            LOG.debug('Tell the PMS to stop transcoding')
            DU().downloadUrl(
                '{server}/video/:/transcode/universal/stop',
                parameters={'session': v.PKC_MACHINE_IDENTIFIER})
        if status['plex_type'] in v.PLEX_VIDEOTYPES:
            # Bookmarks are not be pickup up correctly, so let's do them
            # manually. Applies to addon paths, but direct paths might have
            # started playback via PMS
            _record_playstate(status, ended)
        # Reset the player's status
        app.PLAYSTATE.player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
    # As all playback has halted, reset the players that have been active
    app.PLAYSTATE.active_players = set()
    LOG.info('Finished PKC playback cleanup')


def _record_playstate(status, ended):
    if not status['plex_id']:
        LOG.debug('No Plex id found to record playstate for status %s', status)
        return
    if status['plex_type'] not in v.PLEX_VIDEOTYPES:
        LOG.debug('Not messing with non-video entries')
        return
    with PlexDB() as plexdb:
        db_item = plexdb.item_by_id(status['plex_id'], status['plex_type'])
    if not db_item:
        # Item not (yet) in Kodi library
        LOG.debug('No playstate update due to Plex id not found: %s', status)
        return
    totaltime = float(timing.kodi_time_to_millis(status['totaltime'])) / 1000
    if ended:
        progress = 0.99
        time = v.IGNORE_SECONDS_AT_START + 1
    else:
        time = float(timing.kodi_time_to_millis(status['time'])) / 1000
        try:
            progress = time / totaltime
        except ZeroDivisionError:
            progress = 0.0
        LOG.debug('Playback progress %s (%s of %s seconds)',
                  progress, time, totaltime)
    playcount = status['playcount']
    last_played = timing.kodi_now()
    if playcount is None:
        LOG.debug('playcount not found, looking it up in the Kodi DB')
        with kodi_db.KodiVideoDB() as kodidb:
            playcount = kodidb.get_playcount(db_item['kodi_fileid'])
        playcount = 0 if playcount is None else playcount
    if time < v.IGNORE_SECONDS_AT_START:
        LOG.debug('Ignoring playback less than %s seconds',
                  v.IGNORE_SECONDS_AT_START)
        # Annoying Plex bug - it'll reset an already watched video to unwatched
        playcount = None
        last_played = None
        time = 0
    elif progress >= v.MARK_PLAYED_AT:
        LOG.debug('Recording entirely played video since progress > %s',
                  v.MARK_PLAYED_AT)
        playcount += 1
        time = 0
    with kodi_db.KodiVideoDB() as kodidb:
        kodidb.set_resume(db_item['kodi_fileid'],
                          time,
                          totaltime,
                          playcount,
                          last_played)
        if 'kodi_fileid_2' in db_item and db_item['kodi_fileid_2']:
            # Dirty hack for our episodes
            kodidb.set_resume(db_item['kodi_fileid_2'],
                              time,
                              totaltime,
                              playcount,
                              last_played)
    # We might need to reconsider cleaning the file/path table in the future
    # _clean_file_table()
    # Update the current view to show e.g. an up-to-date progress bar and use
    # the latest resume point info
    if xbmc.getCondVisibility('Container.Content(musicvideos)'):
        # Prevent cursor from moving
        xbmc.executebuiltin('Container.Refresh')
    else:
        # Update widgets
        xbmc.executebuiltin('UpdateLibrary(video)')
        if xbmc.getCondVisibility('Window.IsMedia'):
            xbmc.executebuiltin('Container.Refresh')
    # Hack to force "in progress" widget to appear if it wasn't visible before
    if (app.APP.force_reload_skin and
            xbmc.getCondVisibility('Window.IsVisible(Home.xml)')):
        LOG.debug('Refreshing skin to update widgets')
        xbmc.executebuiltin('ReloadSkin()')


def _clean_file_table():
    """
    If we associate a playing video e.g. pointing to plugin://... to an existing
    Kodi library item, Kodi will add an additional entry for this (additional)
    path plugin:// in the file table. This leads to all sorts of wierd behavior.
    This function tries for at most 5 seconds to clean the file table.
    """
    LOG.debug('Start cleaning Kodi files table')
    # app.APP.monitor.waitForAbort(1)
    try:
        with kodi_db.KodiVideoDB() as kodidb:
            file_ids = list(kodidb.obsolete_file_ids())
            LOG.debug('Obsolete kodi file_ids: %s', file_ids)
            for file_id in file_ids:
                kodidb.remove_file(file_id)
    except utils.OperationalError:
        LOG.debug('Database was locked, unable to clean file table')
    else:
        LOG.debug('Done cleaning up Kodi file table')


class ContextMonitor(backgroundthread.KillableThread):
    """
    Detect the resume dialog for widgets. Could also be used to detect
    external players (see Emby implementation)

    Let's not register this thread because it won't quit due to
    xbmc.getCondVisibility
    It should still exit at some point due to xbmc.abortRequested
    """
    def run(self):
        LOG.info("----===## Starting ContextMonitor ##===----")
        # app.APP.register_thread(self)
        try:
            self._run()
        finally:
            # app.APP.deregister_thread(self)
            LOG.info("##===---- ContextMonitor Stopped ----===##")

    def _run(self):
        while not self.isCanceled():
            # The following function will block if called while PKC should
            # exit!
            if xbmc.getCondVisibility('Window.IsVisible(DialogContextMenu.xml)'):
                if xbmc.getInfoLabel('Control.GetLabel(1002)') in STRINGS:
                    # Remember that the item IS indeed resumable
                    control = int(xbmcgui.Window(10106).getFocusId())
                    app.PLAYSTATE.resume_playback = True if control == 1001 else False
                else:
                    # Different context menu is displayed
                    app.PLAYSTATE.resume_playback = None
            xbmc.sleep(100)
