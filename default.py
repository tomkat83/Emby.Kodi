# -*- coding: utf-8 -*-

###############################################################################

import logging
from os import path as os_path
from sys import path as sys_path, argv
from urlparse import parse_qsl

from xbmc import translatePath, sleep, executebuiltin
from xbmcaddon import Addon
from xbmcgui import ListItem
from xbmcplugin import setResolvedUrl

_addon = Addon(id='plugin.video.plexkodiconnect')
try:
    _addon_path = _addon.getAddonInfo('path').decode('utf-8')
except TypeError:
    _addon_path = _addon.getAddonInfo('path').decode()
try:
    _base_resource = translatePath(os_path.join(
        _addon_path,
        'resources',
        'lib')).decode('utf-8')
except TypeError:
    _base_resource = translatePath(os_path.join(
        _addon_path,
        'resources',
        'lib')).decode()
sys_path.append(_base_resource)

###############################################################################

import entrypoint
from utils import window, reset, passwords_xml, language as lang, dialog, \
    plex_command
from pickler import unpickle_me, pickl_window
from PKC_listitem import convert_PKC_to_listitem
import variables as v

###############################################################################

import loghandler

loghandler.config()
log = logging.getLogger('PLEX.default')

###############################################################################

HANDLE = int(argv[1])


class Main():
    # MAIN ENTRY POINT
    # @utils.profiling()
    def __init__(self):
        log.debug('Full sys.argv received: %s' % argv)
        # Parse parameters
        params = dict(parse_qsl(argv[2][1:]))
        mode = params.get('mode', '')
        itemid = params.get('id', '')

        if mode == 'play':
            self.play()

        elif mode == 'plex_node':
            self.play()

        elif mode == 'ondeck':
            entrypoint.getOnDeck(itemid,
                                 params.get('type'),
                                 params.get('tagname'),
                                 int(params.get('limit')))

        elif mode == 'recentepisodes':
            entrypoint.getRecentEpisodes(itemid,
                                         params.get('type'),
                                         params.get('tagname'),
                                         int(params.get('limit')))

        elif mode == 'nextup':
            entrypoint.getNextUpEpisodes(params['tagname'],
                                         int(params['limit']))

        elif mode == 'inprogressepisodes':
            entrypoint.getInProgressEpisodes(params['tagname'],
                                             int(params['limit']))

        elif mode == 'browseplex':
            entrypoint.browse_plex(key=params.get('key'),
                                   plex_section_id=params.get('id'))

        elif mode == 'getsubfolders':
            entrypoint.GetSubFolders(itemid)

        elif mode == 'watchlater':
            entrypoint.watchlater()

        elif mode == 'channels':
            entrypoint.channels()

        elif mode == 'extras':
            entrypoint.extras(plex_id=params.get('plex_id'))

        elif mode == 'settings':
            executebuiltin('Addon.OpenSettings(%s)' % v.ADDON_ID)

        elif mode == 'enterPMS':
            entrypoint.enterPMS()

        elif mode == 'reset':
            reset()

        elif mode == 'togglePlexTV':
            entrypoint.togglePlexTV()

        elif mode == 'resetauth':
            entrypoint.resetAuth()

        elif mode == 'passwords':
            passwords_xml()

        elif mode == 'switchuser':
            entrypoint.switchPlexUser()

        elif mode in ('manualsync', 'repair'):
            if window('plex_online') != 'true':
                # Server is not online, do not run the sync
                dialog('ok', lang(29999), lang(39205))
                log.error('Not connected to a PMS.')
            else:
                if mode == 'repair':
                    log.info('Requesting repair lib sync')
                    plex_command('RUN_LIB_SCAN', 'repair')
                elif mode == 'manualsync':
                    log.info('Requesting full library scan')
                    plex_command('RUN_LIB_SCAN', 'full')

        elif mode == 'texturecache':
            log.info('Requesting texture caching of all textures')
            plex_command('RUN_LIB_SCAN', 'textures')

        elif mode == 'chooseServer':
            entrypoint.chooseServer()

        elif mode == 'refreshplaylist':
            log.info('Requesting playlist/nodes refresh')
            plex_command('RUN_LIB_SCAN', 'views')

        elif mode == 'deviceid':
            self.deviceid()

        elif mode == 'fanart':
            log.info('User requested fanarttv refresh')
            plex_command('RUN_LIB_SCAN', 'fanart')

        elif '/extrafanart' in argv[0]:
            plexpath = argv[2][1:]
            plexid = itemid
            entrypoint.getExtraFanArt(plexid, plexpath)
            entrypoint.getVideoFiles(plexid, plexpath)

        # Called by e.g. 3rd party plugin video extras
        elif ('/Extras' in argv[0] or '/VideoFiles' in argv[0] or
                '/Extras' in argv[2]):
            plexId = itemid or None
            entrypoint.getVideoFiles(plexId, params)

        else:
            entrypoint.doMainListing(content_type=params.get('content_type'))

    @staticmethod
    def play():
        """
        Start up playback_starter in main Python thread
        """
        request = '%s&handle=%s' % (argv[2], HANDLE)
        # Put the request into the 'queue'
        plex_command('PLAY', request)
        if HANDLE == -1:
            # Handle -1 received, not waiting for main thread
            return
        # Wait for the result
        while not pickl_window('plex_result'):
            sleep(50)
        result = unpickle_me()
        if result is None:
            log.error('Error encountered, aborting')
            dialog('notification',
                   heading='{plex}',
                   message=lang(30128),
                   icon='{error}',
                   time=3000)
            setResolvedUrl(HANDLE, False, ListItem())
        elif result.listitem:
            listitem = convert_PKC_to_listitem(result.listitem)
            setResolvedUrl(HANDLE, True, listitem)

    @staticmethod
    def deviceid():
        deviceId_old = window('plex_client_Id')
        from clientinfo import getDeviceId
        try:
            deviceId = getDeviceId(reset=True)
        except Exception as e:
            log.error('Failed to generate a new device Id: %s' % e)
            dialog('ok', lang(29999), lang(33032))
        else:
            log.info('Successfully removed old device ID: %s New deviceId:'
                     '%s' % (deviceId_old, deviceId))
            # 'Kodi will now restart to apply the changes'
            dialog('ok', lang(29999), lang(33033))
            executebuiltin('RestartApp')


if __name__ == '__main__':
    log.info('%s started' % v.ADDON_ID)
    Main()
    log.info('%s stopped' % v.ADDON_ID)
