#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
from copy import deepcopy
import requests
import xml.etree.ElementTree as etree

from .. import variables as v
from .. import utils
from .. import app
from .. import timing

# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

log = logging.getLogger('PLEX.companion')

TIMEOUT = (5, 5)

# What is Companion controllable?
CONTROLLABLE = {
    v.PLEX_PLAYLIST_TYPE_VIDEO: 'playPause,stop,volume,shuffle,audioStream,'
        'subtitleStream,seekTo,skipPrevious,skipNext,stepBack,stepForward',
    v.PLEX_PLAYLIST_TYPE_AUDIO: 'playPause,stop,volume,shuffle,repeat,seekTo,'
        'skipPrevious,skipNext,stepBack,stepForward',
    v.PLEX_PLAYLIST_TYPE_PHOTO: 'playPause,stop,skipPrevious,skipNext'
}


def log_error(logger, error_message, response):
    logger('%s: %s: %s', error_message, response.status_code, response.reason)
    logger('headers received from the PMS: %s', response.headers)
    logger('Message received from the PMS: %s', response.text)


def proxy_headers():
    return {
        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
        'X-Plex-Product': v.ADDON_NAME,
        'X-Plex-Version': v.ADDON_VERSION,
        'X-Plex-Platform': v.PLATFORM,
        'X-Plex-Platform-Version': v.PLATFORM_VERSION,
        'X-Plex-Device-Name': v.DEVICENAME,
        'Content-Type': 'text/xml;charset=utf-8'
    }


def proxy_params():
    params = {
        'deviceClass': 'pc',
        'protocolCapabilities': 'timeline,playback,navigation,playqueues',
        'protocolVersion': 3
    }
    if app.ACCOUNT.pms_token:
        params['X-Plex-Token'] = app.ACCOUNT.pms_token
    return params


def player():
    return {
        'product': v.ADDON_NAME,
        'deviceClass': 'pc',
        'platform': v.PLATFORM,
        'platformVersion': v.PLATFORM_VERSION,
        'protocolVersion': '3',
        'title': v.DEVICENAME,
        'protocolCapabilities': 'timeline,playback,navigation,playqueues',
        'machineIdentifier': v.PKC_MACHINE_IDENTIFIER,
    }


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


def create_requests_session():
    s = requests.Session()
    s.headers = proxy_headers()
    s.verify = app.CONN.verify_ssl_cert
    if app.CONN.ssl_cert_path:
        s.cert = app.CONN.ssl_cert_path
    s.params = proxy_params()
    return s


def communicate(method, url, **kwargs):
    req = method(url, **kwargs)
    req.encoding = 'utf-8'
    # To make sure that we release the socket, need to access content once
    req.content
    return req


def timeline_dict(playerid, typus):
    with app.APP.lock_playqueues:
        info = app.PLAYSTATE.player_states[playerid]
        playqueue = app.PLAYQUEUES[playerid]
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
        if typus == v.PLEX_PLAYLIST_TYPE_VIDEO and not item.streams_initialized:
            # Not ready yet to send updates
            raise TypeError()
        o = utils.urlparse(app.CONN.server)
        status = 'paused' if int(info['speed']) == 0 else 'playing'
        duration = timing.kodi_time_to_millis(info['totaltime'])
        shuffle = '1' if info['shuffled'] else '0'
        mute = '1' if info['muted'] is True else '0'
        answ = {
            'controllable': CONTROLLABLE[typus],
            'protocol': o.scheme,
            'address': o.hostname,
            'port': str(o.port),
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
            item.current_kodi_video_stream = info['currentvideostream']['index']
            item.current_kodi_audio_stream = info['currentaudiostream']['index']
            item.current_kodi_sub_stream_enabled = info['subtitleenabled']
            try:
                item.current_kodi_sub_stream = info['currentsubtitle']['index']
            except KeyError:
                item.current_kodi_sub_stream = None
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
    Returns an etree XML stating that all players have stopped playback
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


def b_ok_message():
    """
    Returns a byte-encoded (b'') OK message XML for the PMS
    """
    return etree.tostring(
        etree.Element('Response', attrib={'code': '200', 'status': 'OK'}),
        encoding='utf8')


class Subscriber(object):
    def __init__(self, playstate_mgr, cmd=None, uuid=None, command_id=None,
                 url=None):
        self.playstate_mgr = playstate_mgr
        if cmd is not None:
            self.uuid = cmd.get('clientIdentifier')
            self.command_id = int(cmd.get('commandID', 0))
            self.url = f'{app.CONN.server}/player/proxy/timeline'
        else:
            self.uuid = str(uuid)
            self.command_id = command_id
            self.url = f'{url}/:/timeline'
        self.s = create_requests_session()
        self._errors_left = 3

    def __eq__(self, other):
        if isinstance(other, str):
            return self.uuid == other
        elif isinstance(other, Subscriber):
            return self.uuid == other.uuid
        else:
            return False

    def __hash__(self):
        return hash(self.uuid)

    def __del__(self):
        """Make sure we are closing the Session() correctly."""
        self.s.close()

    def _on_error(self):
        self._errors_left -= 1
        if self._errors_left == 0:
            log.warn('Too many issues contacting subscriber %s. Unsubscribing',
                     self.uuid)
            self.playstate_mgr.unsubscribe(self)

    def send_timeline(self, message, state):
        message = deepcopy(message)
        message.set('commandID', str(self.command_id + 1))
        self.s.params['state'] = state
        self.s.params['commandID'] = self.command_id + 1
        # Send update
        log.debug('Sending timeline update to %s with params %s',
                  self.uuid, self.s.params)
        utils.log_xml(message, log.debug, logging.DEBUG)
        try:
            req = communicate(self.s.post,
                              self.url,
                              data=etree.tostring(message, encoding='utf8'),
                              timeout=TIMEOUT)
        except requests.RequestException as error:
            log.warn('Error sending timeline to Subscriber %s: %s: %s',
                     self.uuid, self.url, error)
            self._on_error()
            return
        except SystemExit:
            return
        if not req.ok:
            log_error(log.error,
                      'Unexpected Companion timeline response for player '
                      f'{self.uuid}: {self.url}',
                      req)
            self._on_error()


class UUIDStr(str):
    """
    Subclass of str in order to be able to compare to Subscriber objects
    like this: if UUIDStr() in list(Subscriber(), Subscriber()): ...
    """

    def __eq__(self, other):
        if isinstance(other, Subscriber):
            return self == other.uuid
        else:
            return super().__eq__(other)

    def __hash__(self):
        return super().__hash__()
