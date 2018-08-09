#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PKC Kodi Monitoring implementation
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from json import loads
from threading import Thread
import copy
import xbmc
from xbmcgui import Window

from . import plexdb_functions as plexdb
from . import kodidb_functions as kodidb
from . import utils
from . import plex_functions as PF
from .downloadutils import DownloadUtils as DU
from . import playback
from . import initialsetup
from . import playqueue as PQ
from . import json_rpc as js
from . import playlist_func as PL
from . import state
from . import variables as v

###############################################################################

LOG = getLogger('PLEX.kodimonitor')

# settings: window-variable
WINDOW_SETTINGS = {
    'plex_restricteduser': 'plex_restricteduser',
    'force_transcode_pix': 'plex_force_transcode_pix'
}

# settings: state-variable (state.py)
# Need to use getattr and setattr!
STATE_SETTINGS = {
    'dbSyncIndicator': 'SYNC_DIALOG',
    'remapSMB': 'REMAP_PATH',
    'remapSMBmovieOrg': 'remapSMBmovieOrg',
    'remapSMBmovieNew': 'remapSMBmovieNew',
    'remapSMBtvOrg': 'remapSMBtvOrg',
    'remapSMBtvNew': 'remapSMBtvNew',
    'remapSMBmusicOrg': 'remapSMBmusicOrg',
    'remapSMBmusicNew': 'remapSMBmusicNew',
    'remapSMBphotoOrg': 'remapSMBphotoOrg',
    'remapSMBphotoNew': 'remapSMBphotoNew',
    'enableMusic': 'ENABLE_MUSIC',
    'forceReloadSkinOnPlaybackStop': 'FORCE_RELOAD_SKIN',
    'fetch_pms_item_number': 'FETCH_PMS_ITEM_NUMBER',
    'imageSyncNotifications': 'IMAGE_SYNC_NOTIFICATIONS',
    'syncSpecificPlexPlaylists': 'SYNC_SPECIFIC_PLEX_PLAYLISTS',
    'syncSpecificKodiPlaylists': 'SYNC_SPECIFIC_KODI_PLAYLISTS'
}

###############################################################################


class KodiMonitor(xbmc.Monitor):
    """
    PKC implementation of the Kodi Monitor class. Invoke only once.
    """
    def __init__(self):
        self.xbmcplayer = xbmc.Player()
        self._already_slept = False
        self.hack_replay = None
        xbmc.Monitor.__init__(self)
        for playerid in state.PLAYER_STATES:
            state.PLAYER_STATES[playerid] = copy.deepcopy(state.PLAYSTATE)
            state.OLD_PLAYER_STATES[playerid] = copy.deepcopy(state.PLAYSTATE)
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
        changed = False
        # Reset the window variables from the settings variables
        for settings_value, window_value in WINDOW_SETTINGS.iteritems():
            if utils.window(window_value) != utils.settings(settings_value):
                changed = True
                LOG.debug('PKC window settings changed: %s is now %s',
                          settings_value, utils.settings(settings_value))
                utils.window(window_value, value=utils.settings(settings_value))
        # Reset the state variables in state.py
        for settings_value, state_name in STATE_SETTINGS.iteritems():
            new = utils.settings(settings_value)
            if new == 'true':
                new = True
            elif new == 'false':
                new = False
            if getattr(state, state_name) != new:
                changed = True
                LOG.debug('PKC state settings %s changed from %s to %s',
                          settings_value, getattr(state, state_name), new)
                setattr(state, state_name, new)
                if state_name == 'FETCH_PMS_ITEM_NUMBER':
                    LOG.info('Requesting playlist/nodes refresh')
                    utils.plex_command('RUN_LIB_SCAN', 'views')
        # Special cases, overwrite all internal settings
        initialsetup.set_replace_paths()
        state.BACKGROUND_SYNC_DISABLED = utils.settings(
            'enableBackgroundSync') == 'false'
        state.FULL_SYNC_INTERVALL = int(utils.settings('fullSyncInterval')) * 60
        state.BACKGROUNDSYNC_SAFTYMARGIN = int(
            utils.settings('backgroundsync_saftyMargin'))
        state.SYNC_THREAD_NUMBER = int(utils.settings('syncThreadNumber'))
        state.SSL_CERT_PATH = utils.settings('sslcert') \
            if utils.settings('sslcert') != 'None' else None
        if changed is True:
            # Assume that the user changed the settings so that we can now find
            # the path to all media files
            state.STOP_SYNC = False
            state.PATH_VERIFIED = False

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
            state.SUSPEND_SYNC = True
            with state.LOCK_PLAYQUEUES:
                self.PlayBackStart(data)
        elif method == "Player.OnStop":
            # Should refresh our video nodes, e.g. on deck
            # xbmc.executebuiltin('ReloadSkin()')
            if (self.hack_replay and not data.get('end') and
                    self.hack_replay == data['item']):
                # Hack for add-on paths
                self.hack_replay = None
                with state.LOCK_PLAYQUEUES:
                    self._hack_addon_paths_replay_video()
            elif data.get('end'):
                if state.PKC_CAUSED_STOP is True:
                    state.PKC_CAUSED_STOP = False
                    LOG.debug('PKC caused this playback stop - ignoring')
                else:
                    with state.LOCK_PLAYQUEUES:
                        _playback_cleanup(ended=True)
            else:
                with state.LOCK_PLAYQUEUES:
                    _playback_cleanup()
            state.PKC_CAUSED_STOP_DONE = True
            state.SUSPEND_SYNC = False
        elif method == 'Playlist.OnAdd':
            with state.LOCK_PLAYQUEUES:
                self._playlist_onadd(data)
        elif method == 'Playlist.OnRemove':
            self._playlist_onremove(data)
        elif method == 'Playlist.OnClear':
            with state.LOCK_PLAYQUEUES:
                self._playlist_onclear(data)
        elif method == "VideoLibrary.OnUpdate":
            # Manually marking as watched/unwatched
            playcount = data.get('playcount')
            item = data.get('item')
            if playcount is None or item is None:
                return
            try:
                kodiid = item['id']
                item_type = item['type']
            except (KeyError, TypeError):
                LOG.info("Item is invalid for playstate update.")
                return
            # Send notification to the server.
            with plexdb.Get_Plex_DB() as plexcur:
                plex_dbitem = plexcur.getItem_byKodiId(kodiid, item_type)
            try:
                itemid = plex_dbitem[0]
            except TypeError:
                LOG.error("Could not find itemid in plex database for a "
                          "video library update")
            else:
                # notify the server
                if playcount > 0:
                    PF.scrobble(itemid, 'watched')
                else:
                    PF.scrobble(itemid, 'unwatched')
        elif method == "VideoLibrary.OnRemove":
            pass
        elif method == "System.OnSleep":
            # Connection is going to sleep
            LOG.info("Marking the server as offline. SystemOnSleep activated.")
            utils.window('plex_online', value="sleep")
        elif method == "System.OnWake":
            # Allow network to wake up
            xbmc.sleep(10000)
            utils.window('plex_online', value="false")
        elif method == "GUI.OnScreensaverDeactivated":
            if utils.settings('dbSyncScreensaver') == "true":
                xbmc.sleep(5000)
                utils.plex_command('RUN_LIB_SCAN', 'full')
        elif method == "System.OnQuit":
            LOG.info('Kodi OnQuit detected - shutting down')
            state.STOP_PKC = True

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
        old = state.OLD_PLAYER_STATES[1]
        kwargs = {
            'plex_id': old['plex_id'],
            'plex_type': old['plex_type'],
            'path': old['file'],
            'resolve': False
        }
        thread = Thread(target=playback.playback_triage, kwargs=kwargs)
        thread.start()

    def _playlist_onadd(self, data):
        """
        Called if an item is added to a Kodi playlist. Example data dict:
        {
            u'item': {
                u'type': u'movie',
                u'id': 2},
            u'playlistid': 1,
            u'position': 0
        }
        Will NOT be called if playback initiated by Kodi widgets
        """
        if 'id' not in data['item']:
            return
        old = state.OLD_PLAYER_STATES[data['playlistid']]
        if (not state.DIRECT_PATHS and
                data['position'] == 0 and data['playlistid'] == 1 and
                not PQ.PLAYQUEUES[data['playlistid']].items and
                data['item']['type'] == old['kodi_type'] and
                data['item']['id'] == old['kodi_id']):
            self.hack_replay = data['item']

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
        playqueue = PQ.PLAYQUEUES[data['playlistid']]
        if not playqueue.is_pkc_clear():
            playqueue.pkc_edit = True
            playqueue.clear(kodi=False)
        else:
            LOG.debug('Detected PKC clear - ignoring')

    def _get_ids(self, kodi_id, kodi_type, path):
        """
        Returns the tuple (plex_id, plex_type) or (None, None)
        """
        # No Kodi id returned by Kodi, even if there is one. Ex: Widgets
        plex_id = None
        plex_type = None
        # If using direct paths and starting playback from a widget
        if not kodi_id and kodi_type and path:
            kodi_id, _ = kodidb.kodiid_from_filename(path, kodi_type)
        if kodi_id:
            with plexdb.Get_Plex_DB() as plex_db:
                plex_dbitem = plex_db.getItem_byKodiId(kodi_id, kodi_type)
            try:
                plex_id = plex_dbitem[0]
                plex_type = plex_dbitem[2]
            except TypeError:
                # No plex id, hence item not in the library. E.g. clips
                pass
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
            xbmc.sleep(1000)
        try:
            json_item = js.get_item(playerid)
        except KeyError:
            LOG.debug('No playing item returned by Kodi')
            return None, None, None
        LOG.debug('Kodi playing item properties: %s', json_item)
        return (json_item.get('id'),
                json_item.get('type'),
                json_item.get('file'))

    def PlayBackStart(self, data):
        """
        Called whenever playback is started. Example data:
        {
            u'item': {u'type': u'movie', u'title': u''},
            u'player': {u'playerid': 1, u'speed': 1}
        }
        Unfortunately when using Widgets, Kodi doesn't tell us shit
        """
        self._already_slept = False
        # Get the type of media we're playing
        try:
            playerid = data['player']['playerid']
        except (TypeError, KeyError):
            LOG.info('Aborting playback report - item invalid for updates %s',
                     data)
            return
        if playerid == -1:
            # Kodi might return -1 for "last player"
            try:
                playerid = js.get_player_ids()[0]
            except IndexError:
                LOG.error('Could not retreive active player - aborting')
                return
        playqueue = PQ.PLAYQUEUES[playerid]
        info = js.get_player_props(playerid)
        if playqueue.kodi_playlist_playback:
            # Kodi will tell us the wrong position - of the playlist, not the
            # playqueue, when user starts playing from a playlist :-(
            pos = 0
            LOG.debug('Detected playback from a Kodi playlist')
        else:
            pos = info['position'] if info['position'] != -1 else 0
            LOG.debug('Detected position %s for %s', pos, playqueue)
        status = state.PLAYER_STATES[playerid]
        kodi_id = data.get('id')
        kodi_type = data.get('type')
        path = data.get('file')
        try:
            item = playqueue.items[pos]
        except IndexError:
            # PKC playqueue not yet initialized
            LOG.debug('Position %s not in PKC playqueue yet', pos)
            initialize = True
        else:
            if not kodi_id:
                kodi_id, kodi_type, path = self._json_item(playerid)
            if kodi_id and item.kodi_id:
                if item.kodi_id != kodi_id or item.kodi_type != kodi_type:
                    LOG.debug('Detected different Kodi id')
                    initialize = True
                else:
                    initialize = False
            else:
                # E.g. clips set-up previously with no Kodi DB entry
                if not path:
                    kodi_id, kodi_type, path = self._json_item(playerid)
                if item.file != path:
                    LOG.debug('Detected different path')
                    initialize = True
                else:
                    initialize = False
        if initialize:
            LOG.debug('Need to initialize Plex and PKC playqueue')
            if not kodi_id or not kodi_type:
                kodi_id, kodi_type, path = self._json_item(playerid)
            plex_id, plex_type = self._get_ids(kodi_id, kodi_type, path)
            if not plex_id:
                LOG.debug('No Plex id obtained - aborting playback report')
                state.PLAYER_STATES[playerid] = copy.deepcopy(state.PLAYSTATE)
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
        else:
            LOG.debug('No need to initialize playqueues')
            kodi_id = item.kodi_id
            kodi_type = item.kodi_type
            plex_id = item.plex_id
            plex_type = item.plex_type
            if playqueue.id:
                container_key = '/playQueues/%s' % playqueue.id
            else:
                container_key = '/library/metadata/%s' % plex_id
        # Remember that this player has been active
        state.ACTIVE_PLAYERS.add(playerid)
        status.update(info)
        LOG.debug('Set the Plex container_key to: %s', container_key)
        status['container_key'] = container_key
        status['file'] = path
        status['kodi_id'] = kodi_id
        status['kodi_type'] = kodi_type
        status['plex_id'] = plex_id
        status['plex_type'] = plex_type
        status['playmethod'] = item.playmethod
        status['playcount'] = item.playcount
        LOG.debug('Set the player state: %s', status)


@utils.thread_methods
class SpecialMonitor(Thread):
    """
    Detect the resume dialog for widgets.
    Could also be used to detect external players (see Emby implementation)
    """
    def run(self):
        LOG.info("----====# Starting Special Monitor #====----")
        # "Start from beginning", "Play from beginning"
        strings = (utils.try_encode(utils.lang(12021)),
                   utils.try_encode(utils.lang(12023)))
        while not self.stopped():
            if xbmc.getCondVisibility('Window.IsVisible(DialogContextMenu.xml)'):
                if xbmc.getInfoLabel('Control.GetLabel(1002)') in strings:
                    # Remember that the item IS indeed resumable
                    control = int(Window(10106).getFocusId())
                    state.RESUME_PLAYBACK = True if control == 1001 else False
                else:
                    # Different context menu is displayed
                    state.RESUME_PLAYBACK = False
            if xbmc.getCondVisibility('Window.IsVisible(MyVideoNav.xml)'):
                path = xbmc.getInfoLabel('container.folderpath')
                if (isinstance(path, str) and
                        path.startswith('special://profile/playlists')):
                    pass
                    # TODO: start polling PMS for playlist changes
                    # Optionally: poll PMS continuously with custom intervall
            xbmc.sleep(200)
        LOG.info("#====---- Special Monitor Stopped ----====#")


def _playback_cleanup(ended=False):
    """
    PKC cleanup after playback ends/is stopped. Pass ended=True if Kodi
    completely finished playing an item (because we will get and use wrong
    timing data otherwise)
    """
    LOG.debug('playback_cleanup called. Active players: %s',
              state.ACTIVE_PLAYERS)
    # We might have saved a transient token from a user flinging media via
    # Companion (if we could not use the playqueue to store the token)
    state.PLEX_TRANSIENT_TOKEN = None
    for playerid in state.ACTIVE_PLAYERS:
        status = state.PLAYER_STATES[playerid]
        # Remember the last played item later
        state.OLD_PLAYER_STATES[playerid] = copy.deepcopy(status)
        # Stop transcoding
        if status['playmethod'] == 'Transcode':
            LOG.debug('Tell the PMS to stop transcoding')
            DU().downloadUrl(
                '{server}/video/:/transcode/universal/stop',
                parameters={'session': v.PKC_MACHINE_IDENTIFIER})
        if playerid == 1:
            # Bookmarks might not be pickup up correctly, so let's do them
            # manually. Applies to addon paths, but direct paths might have
            # started playback via PMS
            _record_playstate(status, ended)
        # Reset the player's status
        state.PLAYER_STATES[playerid] = copy.deepcopy(state.PLAYSTATE)
    # As all playback has halted, reset the players that have been active
    state.ACTIVE_PLAYERS = set()
    LOG.debug('Finished PKC playback cleanup')


def _record_playstate(status, ended):
    if not status['plex_id']:
        LOG.debug('No Plex id found to record playstate for status %s', status)
        return
    with plexdb.Get_Plex_DB() as plex_db:
        kodi_db_item = plex_db.getItem_byId(status['plex_id'])
    if kodi_db_item is None:
        # Item not (yet) in Kodi library
        LOG.debug('No playstate update due to Plex id not found: %s', status)
        return
    totaltime = float(utils.kodi_time_to_millis(status['totaltime'])) / 1000
    if ended:
        progress = 0.99
        time = v.IGNORE_SECONDS_AT_START + 1
    else:
        time = float(utils.kodi_time_to_millis(status['time'])) / 1000
        try:
            progress = time / totaltime
        except ZeroDivisionError:
            progress = 0.0
        LOG.debug('Playback progress %s (%s of %s seconds)',
                  progress, time, totaltime)
    playcount = status['playcount']
    last_played = utils.unix_date_to_kodi(utils.unix_timestamp())
    if playcount is None:
        LOG.debug('playcount not found, looking it up in the Kodi DB')
        with kodidb.GetKodiDB('video') as kodi_db:
            playcount = kodi_db.get_playcount(kodi_db_item[1])
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
    with kodidb.GetKodiDB('video') as kodi_db:
        kodi_db.set_resume(kodi_db_item[1],
                           time,
                           totaltime,
                           playcount,
                           last_played,
                           status['plex_type'])
    # Hack to force "in progress" widget to appear if it wasn't visible before
    if (state.FORCE_RELOAD_SKIN and
            xbmc.getCondVisibility('Window.IsVisible(Home.xml)')):
        LOG.debug('Refreshing skin to update widgets')
        xbmc.executebuiltin('ReloadSkin()')
    thread = Thread(target=_clean_file_table)
    thread.setDaemon(True)
    thread.start()


def _clean_file_table():
    """
    If we associate a playing video e.g. pointing to plugin://... to an existing
    Kodi library item, Kodi will add an additional entry for this (additional)
    path plugin:// in the file table. This leads to all sorts of wierd behavior.
    This function tries for at most 5 seconds to clean the file table.
    """
    LOG.debug('Start cleaning Kodi files table')
    i = 0
    while i < 100 and not state.STOP_PKC:
        with kodidb.GetKodiDB('video') as kodi_db:
            files = kodi_db.obsolete_file_ids()
        if files:
            break
        i += 1
        xbmc.sleep(50)
    with kodidb.GetKodiDB('video') as kodi_db:
        for file_id in files:
            LOG.debug('Removing obsolete Kodi file_id %s', file_id)
            kodi_db.remove_file(file_id[0], remove_orphans=False)
    LOG.debug('Done cleaning up Kodi file table')
