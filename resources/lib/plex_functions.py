#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from urllib import urlencode, quote_plus
from ast import literal_eval
from urlparse import urlparse, parse_qsl
from copy import deepcopy
from time import time
from threading import Thread
from xbmc import sleep

from .downloadutils import DownloadUtils as DU
from . import utils
from . import plex_tv
from . import variables as v

###############################################################################
LOG = getLogger('PLEX.plex_functions')

CONTAINERSIZE = int(utils.settings('limitindex'))

# For discovery of PMS in the local LAN
PLEX_GDM_IP = '239.0.0.250'  # multicast to PMS
PLEX_GDM_PORT = 32414
PLEX_GDM_MSG = 'M-SEARCH * HTTP/1.0'

###############################################################################


def ConvertPlexToKodiTime(plexTime):
    """
    Converts Plextime to Koditime. Returns an int (in seconds).
    """
    if plexTime is None:
        return None
    return int(float(plexTime) * v.PLEX_TO_KODI_TIMEFACTOR)


def GetPlexKeyNumber(plexKey):
    """
    Deconstructs e.g. '/library/metadata/xxxx' to the tuple

        ('library/metadata', 'xxxx')

    Returns ('','') if nothing is found
    """
    try:
        result = utils.REGEX_END_DIGITS.findall(plexKey)[0]
    except IndexError:
        result = ('', '')
    return result


def ParseContainerKey(containerKey):
    """
    Parses e.g. /playQueues/3045?own=1&repeat=0&window=200 to:
    'playQueues', '3045', {'window': '200', 'own': '1', 'repeat': '0'}

    Output hence: library, key, query       (str, str, dict)
    """
    result = urlparse(containerKey)
    library, key = GetPlexKeyNumber(result.path)
    query = dict(parse_qsl(result.query))
    return library, key, query


def LiteralEval(string):
    """
    Turns a string e.g. in a dict, safely :-)
    """
    return literal_eval(string)


def GetMethodFromPlexType(plexType):
    methods = {
        'movie': 'add_update',
        'episode': 'add_updateEpisode',
        'show': 'add_update',
        'season': 'add_updateSeason',
        'track': 'add_updateSong',
        'album': 'add_updateAlbum',
        'artist': 'add_updateArtist'
    }
    return methods[plexType]


def GetPlexLoginFromSettings():
    """
    Returns a dict:
        'plexLogin': utils.settings('plexLogin'),
        'plexToken': utils.settings('plexToken'),
        'plexid': utils.settings('plexid'),
        'myplexlogin': utils.settings('myplexlogin'),
        'plexAvatar': utils.settings('plexAvatar'),

    Returns strings or unicode

    Returns empty strings '' for a setting if not found.

    myplexlogin is 'true' if user opted to log into plex.tv (the default)
    """
    return {
        'plexLogin': utils.settings('plexLogin'),
        'plexToken': utils.settings('plexToken'),
        'plexid': utils.settings('plexid'),
        'myplexlogin': utils.settings('myplexlogin'),
        'plexAvatar': utils.settings('plexAvatar'),
    }


def check_connection(url, token=None, verifySSL=None):
    """
    Checks connection to a Plex server, available at url. Can also be used
    to check for connection with plex.tv.

    Override SSL to skip the check by setting verifySSL=False
    if 'None', SSL will be checked (standard requests setting)
    if 'True', SSL settings from file settings are used (False/True)

    Input:
        url         URL to Plex server (e.g. https://192.168.1.1:32400)
        token       appropriate token to access server. If None is passed,
                    the current token is used
    Output:
        False       if server could not be reached or timeout occured
        200         if connection was successfull
        int         or other HTML status codes as received from the server
    """
    # Add '/clients' to URL because then an authentication is necessary
    # If a plex.tv URL was passed, this does not work.
    header_options = None
    if token is not None:
        header_options = {'X-Plex-Token': token}
    if verifySSL is True:
        verifySSL = None if utils.settings('sslverify') == 'true' else False
    if 'plex.tv' in url:
        url = 'https://plex.tv/api/home/users'
    LOG.debug("Checking connection to server %s with verifySSL=%s",
              url, verifySSL)
    answer = DU().downloadUrl(url,
                              authenticate=False,
                              headerOptions=header_options,
                              verifySSL=verifySSL,
                              timeout=10)
    if answer is None:
        LOG.debug("Could not connect to %s", url)
        return False
    try:
        # xml received?
        answer.attrib
    except AttributeError:
        if answer is True:
            # Maybe no xml but connection was successful nevertheless
            answer = 200
    else:
        # Success - we downloaded an xml!
        answer = 200
    # We could connect but maybe were not authenticated. No worries
    LOG.debug("Checking connection successfull. Answer: %s", answer)
    return answer


def discover_pms(token=None):
    """
    Optional parameter:
        token       token for plex.tv

    Returns a list of available PMS to connect to, one entry is the dict:
    {
        'machineIdentifier'     [str] unique identifier of the PMS
        'name'                  [str] name of the PMS
        'token'                 [str] token needed to access that PMS
        'ownername'             [str] name of the owner of this PMS or None if
                                the owner itself supplied tries to connect
        'product'               e.g. 'Plex Media Server' or None
        'version'               e.g. '1.11.2.4772-3e...' or None
        'device':               e.g. 'PC' or 'Windows' or None
        'platform':             e.g. 'Windows', 'Android' or None
        'local'                 [bool] True if plex.tv supplied
                                'publicAddressMatches'='1'
                                or if found using Plex GDM in the local LAN
        'owned'                 [bool] True if it's the owner's PMS
        'relay'                 [bool] True if plex.tv supplied 'relay'='1'
        'presence'              [bool] True if plex.tv supplied 'presence'='1'
        'httpsRequired'         [bool] True if plex.tv supplied
                                'httpsRequired'='1'
        'scheme'                [str] either 'http' or 'https'
        'ip':                   [str] IP of the PMS, e.g. '192.168.1.1'
        'port':                 [str] Port of the PMS, e.g. '32400'
        'baseURL':              [str] <scheme>://<ip>:<port> of the PMS
    }
    """
    LOG.info('Start discovery of Plex Media Servers')
    # Look first for local PMS in the LAN
    local_pms_list = _plex_gdm()
    LOG.debug('PMS found in the local LAN using Plex GDM: %s', local_pms_list)
    # Get PMS from plex.tv
    if token:
        LOG.info('Checking with plex.tv for more PMS to connect to')
        plex_pms_list = _pms_list_from_plex_tv(token)
        _log_pms(plex_pms_list)
    else:
        LOG.info('No plex token supplied, only checked LAN for available PMS')
        plex_pms_list = []

    # Add PMS found only in the LAN to the Plex.tv PMS list
    for pms in local_pms_list:
        for plex_pms in plex_pms_list:
            if pms['machineIdentifier'] == plex_pms['machineIdentifier']:
                break
        else:
            # Only found PMS using GDM - add it to the PMS from plex.tv
            https = _pms_https_enabled('%s:%s' % (pms['ip'], pms['port']))
            if https is None:
                # Error contacting url. Skip and ignore this PMS for now
                LOG.error('Could not contact PMS %s but we should have', pms)
                continue
            elif https is True:
                pms['scheme'] = 'https'
            else:
                pms['scheme'] = 'http'
            pms['baseURL'] = '%s://%s:%s' % (pms['scheme'],
                                             pms['ip'],
                                             pms['port'])
            plex_pms_list.append(pms)
    _log_pms(plex_pms_list)
    return plex_pms_list


def _log_pms(pms_list):
    log_list = deepcopy(pms_list)
    for pms in log_list:
        if pms.get('token') is not None:
            pms['token'] = '%s...' % pms['token'][:5]
    LOG.debug('Found the following PMS: %s', log_list)


def _plex_gdm():
    """
    PlexGDM - looks for PMS in the local LAN and returns a list of the PMS found
    """
    # Import here because we might not need to do gdm because we already
    # connected to a PMS successfully in the past
    import struct
    import socket

    # setup socket for discovery -> multicast message
    gdm = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gdm.settimeout(2.0)
    # Set the time-to-live for messages to 2 for local network
    ttl = struct.pack('b', 2)
    gdm.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

    return_data = []
    try:
        # Send data to the multicast group
        gdm.sendto(PLEX_GDM_MSG, (PLEX_GDM_IP, PLEX_GDM_PORT))

        # Look for responses from all recipients
        while True:
            try:
                data, server = gdm.recvfrom(1024)
                return_data.append({'from': server,
                                    'data': data.decode('utf-8')})
            except socket.timeout:
                break
    except Exception as e:
        # Probably error: (101, 'Network is unreachable')
        LOG.error(e)
        import traceback
        LOG.error("Traceback:\n%s", traceback.format_exc())
    finally:
        gdm.close()
    LOG.debug('Plex GDM returned the data: %s', return_data)
    pms_list = []
    for response in return_data:
        # Check if we had a positive HTTP response
        if '200 OK' not in response['data']:
            continue
        pms = {
            'ip': response['from'][0],
            'scheme': None,
            'local': True,  # Since we found it using GDM
            'product': None,
            'baseURL': None,
            'name': None,
            'version': None,
            'token': None,
            'ownername': None,
            'device': None,
            'platform': None,
            'owned': None,
            'relay': None,
            'presence': True,  # Since we're talking to the PMS
            'httpsRequired': None,
        }
        for line in response['data'].split('\n'):
            if 'Content-Type:' in line:
                pms['product'] = utils.try_decode(line.split(':')[1].strip())
            elif 'Host:' in line:
                pms['baseURL'] = line.split(':')[1].strip()
            elif 'Name:' in line:
                pms['name'] = utils.try_decode(line.split(':')[1].strip())
            elif 'Port:' in line:
                pms['port'] = line.split(':')[1].strip()
            elif 'Resource-Identifier:' in line:
                pms['machineIdentifier'] = line.split(':')[1].strip()
            elif 'Version:' in line:
                pms['version'] = line.split(':')[1].strip()
        pms_list.append(pms)
    return pms_list


def _pms_list_from_plex_tv(token):
    """
    get Plex media Server List from plex.tv/pms/resources
    """
    xml = DU().downloadUrl('https://plex.tv/api/resources',
                           authenticate=False,
                           parameters={'includeHttps': 1},
                           headerOptions={'X-Plex-Token': token})
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not get list of PMS from plex.tv')
        return []

    from Queue import Queue
    queue = Queue()
    thread_queue = []

    max_age_in_seconds = 2 * 60 * 60 * 24
    for device in xml.findall('Device'):
        if 'server' not in device.get('provides'):
            # No PMS - skip
            continue
        if device.find('Connection') is None:
            # no valid connection - skip
            continue
        # check MyPlex data age - skip if >2 days
        info_age = time() - int(device.get('lastSeenAt'))
        if info_age > max_age_in_seconds:
            LOG.debug("Skip server %s not seen for 2 days", device.get('name'))
            continue
        pms = {
            'machineIdentifier': device.get('clientIdentifier'),
            'name': device.get('name'),
            'token': device.get('accessToken'),
            'ownername': device.get('sourceTitle'),
            'product': device.get('product'),  # e.g. 'Plex Media Server'
            'version': device.get('productVersion'),  # e.g. '1.11.2.4772-3e..'
            'device': device.get('device'),  # e.g. 'PC' or 'Windows'
            'platform': device.get('platform'),  # e.g. 'Windows', 'Android'
            'local': device.get('publicAddressMatches') == '1',
            'owned': device.get('owned') == '1',
            'relay': device.get('relay') == '1',
            'presence': device.get('presence') == '1',
            'httpsRequired': device.get('httpsRequired') == '1',
            'connections': []
        }
        # Try a local connection first, no matter what plex.tv tells us
        for connection in device.findall('Connection'):
            if connection.get('local') == '1':
                pms['connections'].append(connection)
        # Then try non-local
        for connection in device.findall('Connection'):
            if connection.get('local') != '1':
                pms['connections'].append(connection)
        # Spawn threads to ping each PMS simultaneously
        thread = Thread(target=_poke_pms, args=(pms, queue))
        thread_queue.append(thread)

    max_threads = 5
    threads = []
    # poke PMS, own thread for each PMS
    while True:
        # Remove finished threads
        for thread in threads:
            if not thread.isAlive():
                threads.remove(thread)
        if len(threads) < max_threads:
            try:
                thread = thread_queue.pop()
            except IndexError:
                # We have done our work
                break
            else:
                thread.start()
                threads.append(thread)
        else:
            sleep(50)
    # wait for requests being answered
    for thread in threads:
        thread.join()
    # declare new PMSs
    pms_list = []
    while not queue.empty():
        pms = queue.get()
        del pms['connections']
        pms_list.append(pms)
        queue.task_done()
    return pms_list


def _poke_pms(pms, queue):
    data = pms['connections'][0].attrib
    url = data['uri']
    if data['local'] == '1' and utils.REGEX_PLEX_DIRECT.findall(url):
        # In case DNS resolve of plex.direct does not work, append a new
        # connection that will directly access the local IP (e.g. internet down)
        conn = deepcopy(pms['connections'][0])
        # Overwrite plex.direct
        conn.attrib['uri'] = '%s://%s:%s' % (data['protocol'],
                                             data['address'],
                                             data['port'])
        pms['connections'].insert(1, conn)
    try:
        protocol, address, port = url.split(':', 2)
    except ValueError:
        # e.g. .ork.plex.services uri, thanks Plex
        protocol, address = url.split(':', 1)
        port = data['port']
        url = '%s:%s' % (url, port)
    address = address.replace('/', '')
    xml = DU().downloadUrl('%s/identity' % url,
                           authenticate=False,
                           headerOptions={'X-Plex-Token': pms['token']},
                           verifySSL=False,
                           timeout=10)
    try:
        xml.attrib['machineIdentifier']
    except (AttributeError, KeyError):
        # No connection, delete the one we just tested
        del pms['connections'][0]
        if pms['connections']:
            # Still got connections left, try them
            return _poke_pms(pms, queue)
        return
    else:
        # Connection successful - correct pms?
        if xml.get('machineIdentifier') == pms['machineIdentifier']:
            # process later
            pms['baseURL'] = url
            pms['scheme'] = protocol
            pms['ip'] = address
            pms['port'] = port
            queue.put(pms)
            return
    LOG.info('Found a pms at %s, but the expected machineIdentifier of '
             '%s did not match the one we found: %s',
             url, pms['uuid'], xml.get('machineIdentifier'))


def GetPlexMetadata(key):
    """
    Returns raw API metadata for key as an etree XML.

    Can be called with either Plex key '/library/metadata/xxxx'metadata
    OR with the digits 'xxxx' only.

    Returns None or 401 if something went wrong
    """
    key = str(key)
    if '/library/metadata/' in key:
        url = "{server}" + key
    else:
        url = "{server}/library/metadata/" + key
    arguments = {
        'checkFiles': 0,
        'includeExtras': 1,         # Trailers and Extras => Extras
        'includeReviews': 1,
        'includeRelated': 0,        # Similar movies => Video -> Related
        'skipRefresh': 1,
        # 'includeRelatedCount': 0,
        # 'includeOnDeck': 1,
        # 'includeChapters': 1,
        # 'includePopularLeaves': 1,
        # 'includeConcerts': 1
    }
    url = url + '?' + urlencode(arguments)
    xml = DU().downloadUrl(url)
    if xml == 401:
        # Either unauthorized (taken care of by doUtils) or PMS under strain
        return 401
    # Did we receive a valid XML?
    try:
        xml.attrib
    # Nope we did not receive a valid XML
    except AttributeError:
        LOG.error("Error retrieving metadata for %s", url)
        xml = None
    return xml


def GetAllPlexChildren(key):
    """
    Returns a list (raw xml API dump) of all Plex children for the key.
    (e.g. /library/metadata/194853/children pointing to a season)

    Input:
        key             Key to a Plex item, e.g. 12345
    """
    return DownloadChunks("{server}/library/metadata/%s/children?" % key)


def GetPlexSectionResults(viewId, args=None):
    """
    Returns a list (XML API dump) of all Plex items in the Plex
    section with key = viewId.

    Input:
        args:       optional dict to be urlencoded

    Returns None if something went wrong
    """
    url = "{server}/library/sections/%s/all?" % viewId
    if args:
        url += urlencode(args) + '&'
    return DownloadChunks(url)


def DownloadChunks(url):
    """
    Downloads PMS url in chunks of CONTAINERSIZE.

    url MUST end with '?' (if no other url encoded args are present) or '&'

    Returns a stitched-together xml or None.
    """
    xml = None
    pos = 0
    error_counter = 0
    while error_counter < 10:
        args = {
            'X-Plex-Container-Size': CONTAINERSIZE,
            'X-Plex-Container-Start': pos
        }
        xmlpart = DU().downloadUrl(url + urlencode(args))
        # If something went wrong - skip in the hope that it works next time
        try:
            xmlpart.attrib
        except AttributeError:
            LOG.error('Error while downloading chunks: %s',
                      url + urlencode(args))
            pos += CONTAINERSIZE
            error_counter += 1
            continue

        # Very first run: starting xml (to retain data in xml's root!)
        if xml is None:
            xml = deepcopy(xmlpart)
            if len(xmlpart) < CONTAINERSIZE:
                break
            else:
                pos += CONTAINERSIZE
                continue
        # Build answer xml - containing the entire library
        for child in xmlpart:
            xml.append(child)
        # Done as soon as we don't receive a full complement of items
        if len(xmlpart) < CONTAINERSIZE:
            break
        pos += CONTAINERSIZE
    if error_counter == 10:
        LOG.error('Fatal error while downloading chunks for %s', url)
        return None
    return xml


def GetAllPlexLeaves(viewId, lastViewedAt=None, updatedAt=None):
    """
    Returns a list (raw XML API dump) of all Plex subitems for the key.
    (e.g. /library/sections/2/allLeaves pointing to all TV shows)

    Input:
        viewId              Id of Plex library, e.g. '2'
        lastViewedAt        Unix timestamp; only retrieves PMS items viewed
                            since that point of time until now.
        updatedAt           Unix timestamp; only retrieves PMS items updated
                            by the PMS since that point of time until now.

    If lastViewedAt and updatedAt=None, ALL PMS items are returned.

    Warning: lastViewedAt and updatedAt are combined with AND by the PMS!

    Relevant "master time": PMS server. I guess this COULD lead to problems,
    e.g. when server and client are in different time zones.
    """
    args = []
    url = "{server}/library/sections/%s/allLeaves" % viewId

    if lastViewedAt:
        args.append('lastViewedAt>=%s' % lastViewedAt)
    if updatedAt:
        args.append('updatedAt>=%s' % updatedAt)
    if args:
        url += '?' + '&'.join(args) + '&'
    else:
        url += '?'
    return DownloadChunks(url)


def GetPlexOnDeck(viewId):
    """
    """
    return DownloadChunks("{server}/library/sections/%s/onDeck?" % viewId)


def get_plex_hub():
    return DU().downloadUrl('{server}/hubs')


def get_plex_sections():
    """
    Returns all Plex sections (libraries) of the PMS as an etree xml
    """
    return DU().downloadUrl('{server}/library/sections')


def init_plex_playqueue(itemid, librarySectionUUID, mediatype='movie',
                        trailers=False):
    """
    Returns raw API metadata XML dump for a playlist with e.g. trailers.
   """
    url = "{server}/playQueues"
    args = {
        'type': mediatype,
        'uri': ('library://' + librarySectionUUID +
                '/item/%2Flibrary%2Fmetadata%2F' + itemid),
        'includeChapters': '1',
        'shuffle': '0',
        'repeat': '0'
    }
    if trailers is True:
        args['extrasPrefixCount'] = utils.settings('trailerNumber')
    xml = DU().downloadUrl(url + '?' + urlencode(args), action_type="POST")
    try:
        xml[0].tag
    except (IndexError, TypeError, AttributeError):
        LOG.error("Error retrieving metadata for %s", url)
        return
    return xml


def _pms_https_enabled(url):
    """
    Returns True if the PMS can talk https, False otherwise.
    None if error occured, e.g. the connection timed out

    Call with e.g. url='192.168.0.1:32400' (NO http/https)

    This is done by GET /identity (returns an error if https is enabled and we
    are trying to use http)

    Prefers HTTPS over HTTP
    """
    res = DU().downloadUrl('https://%s/identity' % url,
                           authenticate=False,
                           verifySSL=False)
    try:
        res.attrib
    except AttributeError:
        # Might have SSL deactivated. Try with http
        res = DU().downloadUrl('http://%s/identity' % url,
                               authenticate=False,
                               verifySSL=False)
        try:
            res.attrib
        except AttributeError:
            LOG.error("Could not contact PMS %s", url)
            return None
        else:
            # Received a valid XML. Server wants to talk HTTP
            return False
    else:
        # Received a valid XML. Server wants to talk HTTPS
        return True


def GetMachineIdentifier(url):
    """
    Returns the unique PMS machine identifier of url

    Returns None if something went wrong
    """
    xml = DU().downloadUrl('%s/identity' % url,
                           authenticate=False,
                           verifySSL=False,
                           timeout=10)
    try:
        machineIdentifier = xml.attrib['machineIdentifier']
    except (AttributeError, KeyError):
        LOG.error('Could not get the PMS machineIdentifier for %s', url)
        return None
    LOG.debug('Found machineIdentifier %s for the PMS %s',
              machineIdentifier, url)
    return machineIdentifier


def GetPMSStatus(token):
    """
    token:                  Needs to be authorized with a master Plex token
                            (not a managed user token)!
    Calls /status/sessions on currently active PMS. Returns a dict with:

    'sessionKey':
    {
        'userId':           Plex ID of the user (if applicable, otherwise '')
        'username':         Plex name (if applicable, otherwise '')
        'ratingKey':        Unique Plex id of item being played
    }

    or an empty dict.
    """
    answer = {}
    xml = DU().downloadUrl('{server}/status/sessions',
                           headerOptions={'X-Plex-Token': token})
    try:
        xml.attrib
    except AttributeError:
        return answer
    for item in xml:
        ratingKey = item.attrib.get('ratingKey')
        sessionKey = item.attrib.get('sessionKey')
        userId = item.find('User')
        username = ''
        if userId is not None:
            username = userId.attrib.get('title', '')
            userId = userId.attrib.get('id', '')
        else:
            userId = ''
        answer[sessionKey] = {
            'userId': userId,
            'username': username,
            'ratingKey': ratingKey
        }
    return answer


def collections(section_id):
    """
    Returns an etree with list of collections or None.
    """
    url = '{server}/library/sections/%s/all' % section_id
    params = {
        'type': 18,  # Collections
        'includeCollections': 1,
    }
    xml = DU().downloadUrl(url, parameters=params)
    try:
        xml.attrib
    except AttributeError:
        LOG.error("Error retrieving collections for %s", url)
        xml = None
    return xml


def scrobble(ratingKey, state):
    """
    Tells the PMS to set an item's watched state to state="watched" or
    state="unwatched"
    """
    args = {
        'key': ratingKey,
        'identifier': 'com.plexapp.plugins.library'
    }
    if state == "watched":
        url = "{server}/:/scrobble?" + urlencode(args)
    elif state == "unwatched":
        url = "{server}/:/unscrobble?" + urlencode(args)
    else:
        return
    DU().downloadUrl(url)
    LOG.info("Toggled watched state for Plex item %s", ratingKey)


def delete_item_from_pms(plexid):
    """
    Deletes the item plexid from the Plex Media Server (and the harddrive!).
    Do make sure that the currently logged in user has the credentials

    Returns True if successful, False otherwise
    """
    if DU().downloadUrl('{server}/library/metadata/%s' % plexid,
                        action_type="DELETE") is True:
        LOG.info('Successfully deleted Plex id %s from the PMS', plexid)
        return True
    LOG.error('Could not delete Plex id %s from the PMS', plexid)
    return False


def get_PMS_settings(url, token):
    """
    Retrieve the PMS' settings via <url>/:/prefs

    Call with url: scheme://ip:port
    """
    return DU().downloadUrl(
        '%s/:/prefs' % url,
        authenticate=False,
        verifySSL=False,
        headerOptions={'X-Plex-Token': token} if token else None)


def GetUserArtworkURL(username):
    """
    Returns the URL for the user's Avatar. Or False if something went
    wrong.
    """
    users = plex_tv.plex_home_users(utils.settings('plexToken'))
    url = ''
    for user in users:
        if user.title == username:
            url = user.thumb
    LOG.debug("Avatar url for user %s is: %s", username, url)
    return url


def transcode_image_path(key, AuthToken, path, width, height):
    """
    Transcode Image support

    parameters:
        key
        AuthToken
        path - source path of current XML: path[srcXML]
        width
        height
    result:
        final path to image file
    """
    # external address - can we get a transcoding request for external images?
    if key.startswith('http://') or key.startswith('https://'):
        path = key
    elif key.startswith('/'):  # internal full path.
        path = 'http://127.0.0.1:32400' + key
    else:  # internal path, add-on
        path = 'http://127.0.0.1:32400' + path + '/' + key
    path = utils.try_encode(path)
    # This is bogus (note the extra path component) but ATV is stupid when it
    # comes to caching images, it doesn't use querystrings. Fortunately PMS is
    # lenient...
    transcode_path = ('/photo/:/transcode/%sx%s/%s'
                      % (width, height, quote_plus(path)))
    args = {
        'width': width,
        'height': height,
        'url': path
    }
    if AuthToken:
        args['X-Plex-Token'] = AuthToken
    return transcode_path + '?' + urlencode(args)
