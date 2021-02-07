#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PKC Kodi Monitoring implementation
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from json import loads
import copy
import json
import binascii

import xbmc

from .plex_api import API
from .plex_db import PlexDB
from . import kodi_db
from .downloadutils import DownloadUtils as DU
from . import utils, timing, plex_functions as PF
from . import json_rpc as js, playqueue as PQ, playlist_func as PL
from . import backgroundthread, app, variables as v

LOG = getLogger('PLEX.kodimonitor')


class KodiMonitor(xbmc.Monitor):
    """
    PKC implementation of the Kodi Monitor class. Invoke only once.
    """
    def __init__(self):
        self._already_slept = False
        xbmc.Monitor.__init__(self)
        for playerid in app.PLAYSTATE.player_states:
            app.PLAYSTATE.player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
            app.PLAYSTATE.old_player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
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

    def onNotification(self, sender, method, data):
        """
        Called when a bunch of different stuff happens on the Kodi side
        """
        if data:
            data = loads(data, 'utf-8')
            LOG.debug("Method: %s Data: %s", method, data)

        if method == "Player.OnPlay":
            with app.APP.lock_playqueues:
                self.PlayBackStart(data)
        elif method == "Player.OnStop":
            with app.APP.lock_playqueues:
                _playback_cleanup(ended=data.get('end'))
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
            _videolibrary_onupdate(data)
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
        elif method == 'Other.plugin.video.plexkodiconnect_play_action':
            self._start_next_episode(data)

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
        pass

    def _playlist_onremove(self, data):
        """
        Called if an item is removed from a Kodi playlist. Example data dict:
        {
            u'playlistid': 1,
            u'position': 0
        }
        """
        pass

    @staticmethod
    def _playlist_onclear(data):
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

    @staticmethod
    def _start_next_episode(data):
        """
        Used for the add-on Upnext to start playback of the next episode
        """
        LOG.info('Upnext: Start playback of the next episode')
        play_info = binascii.unhexlify(data[0])
        play_info = json.loads(play_info)
        app.APP.player.stop()
        handle = 'RunPlugin(%s)' % play_info.get('handle')
        xbmc.executebuiltin(handle.encode('utf-8'))

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
        kodi_id = data['item'].get('id') if 'item' in data else None
        kodi_type = data['item'].get('type') if 'item' in data else None
        path = data['item'].get('file') if 'item' in data else None
        if playerid == -1:
            # Kodi might return -1 for "last player"
            # Getting the playerid is really a PITA
            try:
                playerid = js.get_player_ids()[0]
            except IndexError:
                # E.g. Kodi 18 doesn't tell us anything useful
                if kodi_type in v.KODI_VIDEOTYPES:
                    playlist_type = v.KODI_TYPE_VIDEO_PLAYLIST
                elif kodi_type in v.KODI_AUDIOTYPES:
                    playlist_type = v.KODI_TYPE_AUDIO_PLAYLIST
                else:
                    LOG.error('Unexpected type %s, data %s', kodi_type, data)
                    return
                playerid = js.get_playlist_id(playlist_type)
                if not playerid:
                    LOG.error('Coud not get playerid for data %s', data)
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
        status = app.PLAYSTATE.player_states[playerid]
        try:
            item = playqueue.items[pos]
            LOG.debug('PKC playqueue item is: %s', item)
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
                if path == '':
                    LOG.debug('Detected empty path: aborting playback report')
                    return
                if item.file != path:
                    # Clips will get a new path
                    LOG.debug('Detected different path')
                    try:
                        tmp_plex_id = int(utils.REGEX_PLEX_ID.findall(path)[0])
                    except IndexError:
                        LOG.debug('No Plex id in path, need to init playqueue')
                        initialize = True
                    else:
                        if tmp_plex_id == item.plex_id:
                            LOG.debug('Detected different path for the same id')
                            initialize = False
                        else:
                            LOG.debug('Different Plex id, need to init playqueue')
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
                app.PLAYSTATE.player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
                return
            try:
                item = PL.init_plex_playqueue(playqueue, plex_id=plex_id)
            except PL.PlaylistError:
                LOG.info('Could not initialize the Plex playlist')
                return
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
        # Mechanik for Plex skip intro feature
        if utils.settings('enableSkipIntro') == 'true':
            api = API(item.xml)
            status['intro_markers'] = api.intro_markers()
        # Remember the currently playing item
        app.PLAYSTATE.item = item
        # Remember that this player has been active
        app.PLAYSTATE.active_players.add(playerid)
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
        try:
            status['external_player'] = app.APP.player.isExternalPlayer() == 1
        except AttributeError:
            # Kodi version < 17
            pass
        LOG.debug('Set the player state: %s', status)
        if not app.SYNC.direct_paths:
            _notify_upnext(item)


def _playback_cleanup(ended=False):
    """
    PKC cleanup after playback ends/is stopped. Pass ended=True if Kodi
    completely finished playing an item (because we will get and use wrong
    timing data otherwise)
    """
    LOG.debug('playback_cleanup called. Active players: %s',
              app.PLAYSTATE.active_players)
    if app.APP.skip_intro_dialog:
        app.APP.skip_intro_dialog.close()
        app.APP.skip_intro_dialog = None
    # We might have saved a transient token from a user flinging media via
    # Companion (if we could not use the playqueue to store the token)
    app.CONN.plex_transient_token = None
    for playerid in app.PLAYSTATE.active_players:
        status = app.PLAYSTATE.player_states[playerid]
        # Remember the last played item later
        app.PLAYSTATE.old_player_states[playerid] = copy.deepcopy(status)
        # Stop transcoding
        if status['playmethod'] == v.PLAYBACK_METHOD_TRANSCODE:
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
        app.PLAYSTATE.player_states[playerid] = copy.deepcopy(app.PLAYSTATE.template)
    # As all playback has halted, reset the players that have been active
    app.PLAYSTATE.active_players = set()
    app.PLAYSTATE.item = None
    utils.delete_temporary_subtitles()
    LOG.debug('Finished PKC playback cleanup')


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
    if status['external_player']:
        # video has either been entirely watched - or not.
        # "ended" won't work, need a workaround
        ended = _external_player_correct_plex_watch_count(db_item)
        if ended:
            progress = 0.99
            time = v.IGNORE_SECONDS_AT_START + 1
        else:
            progress = 0.0
            time = 0.0
    else:
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
    # Hack to force "in progress" widget to appear if it wasn't visible before
    if (app.APP.force_reload_skin and
            xbmc.getCondVisibility('Window.IsVisible(Home.xml)')):
        LOG.debug('Refreshing skin to update widgets')
        xbmc.executebuiltin('ReloadSkin()')
    task = backgroundthread.FunctionAsTask(_clean_file_table, None)
    backgroundthread.BGThreader.addTasksToFront([task])


def _external_player_correct_plex_watch_count(db_item):
    """
    Kodi won't safe playstate at all for external players

    There's currently no way to get a resumpoint if an external player is
    in use  We are just checking whether we should mark video as
    completely watched or completely unwatched (according to
    playcountminimumtime set in playercorefactory.xml)
    See https://kodi.wiki/view/External_players
    """
    with kodi_db.KodiVideoDB() as kodidb:
        playcount = kodidb.get_playcount(db_item['kodi_fileid'])
    LOG.debug('External player detected. Playcount: %s', playcount)
    PF.scrobble(db_item['plex_id'], 'watched' if playcount else 'unwatched')
    return True if playcount else False


def _clean_file_table():
    """
    If we associate a playing video e.g. pointing to plugin://... to an existing
    Kodi library item, Kodi will add an additional entry for this (additional)
    path plugin:// in the file table. This leads to all sorts of wierd behavior.
    This function tries for at most 5 seconds to clean the file table.
    """
    LOG.debug('Start cleaning Kodi files table')
    if app.APP.monitor.waitForAbort(2):
        # PKC should exit
        return
    try:
        with kodi_db.KodiVideoDB() as kodidb:
            obsolete_file_ids = list(kodidb.obsolete_file_ids())
            for file_id in obsolete_file_ids:
                LOG.debug('Removing obsolete Kodi file_id %s', file_id)
                kodidb.remove_file(file_id, remove_orphans=False)
    except utils.OperationalError:
        LOG.debug('Database was locked, unable to clean file table')
    else:
        LOG.debug('Done cleaning up Kodi file table')


def _next_episode(current_api):
    """
    Returns the xml for the next episode after the current one
    Returns None if something went wrong or there is no next episode
    """
    xml = PF.show_episodes(current_api.grandparent_id())
    if xml is None:
        return
    for counter, episode in enumerate(xml):
        api = API(episode)
        if api.plex_id == current_api.plex_id:
            break
    else:
        LOG.error('Did not find the episode with Plex id %s for show %s: %s',
                  current_api.plex_id, current_api.grandparent_id(),
                  current_api.grandparent_title())
        return
    try:
        next_api = API(xml[counter + 1])
    except IndexError:
        # Was the last episode
        return
    return next_api


def _complete_artwork_keys(info):
    """
    Make sure that the minimum set of keys is present in the info dict
    """
    for key in ('tvshow.poster',
                'tvshow.fanart',
                'tvshow.landscape',
                'tvshow.clearart',
                'tvshow.clearlogo',
                'thumb'):
        if key not in info['art']:
            info['art'][key] = ''


def _notify_upnext(item):
    """
    Signals to the Kodi add-on Upnext that there is another episode after this
    one.
    Needed for add-on paths in order to prevent crashes when Upnext does this
    by itself
    """
    if not item.plex_type == v.PLEX_TYPE_EPISODE:
        return
    this_api = API(item.xml)
    next_api = _next_episode(this_api)
    if next_api is None:
        return
    info = {}
    for key, api in (('current_episode', this_api),
                     ('next_episode', next_api)):
        info[key] = {
            'episodeid': api.plex_id,
            'tvshowid': api.grandparent_id(),
            'title': api.title(),
            'showtitle': api.grandparent_title(),
            'plot': api.plot(),
            'playcount': api.viewcount(),
            'season': api.season_number(),
            'episode': api.index(),
            'firstaired': api.year(),
            'rating': api.rating(),
            'art': api.artwork(kodi_id=api.kodi_id,
                               kodi_type=api.kodi_type,
                               full_artwork=True)
        }
        _complete_artwork_keys(info[key])
    info['play_info'] = {'handle': next_api.fullpath(force_addon=True)[0]}
    sender = v.ADDON_ID.encode('utf-8')
    method = 'upnext_data'.encode('utf-8')
    data = binascii.hexlify(json.dumps(info))
    data = '\\"[\\"{0}\\"]\\"'.format(data)
    xbmc.executebuiltin('NotifyAll(%s, %s, %s)' % (sender, method, data))


def _videolibrary_onupdate(data):
    """
    A specific Kodi library item has been updated. This seems to happen if the
    user marks an item as watched/unwatched or if playback of the item just
    stopped
    """
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
    if app.PLAYSTATE.item and kodi_id == app.PLAYSTATE.item.kodi_id and \
            kodi_type == app.PLAYSTATE.item.kodi_type:
        # Kodi updates an item immediately after playback. Hence we do NOT
        # increase or decrease the viewcount
        return
    # Send notification to the server.
    with PlexDB(lock=False) as plexdb:
        db_item = plexdb.item_by_kodi_id(kodi_id, kodi_type)
    if not db_item:
        LOG.error("Could not find plex_id in plex database for a "
                  "video library update")
        return
    # notify the server
    if playcount > 0:
        PF.scrobble(db_item['plex_id'], 'watched')
    else:
        PF.scrobble(db_item['plex_id'], 'unwatched')
