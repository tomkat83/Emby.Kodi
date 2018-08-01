# -*- coding: utf-8 -*-

###############################################################################
from __future__ import absolute_import, division, unicode_literals
import logging
from sys import argv
from urlparse import parse_qsl
from xbmc import sleep, executebuiltin
from xbmcgui import ListItem
from xbmcplugin import setResolvedUrl

from resources.lib import entrypoint, utils, pickler, pkc_listitem, \
    variables as v, loghandler
from resources.lib.watchdog.utils import unicode_paths

###############################################################################

loghandler.config()
log = logging.getLogger('PLEX.default')

###############################################################################

HANDLE = int(argv[1])


class Main():
    # MAIN ENTRY POINT
    # @utils.profiling()
    def __init__(self):
        log.debug('Full sys.argv received: %s', argv)
        # Parse parameters
        path = unicode_paths.decode(argv[0])
        arguments = unicode_paths.decode(argv[2])
        params = dict(parse_qsl(arguments[1:]))
        mode = params.get('mode', '')
        itemid = params.get('id', '')

        if mode == 'play':
            self.play()

        elif mode == 'plex_node':
            self.play()

        elif mode == 'ondeck':
            entrypoint.on_deck_episodes(itemid,
                                        params.get('tagname'),
                                        int(params.get('limit')))

        elif mode == 'recentepisodes':
            entrypoint.recent_episodes(params.get('type'),
                                       params.get('tagname'),
                                       int(params.get('limit')))

        elif mode == 'nextup':
            entrypoint.next_up_episodes(params['tagname'],
                                        int(params['limit']))

        elif mode == 'inprogressepisodes':
            entrypoint.in_progress_episodes(params['tagname'],
                                            int(params['limit']))

        elif mode == 'browseplex':
            entrypoint.browse_plex(key=params.get('key'),
                                   plex_section_id=params.get('id'))

        elif mode == 'watchlater':
            entrypoint.watchlater()

        elif mode == 'channels':
            entrypoint.channels()

        elif mode == 'extras':
            entrypoint.extras(plex_id=params.get('plex_id'))

        elif mode == 'settings':
            executebuiltin('Addon.OpenSettings(%s)' % v.ADDON_ID)

        elif mode == 'enterPMS':
            entrypoint.create_new_pms()

        elif mode == 'reset':
            utils.reset()

        elif mode == 'togglePlexTV':
            entrypoint.toggle_plex_tv_sign_in()

        elif mode == 'resetauth':
            entrypoint.reset_authorization()

        elif mode == 'passwords':
            utils.passwords_xml()

        elif mode == 'switchuser':
            entrypoint.switch_plex_user()

        elif mode in ('manualsync', 'repair'):
            if pickler.pickl_window('plex_online') != 'true':
                # Server is not online, do not run the sync
                utils.dialog('ok', utils.lang(29999), utils.lang(39205))
                log.error('Not connected to a PMS.')
            else:
                if mode == 'repair':
                    log.info('Requesting repair lib sync')
                    utils.plex_command('RUN_LIB_SCAN', 'repair')
                elif mode == 'manualsync':
                    log.info('Requesting full library scan')
                    utils.plex_command('RUN_LIB_SCAN', 'full')

        elif mode == 'texturecache':
            log.info('Requesting texture caching of all textures')
            utils.plex_command('RUN_LIB_SCAN', 'textures')

        elif mode == 'chooseServer':
            entrypoint.choose_pms_server()

        elif mode == 'refreshplaylist':
            log.info('Requesting playlist/nodes refresh')
            utils.plex_command('RUN_LIB_SCAN', 'views')

        elif mode == 'deviceid':
            self.deviceid()

        elif mode == 'fanart':
            log.info('User requested fanarttv refresh')
            utils.plex_command('RUN_LIB_SCAN', 'fanart')

        elif '/extrafanart' in path:
            plexpath = arguments[1:]
            plexid = itemid
            entrypoint.extra_fanart(plexid, plexpath)
            entrypoint.get_video_files(plexid, plexpath)

        # Called by e.g. 3rd party plugin video extras
        elif ('/Extras' in path or '/VideoFiles' in path or
                '/Extras' in arguments):
            plexId = itemid or None
            entrypoint.get_video_files(plexId, params)

        elif mode == 'playlists':
            entrypoint.playlists(params.get('content_type'))

        elif mode == 'hub':
            entrypoint.hub(params.get('type'))

        else:
            entrypoint.show_main_menu(content_type=params.get('content_type'))

    @staticmethod
    def play():
        """
        Start up playback_starter in main Python thread
        """
        request = '%s&handle=%s' % (argv[2], HANDLE)
        # Put the request into the 'queue'
        utils.plex_command('PLAY', request)
        if HANDLE == -1:
            # Handle -1 received, not waiting for main thread
            return
        # Wait for the result
        while not pickler.pickl_window('plex_result'):
            sleep(50)
        result = pickler.unpickle_me()
        if result is None:
            log.error('Error encountered, aborting')
            utils.dialog('notification',
                         heading='{plex}',
                         message=utils.lang(30128),
                         icon='{error}',
                         time=3000)
            setResolvedUrl(HANDLE, False, ListItem())
        elif result.listitem:
            listitem = pkc_listitem.convert_pkc_to_listitem(result.listitem)
            setResolvedUrl(HANDLE, True, listitem)

    @staticmethod
    def deviceid():
        deviceId_old = pickler.pickl_window('plex_client_Id')
        from resources.lib import clientinfo
        try:
            deviceId = clientinfo.getDeviceId(reset=True)
        except Exception as e:
            log.error('Failed to generate a new device Id: %s' % e)
            utils.dialog('ok', utils.lang(29999), utils.lang(33032))
        else:
            log.info('Successfully removed old device ID: %s New deviceId:'
                     '%s' % (deviceId_old, deviceId))
            # 'Kodi will now restart to apply the changes'
            utils.dialog('ok', utils.lang(29999), utils.lang(33033))
            executebuiltin('RestartApp')


if __name__ == '__main__':
    log.info('%s started' % v.ADDON_ID)
    Main()
    log.info('%s stopped' % v.ADDON_ID)
