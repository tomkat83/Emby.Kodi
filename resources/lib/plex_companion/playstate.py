#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import requests
import xml.etree.ElementTree as etree

from .common import proxy_headers, proxy_params, log_error

from .. import json_rpc as js
from .. import variables as v
from .. import backgroundthread
from .. import app
from .. import timing
from .. import playqueue as PQ
from .. import skip_plex_intro


# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

log = getLogger('PLEX.companion.playstate')

TIMEOUT = (5, 5)

# What is Companion controllable?
CONTROLLABLE = {
    v.PLEX_PLAYLIST_TYPE_VIDEO: 'playPause,stop,volume,shuffle,audioStream,'
        'subtitleStream,seekTo,skipPrevious,skipNext,'
        'stepBack,stepForward',
    v.PLEX_PLAYLIST_TYPE_AUDIO: 'playPause,stop,volume,shuffle,repeat,seekTo,'
        'skipPrevious,skipNext,stepBack,stepForward',
    v.PLEX_PLAYLIST_TYPE_PHOTO: 'playPause,stop,skipPrevious,skipNext'
}


def split_server_uri(server):
    (protocol, url, port) = server.split(':')
    url = url.replace('/', '')
    return (protocol, url, port)


def get_correct_position(info, playqueue):
    """
    Kodi tells us the PLAYLIST position, not PLAYQUEUE position, if the
    user initiated playback of a playlist
    """
    if playqueue.kodi_playlist_playback:
        position = 0
    else:
        position = info['position'] or 0
    return position


def timeline_dict(playerid, typus):
    with app.APP.lock_playqueues:
        info = app.PLAYSTATE.player_states[playerid]
        playqueue = PQ.PLAYQUEUES[playerid]
        position = get_correct_position(info, playqueue)
        try:
            item = playqueue.items[position]
        except IndexError:
            # E.g. for direct path playback for single item
            return {
                'controllable': CONTROLLABLE[typus],
                'type': typus,
                'state': 'stopped'
            }
        protocol, url, port = split_server_uri(app.CONN.server)
        status = 'paused' if int(info['speed']) == 0 else 'playing'
        duration = timing.kodi_time_to_millis(info['totaltime'])
        shuffle = '1' if info['shuffled'] else '0'
        mute = '1' if info['muted'] is True else '0'
        answ = {
            'controllable': CONTROLLABLE[typus],
            'protocol': protocol,
            'address': url,
            'port': port,
            'machineIdentifier': app.CONN.machine_identifier,
            'state': status,
            'type': typus,
            'itemType': typus,
            'time': str(timing.kodi_time_to_millis(info['time'])),
            'duration': str(duration),
            'seekRange': '0-%s' % duration,
            'shuffle': shuffle,
            'repeat': v.PLEX_REPEAT_FROM_KODI_REPEAT[info['repeat']],
            'volume': str(info['volume']),
            'mute': mute,
            'mediaIndex': '0',  # Still to implement
            'partIndex': '0',
            'partCount': '1',
            'providerIdentifier': 'com.plexapp.plugins.library',
        }
        # Get the plex id from the PKC playqueue not info, as Kodi jumps to
        # next playqueue element way BEFORE kodi monitor onplayback is
        # called
        if item.plex_id:
            answ['key'] = '/library/metadata/%s' % item.plex_id
            answ['ratingKey'] = str(item.plex_id)
        # PlayQueue stuff
        if info['container_key']:
            answ['containerKey'] = info['container_key']
        if (info['container_key'] is not None and
                info['container_key'].startswith('/playQueues')):
            answ['playQueueID'] = str(playqueue.id)
            answ['playQueueVersion'] = str(playqueue.version)
            answ['playQueueItemID'] = str(item.id)
        if playqueue.items[position].guid:
            answ['guid'] = item.guid
        # Temp. token set?
        if app.CONN.plex_transient_token:
            answ['token'] = app.CONN.plex_transient_token
        elif playqueue.plex_transient_token:
            answ['token'] = playqueue.plex_transient_token
        # Process audio and subtitle streams
        if typus == v.PLEX_PLAYLIST_TYPE_VIDEO:
            answ['videoStreamID'] = str(item.current_plex_video_stream)
            answ['audioStreamID'] = str(item.current_plex_audio_stream)
            # Mind the zero - meaning subs are deactivated
            answ['subtitleStreamID'] = str(item.current_plex_sub_stream or 0)
        return answ


def timeline(players):
    """
    Returns a timeline xml as str
    (xml containing video, audio, photo player state)
    """
    xml = etree.Element('MediaContainer')
    location = 'navigation'
    for typus in (v.PLEX_PLAYLIST_TYPE_AUDIO,
                  v.PLEX_PLAYLIST_TYPE_VIDEO,
                  v.PLEX_PLAYLIST_TYPE_PHOTO):
        player = players.get(v.KODI_PLAYLIST_TYPE_FROM_PLEX_PLAYLIST_TYPE[typus])
        if player is None:
            # Kodi player currently not actively playing, but stopped
            timeline = {
                'controllable': CONTROLLABLE[typus],
                'type': typus,
                'state': 'stopped'
            }
        else:
            # Active Kodi player, i.e. video, audio or picture player
            timeline = timeline_dict(player['playerid'], typus)
            if typus in (v.PLEX_PLAYLIST_TYPE_VIDEO, v.PLEX_PLAYLIST_TYPE_PHOTO):
                location = 'fullScreenVideo'
        etree.SubElement(xml, 'Timeline', attrib=timeline)
    xml.set('location', location)
    return xml


def stopped_timeline():
    """
    Returns an XML stating that all players have stopped playback
    """
    xml = etree.Element('MediaContainer', attrib={'location': 'navigation'})
    for typus in (v.PLEX_PLAYLIST_TYPE_AUDIO,
                  v.PLEX_PLAYLIST_TYPE_VIDEO,
                  v.PLEX_PLAYLIST_TYPE_PHOTO):
        # Kodi player currently not actively playing, but stopped
        timeline = {
            'controllable': CONTROLLABLE[typus],
            'type': typus,
            'state': 'stopped'
        }
        etree.SubElement(xml, 'Timeline', attrib=timeline)
    return xml


def update_player_info(players):
    """
    Update the playstate info for other PKC "consumers"
    """
    for player in players.values():
        playerid = player['playerid']
        app.PLAYSTATE.player_states[playerid].update(js.get_player_props(playerid))
        app.PLAYSTATE.player_states[playerid]['volume'] = js.get_volume()
        app.PLAYSTATE.player_states[playerid]['muted'] = js.get_muted()


class PlaystateMgr(backgroundthread.KillableThread):
    """
    If Kodi plays something, tell the PMS about it and - if a Companion client
    is connected - tell the PMS Plex Companion piece of the PMS about it.
    Also checks whether an intro is currently playing, enabling the user to
    skip it.
    """
    daemon = True

    def __init__(self):
        self._subscribed = False
        self._command_id = None
        self.s = None
        self.t = None
        self.stopped_timeline = stopped_timeline()
        super().__init__()

    def _get_requests_session(self):
        if self.s is None:
            log.debug('Creating new requests session')
            self.s = requests.Session()
            self.s.headers = proxy_headers()
            self.s.verify = app.CONN.verify_ssl_cert
            if app.CONN.ssl_cert_path:
                self.s.cert = app.CONN.ssl_cert_path
            self.s.params = proxy_params()
        return self.s

    def _get_requests_session_companion(self):
        if self.t is None:
            log.debug('Creating new companion requests session')
            self.t = requests.Session()
            self.t.headers = proxy_headers()
            self.t.verify = app.CONN.verify_ssl_cert
            if app.CONN.ssl_cert_path:
                self.t.cert = app.CONN.ssl_cert_path
            self.t.params = proxy_params()
        return self.t

    def close_requests_session(self):
        for session in (self.s, self.t):
            if session is not None:
                try:
                    session.close()
                except AttributeError:
                    # "thread-safety" - Just in case s was set to None in the
                    # meantime
                    pass
                session = None

    @staticmethod
    def communicate(method, url, **kwargs):
        try:
            # This will usually block until timeout is reached!
            req = method(url, **kwargs)
        except requests.ConnectTimeout:
            # The request timed out while trying to connect to the PMS
            log.error('Requests ConnectionTimeout!')
            raise
        except requests.ReadTimeout:
            # The PMS did not send any data in the allotted amount of time
            log.error('Requests ReadTimeout!')
            raise
        except requests.TooManyRedirects:
            log.error('TooManyRedirects error!')
            raise
        except requests.HTTPError as error:
            log.error('HTTPError: %s', error)
            raise
        except requests.ConnectionError as error:
            log.error('ConnectionError: %s', error)
            raise
        req.encoding = 'utf-8'
        # To make sure that we release the socket, need to access content once
        req.content
        return req

    def _subscribe(self, cmd):
        self._command_id = int(cmd.get('commandID'))
        self._subscribed = True

    def _unsubscribe(self):
        self._subscribed = False
        self._command_id = None

    def send_stop(self):
        """
        If we're still connected to a PMS, tells the PMS that playback stopped
        """
        if app.CONN.online and app.ACCOUNT.authenticated:
            # Only try to send something if we're connected
            self.pms_timeline(dict(), self.stopped_timeline)
            self.companion_timeline(self.stopped_timeline)

    def check_subscriber(self, cmd):
        if cmd.get('path') == '/player/timeline/unsubscribe':
            log.info('Stop Plex Companion subscription')
            self._unsubscribe()
        elif not self._subscribed:
            log.info('Start Plex Companion subscription')
            self._subscribe(cmd)
        else:
            try:
                self._command_id = int(cmd.get('commandID'))
            except TypeError:
                pass

    def companion_timeline(self, message):
        if not self._subscribed:
            return
        url = f'{app.CONN.server}/player/proxy/timeline'
        self._get_requests_session_companion()
        self.t.params['commandID'] = self._command_id
        message.set('commandID', str(self._command_id))
        # Get the correct playstate
        state = 'stopped'
        for timeline in message:
            if timeline.get('state') != 'stopped':
                state = timeline.get('state')
        self.t.params['state'] = state
        # Send update
        try:
            req = self.communicate(self.t.post,
                                   url,
                                   data=etree.tostring(message,
                                                       encoding='utf-8'),
                                   timeout=TIMEOUT)
        except (requests.RequestException, SystemExit):
            return
        if not req.ok:
            log_error(log.error, 'Unexpected Companion timeline', req)

    def pms_timeline_per_player(self, playerid, message):
        """
        Pass a really low timeout in seconds if shutting down Kodi and we don't
        need the PMS' response
        """
        url = f'{app.CONN.server}/:/timeline'
        self._get_requests_session()
        self.s.params.update(message[playerid].attrib)
        # Tell the PMS about our playstate progress
        try:
            req = self.communicate(self.s.get, url, timeout=TIMEOUT)
        except (requests.RequestException, SystemExit):
            return
        if not req.ok:
            log_error(log.error, 'Failed reporting playback progress', req)

    def pms_timeline(self, players, message):
        players = players if players else \
            {0: {'playerid': 0}, 1: {'playerid': 1}, 2: {'playerid': 2}}
        for player in players.values():
            self.pms_timeline_per_player(player['playerid'], message)

    def run(self):
        app.APP.register_thread(self)
        log.info("----===## Starting PlaystateMgr ##===----")
        try:
            self._run()
        finally:
            # Make sure we're telling the PMS that playback will stop
            self.send_stop()
            # Cleanup
            self.close_requests_session()
            app.APP.deregister_thread(self)
            log.info("----===## PlaystateMgr stopped ##===----")

    def _run(self):
        signaled_playback_stop = True
        while not self.should_cancel():
            if self.should_suspend():
                self._unsubscribe()
                self.close_requests_session()
                if self.wait_while_suspended():
                    break
            # We will only become active if there's Kodi playback going on
            players = js.get_players()
            if not players and signaled_playback_stop:
                self.sleep(1)
                continue
            elif not players:
                # Playback has just stopped, need to tell Plex
                signaled_playback_stop = True
                self.send_stop()
                self.sleep(1)
                continue
            else:
                # Update the playstate info, such as playback progress
                update_player_info(players)
                try:
                    message = timeline(players)
                except TypeError:
                    # We haven't had a chance to set the kodi_stream_index for
                    # the currently playing item. Just skip for now
                    self.sleep(1)
                    continue
                else:
                    # Kodi will started with 'stopped' - make sure we're
                    # waiting here until we got something playing or on pause.
                    for entry in message:
                        if entry.get('state') != 'stopped':
                            break
                    else:
                        continue
                    signaled_playback_stop = False
            try:
                # Check whether an intro is currently running
                skip_plex_intro.check()
            except IndexError:
                # Playback might have already stopped
                pass
            # Send the playback progress info to the PMS
            self.pms_timeline(players, message)
            # Send the info to all Companion devices via the PMS
            self.companion_timeline(message)
            self.sleep(1)
