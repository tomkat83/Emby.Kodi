# -*- coding: utf-8 -*-
import logging
from sys import argv
from urllib.parse import parse_qsl

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib import entrypoint, utils, transfer, variables as v, loghandler


loghandler.config()
LOG = logging.getLogger('PLEX.default')


def triage(mode, params, path, arguments, itemid):
    if mode == 'play':
        play()
        return
    elif mode == 'plex_node':
        play()
        return
    elif mode == 'route_to_extras':
        # Hack so we can store this path in the Kodi DB
        handle = ('plugin://%s?mode=extras&plex_id=%s'
                  % (v.ADDON_ID, params.get('plex_id')))
        xbmc.executebuiltin('ActivateWindow(videos,\"%s\",return)' % handle)
        return
    elif mode == 'settings':
        xbmc.executebuiltin('Addon.OpenSettings(%s)' % v.ADDON_ID)
        return
    elif mode == 'enterPMS':
        LOG.info('Request to manually enter new PMS address')
        transfer.plex_command('enter_new_pms_address')
        return
    elif mode == 'reset':
        transfer.plex_command('RESET-PKC')
        return
    elif mode == 'togglePlexTV':
        LOG.info('Toggle of Plex.tv sign-in requested')
        transfer.plex_command('toggle_plex_tv_sign_in')
        return
    elif mode == 'passwords':
        from resources.lib.windows import direct_path_sources
        direct_path_sources.start()
        return
    elif mode == 'switchuser':
        LOG.info('Plex home user switch requested')
        transfer.plex_command('switch_plex_user')
        return
    elif mode in ('manualsync', 'repair'):
        if mode == 'repair':
            LOG.info('Requesting repair lib sync')
            transfer.plex_command('repair-scan')
        elif mode == 'manualsync':
            LOG.info('Requesting full library scan')
            transfer.plex_command('full-scan')
        return
    elif mode == 'texturecache':
        LOG.info('Requesting texture caching of all textures')
        transfer.plex_command('textures-scan')
        return
    elif mode == 'chooseServer':
        LOG.info("Choosing PMS server requested, starting")
        transfer.plex_command('choose_pms_server')
        return
    elif mode == 'deviceid':
        LOG.info('New PKC UUID / unique device id requested')
        transfer.plex_command('generate_new_uuid')
        return
    elif mode == 'fanart':
        LOG.info('User requested fanarttv refresh')
        transfer.plex_command('fanart-scan')
        return
    # Listings: we list ListItems and need to tell Kodi when we're done
    try:
        if mode == 'browseplex':
            entrypoint.browse_plex(key=params.get('key'),
                                   plex_type=params.get('plex_type'),
                                   section_id=params.get('section_id'),
                                   synched=params.get('synched') != 'false',
                                   prompt=params.get('prompt'),
                                   query=params.get('query'))
        elif mode == 'show_section':
            entrypoint.show_section(params.get('section_index'))
        elif mode == 'watchlater':
            entrypoint.watchlater()
        elif mode == 'watchlist':
            entrypoint.watchlist(section_id=params.get('section_id'))
        elif mode == 'channels':
            entrypoint.browse_plex(key='/channels/all')
        elif mode == 'search':
            # "Search"
            entrypoint.browse_plex(key='/hubs/search',
                                   args={'includeCollections': 1,
                                         'includeExternalMedia': 1},
                                   prompt=utils.lang(137),
                                   query=params.get('query'))
        elif mode == 'route_to_extras':
            # Hack so we can store this path in the Kodi DB
            handle = ('plugin://%s?mode=extras&plex_id=%s'
                      % (v.ADDON_ID, params.get('plex_id')))
            xbmc.executebuiltin('ActivateWindow(videos,\"%s\",return)' % handle)

        elif mode == 'extras':
            entrypoint.extras(plex_id=params.get('plex_id'))
        # Called by e.g. 3rd party plugin video extras
        elif ('/Extras' in path or '/VideoFiles' in path or
                '/Extras' in arguments):
            plexId = itemid or None
            entrypoint.get_video_files(plexId, params)
        elif mode == 'playlists':
            entrypoint.playlists(params.get('content_type'))
        elif mode == 'hub':
            entrypoint.hub(params.get('content_type'))
        elif mode == 'select-libraries':
            LOG.info('User requested to select Plex libraries')
            transfer.plex_command('select-libraries')
        elif mode == 'refreshplaylist':
            LOG.info('User requested to refresh Kodi playlists and nodes')
            transfer.plex_command('refreshplaylist')
        elif '/extrafanart' in path:
            plexpath = arguments[1:]
            plexid = itemid
            entrypoint.extra_fanart(plexid, plexpath)
            entrypoint.get_video_files(plexid, plexpath)
        else:
            entrypoint.show_main_menu(content_type=params.get('content_type'))
    except entrypoint.ListingException:
        # Tell Kodi listing is done and we failed
        xbmcplugin.endOfDirectory(int(argv[1]), False)
    else:
        # Tell Kodi listing is done and we were successful
        xbmcplugin.endOfDirectory(int(argv[1]))


def play():
    """
    Start up playback_starter in main Python thread
    """
    request = '%s&handle=%s' % (argv[2], int(argv[1]))
    # Put the request into the 'queue'
    transfer.plex_command('PLAY-%s' % request)
    if int(argv[1]) == -1:
        # Handle -1 received, not waiting for main thread
        return
    # Wait for the result from the main PKC thread
    result = transfer.wait_for_transfer(source='main')
    if result is True:
        xbmcplugin.setResolvedUrl(int(argv[1]), False, xbmcgui.ListItem())
        # Tell main thread that we're done
        transfer.send(True, target='main')
    else:
        # Received a xbmcgui.ListItem()
        xbmcplugin.setResolvedUrl(int(argv[1]), True, result)


def main():
    LOG.debug('Full sys.argv received: %s', argv)
    # Parse parameters that were passed
    params = dict(parse_qsl(argv[2][1:]))
    mode = params.get('mode', '')
    path = argv[0]
    arguments = argv[2]
    itemid = params.get('id', '')
    triage(mode, params, path, arguments, itemid)


if __name__ == '__main__':
    LOG.info('%s started' % v.ADDON_ID)
    try:
        v.database_paths()
    except RuntimeError as err:
        # Database does not exists
        LOG.error('The current Kodi version is incompatible')
        LOG.error('Error: %s', err)
    else:
        main()
    LOG.info('%s stopped' % v.ADDON_ID)
