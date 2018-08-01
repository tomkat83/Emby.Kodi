#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Manages getting playstate from Kodi and sending it to the PMS as well as
subscribed Plex Companion clients.
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread

from ..downloadutils import DownloadUtils as DU
from .. import utils
from .. import state
from .. import variables as v
from .. import json_rpc as js
from .. import playqueue as PQ

###############################################################################
LOG = getLogger('PLEX.subscribers')
###############################################################################

# What is Companion controllable?
CONTROLLABLE = {
    v.PLEX_PLAYLIST_TYPE_VIDEO: 'playPause,stop,volume,shuffle,audioStream,'
        'subtitleStream,seekTo,skipPrevious,skipNext,'
        'stepBack,stepForward',
    v.PLEX_PLAYLIST_TYPE_AUDIO: 'playPause,stop,volume,shuffle,repeat,seekTo,'
        'skipPrevious,skipNext,stepBack,stepForward',
    v.PLEX_PLAYLIST_TYPE_PHOTO: 'playPause,stop,skipPrevious,skipNext'
}

STREAM_DETAILS = {
    'video': 'currentvideostream',
    'audio': 'currentaudiostream',
    'subtitle': 'currentsubtitle'
}

XML = ('%s<MediaContainer commandID="{command_id}" location="{location}">\n'
       '  <Timeline {%s}/>\n'
       '  <Timeline {%s}/>\n'
       '  <Timeline {%s}/>\n'
       '</MediaContainer>\n') % (v.XML_HEADER,
                                 v.PLEX_PLAYLIST_TYPE_VIDEO,
                                 v.PLEX_PLAYLIST_TYPE_AUDIO,
                                 v.PLEX_PLAYLIST_TYPE_PHOTO)

# Headers are different for Plex Companion - use these for PMS notifications
HEADERS_PMS = {
    'Connection': 'keep-alive',
    'Accept': 'text/plain, */*; q=0.01',
    'Accept-Language': 'en',
    'Accept-Encoding': 'gzip, deflate',
    'User-Agent': '%s %s (%s)' % (v.ADDON_NAME, v.ADDON_VERSION, v.PLATFORM)
}


def params_pms():
    """
    Returns the url parameters for communicating with the PMS
    """
    return {
        # 'X-Plex-Client-Capabilities': 'protocols=shoutcast,http-video;'
        #     'videoDecoders=h264{profile:high&resolution:2160&level:52};'
        #     'audioDecoders=mp3,aac,dts{bitrate:800000&channels:2},'
        #     'ac3{bitrate:800000&channels:2}',
        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
        'X-Plex-Device': v.PLATFORM,
        'X-Plex-Device-Name': v.DEVICENAME,
        # 'X-Plex-Device-Screen-Resolution': '1916x1018,1920x1080',
        'X-Plex-Model': 'unknown',
        'X-Plex-Platform': v.PLATFORM,
        'X-Plex-Platform-Version': 'unknown',
        'X-Plex-Product': v.ADDON_NAME,
        'X-Plex-Provider-Version': v.ADDON_VERSION,
        'X-Plex-Version': v.ADDON_VERSION,
        'hasMDE': '1',
        # 'X-Plex-Session-Identifier': ['vinuvirm6m20iuw9c4cx1dcx'],
    }


def headers_companion_client():
    """
    Headers are different for Plex Companion - use these for a Plex Companion
    client
    """
    return {
        'Content-Type': 'application/xml',
        'Connection': 'Keep-Alive',
        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
        'X-Plex-Device-Name': v.DEVICENAME,
        'X-Plex-Platform': v.PLATFORM,
        'X-Plex-Platform-Version': 'unknown',
        'X-Plex-Product': v.ADDON_NAME,
        'X-Plex-Version': v.ADDON_VERSION,
        'Accept-Encoding': 'gzip, deflate',
        'Accept-Language': 'en,*'
    }


def update_player_info(playerid):
    """
    Updates all player info for playerid [int] in state.py.
    """
    state.PLAYER_STATES[playerid].update(js.get_player_props(playerid))
    state.PLAYER_STATES[playerid]['volume'] = js.get_volume()
    state.PLAYER_STATES[playerid]['muted'] = js.get_muted()


class SubscriptionMgr(object):
    """
    Manages Plex companion subscriptions
    """
    def __init__(self, request_mgr, player):
        self.serverlist = []
        self.subscribers = {}
        self.info = {}
        self.server = ""
        self.protocol = "http"
        self.port = ""
        self.isplaying = False
        self.location = 'navigation'
        # In order to be able to signal a stop at the end
        self.last_params = {}
        self.lastplayers = {}
        # In order to signal a stop to Plex Web ONCE on playback stop
        self.stop_sent_to_web = True

        self.xbmcplayer = player
        self.request_mgr = request_mgr

    def _server_by_host(self, host):
        if len(self.serverlist) == 1:
            return self.serverlist[0]
        for server in self.serverlist:
            if (server.get('serverName') in host or
                    server.get('server') in host):
                return server
        return {}

    @staticmethod
    def _get_correct_position(info, playqueue):
        """
        Kodi tells us the PLAYLIST position, not PLAYQUEUE position, if the
        user initiated playback of a playlist
        """
        if playqueue.kodi_playlist_playback:
            position = 0
        else:
            position = info['position'] or 0
        return position

    def msg(self, players):
        """
        Returns a timeline xml as str
        (xml containing video, audio, photo player state)
        """
        self.isplaying = False
        self.location = 'navigation'
        answ = str(XML)
        timelines = {
            v.PLEX_PLAYLIST_TYPE_VIDEO: None,
            v.PLEX_PLAYLIST_TYPE_AUDIO: None,
            v.PLEX_PLAYLIST_TYPE_PHOTO: None
        }
        for typus in timelines:
            if players.get(v.KODI_PLAYLIST_TYPE_FROM_PLEX_PLAYLIST_TYPE[typus]) is None:
                timeline = {
                    'controllable': CONTROLLABLE[typus],
                    'type': typus,
                    'state': 'stopped'
                }
            else:
                timeline = self._timeline_dict(players[
                        v.KODI_PLAYLIST_TYPE_FROM_PLEX_PLAYLIST_TYPE[typus]],
                    typus)
            timelines[typus] = self._dict_to_xml(timeline)
        timelines.update({'command_id': '{command_id}',
                         'location': self.location})
        return answ.format(**timelines)

    @staticmethod
    def _dict_to_xml(dictionary):
        """
        Returns the string 'key1="value1" key2="value2" ...' for dictionary
        """
        answ = ''
        for key, value in dictionary.iteritems():
            answ += '%s="%s" ' % (key, value)
        return answ

    def _timeline_dict(self, player, ptype):
        with state.LOCK_PLAYQUEUES:
            playerid = player['playerid']
            info = state.PLAYER_STATES[playerid]
            playqueue = PQ.PLAYQUEUES[playerid]
            position = self._get_correct_position(info, playqueue)
            try:
                item = playqueue.items[position]
            except IndexError:
                # E.g. for direct path playback for single item
                return {
                    'controllable': CONTROLLABLE[ptype],
                    'type': ptype,
                    'state': 'stopped'
                }
            self.isplaying = True
            self.stop_sent_to_web = False
            if ptype in (v.PLEX_PLAYLIST_TYPE_VIDEO,
                         v.PLEX_PLAYLIST_TYPE_PHOTO):
                self.location = 'fullScreenVideo'
            pbmc_server = utils.window('pms_server')
            if pbmc_server:
                (self.protocol, self.server, self.port) = pbmc_server.split(':')
                self.server = self.server.replace('/', '')
            status = 'paused' if int(info['speed']) == 0 else 'playing'
            duration = utils.kodi_time_to_millis(info['totaltime'])
            shuffle = '1' if info['shuffled'] else '0'
            mute = '1' if info['muted'] is True else '0'
            answ = {
                'controllable': CONTROLLABLE[ptype],
                'protocol': self.protocol,
                'address': self.server,
                'port': self.port,
                'machineIdentifier': utils.window('plex_machineIdentifier'),
                'state': status,
                'type': ptype,
                'itemType': ptype,
                'time': utils.kodi_time_to_millis(info['time']),
                'duration': duration,
                'seekRange': '0-%s' % duration,
                'shuffle': shuffle,
                'repeat': v.PLEX_REPEAT_FROM_KODI_REPEAT[info['repeat']],
                'volume': info['volume'],
                'mute': mute,
                'mediaIndex': 0,  # Still to implement from here
                'partIndex': 0,
                'partCount': 1,
                'providerIdentifier': 'com.plexapp.plugins.library',
            }
            # Get the plex id from the PKC playqueue not info, as Kodi jumps to
            # next playqueue element way BEFORE kodi monitor onplayback is
            # called
            if item.plex_id:
                answ['key'] = '/library/metadata/%s' % item.plex_id
                answ['ratingKey'] = item.plex_id
            # PlayQueue stuff
            if info['container_key']:
                answ['containerKey'] = info['container_key']
            if (info['container_key'] is not None and
                    info['container_key'].startswith('/playQueues')):
                answ['playQueueID'] = playqueue.id
                answ['playQueueVersion'] = playqueue.version
                answ['playQueueItemID'] = item.id
            if playqueue.items[position].guid:
                answ['guid'] = item.guid
            # Temp. token set?
            if state.PLEX_TRANSIENT_TOKEN:
                answ['token'] = state.PLEX_TRANSIENT_TOKEN
            elif playqueue.plex_transient_token:
                answ['token'] = playqueue.plex_transient_token
            # Process audio and subtitle streams
            if ptype == v.PLEX_PLAYLIST_TYPE_VIDEO:
                strm_id = self._plex_stream_index(playerid, 'audio')
                if strm_id:
                    answ['audioStreamID'] = strm_id
                else:
                    LOG.error('We could not select a Plex audiostream')
                strm_id = self._plex_stream_index(playerid, 'video')
                if strm_id:
                    answ['videoStreamID'] = strm_id
                else:
                    LOG.error('We could not select a Plex videostream')
                if info['subtitleenabled']:
                    try:
                        strm_id = self._plex_stream_index(playerid, 'subtitle')
                    except KeyError:
                        # subtitleenabled can be True while currentsubtitle can
                        # still be {}
                        strm_id = None
                    if strm_id is not None:
                        # If None, then the subtitle is only present on Kodi
                        # side
                        answ['subtitleStreamID'] = strm_id
            return answ

    def signal_stop(self):
        """
        Externally called on PKC shutdown to ensure that PKC signals a stop to
        the PMS. Otherwise, PKC might be stuck at "currently playing"
        """
        LOG.info('Signaling a complete stop to PMS')
        # To avoid RuntimeError, don't use self.lastplayers
        for playerid in (0, 1, 2):
            self.last_params['state'] = 'stopped'
            self._send_pms_notification(playerid, self.last_params)

    def _plex_stream_index(self, playerid, stream_type):
        """
        Returns the current Plex stream index [str] for the player playerid

        stream_type: 'video', 'audio', 'subtitle'
        """
        playqueue = PQ.PLAYQUEUES[playerid]
        info = state.PLAYER_STATES[playerid]
        position = self._get_correct_position(info, playqueue)
        return playqueue.items[position].plex_stream_index(
            info[STREAM_DETAILS[stream_type]]['index'], stream_type)

    def update_command_id(self, uuid, command_id):
        """
        Updates the Plex Companien client with the machine identifier uuid with
        command_id
        """
        with state.LOCK_SUBSCRIBER:
            if command_id and self.subscribers.get(uuid):
                self.subscribers[uuid].command_id = int(command_id)

    def _playqueue_init_done(self, players):
        """
        update_player_info() can result in values BEFORE kodi monitor is called.
        Hence we'd have a missmatch between the state.PLAYER_STATES and our
        playqueues.
        """
        for player in players.values():
            info = state.PLAYER_STATES[player['playerid']]
            playqueue = PQ.PLAYQUEUES[player['playerid']]
            position = self._get_correct_position(info, playqueue)
            try:
                item = playqueue.items[position]
            except IndexError:
                # E.g. for direct path playback for single item
                return False
            if item.plex_id != info['plex_id']:
                # Kodi playqueue already progressed; need to wait until
                # everything is loaded
                return False
        return True

    def notify(self):
        """
        Causes PKC to tell the PMS and Plex Companion players to receive a
        notification what's being played.
        """
        with state.LOCK_SUBSCRIBER:
            self._cleanup()
            # Get all the active/playing Kodi players (video, audio, pictures)
            players = js.get_players()
            # Update the PKC info with what's playing on the Kodi side
            for player in players.values():
                update_player_info(player['playerid'])
            # Check whether we can use the CURRENT info or whether PKC is still
            # initializing
            if self._playqueue_init_done(players) is False:
                LOG.debug('PKC playqueue is still initializing - skip update')
                return
            self._notify_server(players)
            if self.subscribers:
                msg = self.msg(players)
                for subscriber in self.subscribers.values():
                    subscriber.send_update(msg)
            self.lastplayers = players

    def _notify_server(self, players):
        for typus, player in players.iteritems():
            self._send_pms_notification(
                player['playerid'], self._get_pms_params(player['playerid']))
            try:
                del self.lastplayers[typus]
            except KeyError:
                pass
        # Process the players we have left (to signal a stop)
        for player in self.lastplayers.values():
            self.last_params['state'] = 'stopped'
            self._send_pms_notification(player['playerid'], self.last_params)

    def _get_pms_params(self, playerid):
        info = state.PLAYER_STATES[playerid]
        playqueue = PQ.PLAYQUEUES[playerid]
        position = self._get_correct_position(info, playqueue)
        try:
            item = playqueue.items[position]
        except IndexError:
            return self.last_params
        status = 'paused' if int(info['speed']) == 0 else 'playing'
        params = {
            'state': status,
            'ratingKey': item.plex_id,
            'key': '/library/metadata/%s' % item.plex_id,
            'time': utils.kodi_time_to_millis(info['time']),
            'duration': utils.kodi_time_to_millis(info['totaltime'])
        }
        if info['container_key'] is not None:
            # params['containerKey'] = info['container_key']
            if info['container_key'].startswith('/playQueues/'):
                # params['playQueueVersion'] = playqueue.version
                # params['playQueueID'] = playqueue.id
                params['playQueueItemID'] = item.id
        self.last_params = params
        return params

    def _send_pms_notification(self, playerid, params):
        serv = self._server_by_host(self.server)
        playqueue = PQ.PLAYQUEUES[playerid]
        xargs = params_pms()
        xargs.update(params)
        if state.PLEX_TRANSIENT_TOKEN:
            xargs['X-Plex-Token'] = state.PLEX_TRANSIENT_TOKEN
        elif playqueue.plex_transient_token:
            xargs['X-Plex-Token'] = playqueue.plex_transient_token
        elif state.PMS_TOKEN:
            xargs['X-Plex-Token'] = state.PMS_TOKEN
        url = '%s://%s:%s/:/timeline' % (serv.get('protocol', 'http'),
                                         serv.get('server', 'localhost'),
                                         serv.get('port', '32400'))
        DU().downloadUrl(url,
                         authenticate=False,
                         parameters=xargs,
                         headerOverride=HEADERS_PMS)
        LOG.debug("Sent server notification with parameters: %s to %s",
                  xargs, url)

    def add_subscriber(self, protocol, host, port, uuid, command_id):
        """
        Adds a new Plex Companion subscriber to PKC.
        """
        subscriber = Subscriber(protocol,
                                host,
                                port,
                                uuid,
                                command_id,
                                self,
                                self.request_mgr)
        with state.LOCK_SUBSCRIBER:
            self.subscribers[subscriber.uuid] = subscriber
        return subscriber

    def remove_subscriber(self, uuid):
        """
        Removes a connected Plex Companion subscriber with machine identifier
        uuid from PKC notifications.
        (Calls the cleanup() method of the subscriber)
        """
        with state.LOCK_SUBSCRIBER:
            for subscriber in self.subscribers.values():
                if subscriber.uuid == uuid or subscriber.host == uuid:
                    subscriber.cleanup()
                    del self.subscribers[subscriber.uuid]

    def _cleanup(self):
        for subscriber in self.subscribers.values():
            if subscriber.age > 30:
                subscriber.cleanup()
                del self.subscribers[subscriber.uuid]


class Subscriber(object):
    """
    Plex Companion subscribing device
    """
    def __init__(self, protocol, host, port, uuid, command_id, sub_mgr,
                 request_mgr):
        self.protocol = protocol or "http"
        self.host = host
        self.port = port or 32400
        self.uuid = uuid or host
        self.command_id = int(command_id) or 0
        self.age = 0
        self.sub_mgr = sub_mgr
        self.request_mgr = request_mgr

    def __eq__(self, other):
        return self.uuid == other.uuid

    def cleanup(self):
        """
        Closes the connection to the Plex Companion client
        """
        self.request_mgr.closeConnection(self.protocol, self.host, self.port)

    def send_update(self, msg):
        """
        Sends msg to the Plex Companion client (via .../:/timeline)
        """
        self.age += 1
        msg = msg.format(command_id=self.command_id)
        LOG.debug("sending xml to subscriber uuid=%s,commandID=%i:\n%s",
                  self.uuid, self.command_id, msg)
        url = '%s://%s:%s/:/timeline' % (self.protocol, self.host, self.port)
        thread = Thread(target=self._threaded_send, args=(url, msg))
        thread.start()

    def _threaded_send(self, url, msg):
        """
        Threaded POST request, because they stall due to response missing
        the Content-Length header :-(
        """
        response = DU().downloadUrl(url,
                                    action_type="POST",
                                    postBody=msg,
                                    authenticate=False,
                                    headerOverride=headers_companion_client())
        if response in (False, None, 401):
            self.sub_mgr.remove_subscriber(self.uuid)
