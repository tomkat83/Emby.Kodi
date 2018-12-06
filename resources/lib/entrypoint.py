#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Loads of different functions called in SEPARATE Python instances through
e.g. plugin://... calls. Hence be careful to only rely on window variables.
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from sys import argv
from urllib import urlencode
import xbmcplugin
from xbmc import sleep, executebuiltin
from xbmcgui import ListItem

from . import utils
from . import path_ops
from . import initialsetup
from .downloadutils import DownloadUtils as DU
from .plex_api import API
from . import plex_functions as PF
from . import json_rpc as js
from . import variables as v
# Be careful - your using state in another Python instance!
from . import state

###############################################################################
LOG = getLogger('PLEX.entrypoint')

###############################################################################


def choose_pms_server():
    """
    Lets user choose from list of PMS
    """
    LOG.info("Choosing PMS server requested, starting")

    setup = initialsetup.InitialSetup()
    server = setup.pick_pms(showDialog=True)
    if server is None:
        LOG.error('We did not connect to a new PMS, aborting')
        utils.plex_command('SUSPEND_USER_CLIENT', 'False')
        utils.plex_command('SUSPEND_LIBRARY_THREAD', 'False')
        return

    LOG.info("User chose server %s", server['name'])
    setup.write_pms_to_settings(server)

    if not _log_out():
        return

    # Wipe Kodi and Plex database as well as playlists and video nodes
    utils.wipe_database()

    # Log in again
    _log_in()
    LOG.info("Choosing new PMS complete")
    # '<PMS> connected'
    utils.dialog('notification',
                 utils.lang(29999),
                 '%s %s' % (server['name'], utils.lang(39220)),
                 icon='{plex}',
                 time=3000,
                 sound=False)


def toggle_plex_tv_sign_in():
    """
    Signs out of Plex.tv if there was a token saved and thus deletes the token.
    Or signs in to plex.tv if the user was not logged in before.
    """
    if utils.settings('plexToken'):
        LOG.info('Reseting plex.tv credentials in settings')
        utils.settings('plexLogin', value="")
        utils.settings('plexToken', value="")
        utils.settings('plexid', value="")
        utils.settings('plexAvatar', value="")
        utils.settings('plex_status', value=utils.lang(39226))

        utils.window('plex_token', clear=True)
        utils.plex_command('PLEX_TOKEN', '')
        utils.plex_command('PLEX_USERNAME', '')
    else:
        LOG.info('Login to plex.tv')
        initialsetup.InitialSetup().plex_tv_sign_in()
    utils.dialog('notification',
                 utils.lang(29999),
                 utils.lang(39221),
                 icon='{plex}',
                 time=3000,
                 sound=False)


def reset_authorization():
    """
    User tried login and failed too many times. Reset # of logins
    """
    if utils.yesno_dialog(utils.lang(29999), utils.lang(39206)):
        LOG.info("Reset login attempts.")
        utils.plex_command('PMS_STATUS', 'Auth')
    else:
        executebuiltin('Addon.OpenSettings(plugin.video.plexkodiconnect)')


def directory_item(label, path, folder=True):
    """
    Adds a xbmcplugin.addDirectoryItem() directory itemlistitem
    """
    listitem = ListItem(label, path=path)
    listitem.setThumbnailImage(
        "special://home/addons/plugin.video.plexkodiconnect/icon.png")
    listitem.setArt(
        {"fanart": "special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    listitem.setArt(
        {"landscape":"special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                url=path,
                                listitem=listitem,
                                isFolder=folder)


def show_main_menu(content_type=None):
    """
    Shows the main PKC menu listing with all libraries, Channel, settings, etc.
    """
    LOG.debug('Do main listing with content_type: %s', content_type)
    xbmcplugin.setContent(int(argv[1]), 'files')
    # Get emby nodes from the window props
    plexprops = utils.window('Plex.nodes.total')
    if plexprops:
        totalnodes = int(plexprops)
        for i in range(totalnodes):
            path = utils.window('Plex.nodes.%s.index' % i)
            if not path:
                path = utils.window('Plex.nodes.%s.content' % i)
                if not path:
                    continue
            label = utils.window('Plex.nodes.%s.title' % i)
            node_type = utils.window('Plex.nodes.%s.type' % i)
            # because we do not use seperate entrypoints for each content type,
            # we need to figure out which items to show in each listing. for
            # now we just only show picture nodes in the picture library video
            # nodes in the video library and all nodes in any other window
            if node_type == 'photos' and content_type == 'image':
                directory_item(label, path)
            elif node_type == 'albums' and content_type == 'audio':
                directory_item(label, path)
            elif node_type in ('movies',
                               'tvshows',
                               'homevideos',
                               'musicvideos') and content_type == 'video':
                directory_item(label, path)
    # Playlists
    if content_type != 'image':
        directory_item(utils.lang(136),
                       ('plugin://%s?mode=playlists&content_type=%s'
                        % (v.ADDON_ID, content_type)))
    # Plex Hub
    directory_item('Plex Hub',
                   'plugin://%s?mode=hub&type=%s' % (v.ADDON_ID, content_type))
    # Plex Watch later
    if content_type not in ('image', 'audio'):
        directory_item(utils.lang(39211),
                       "plugin://%s?mode=watchlater" % v.ADDON_ID)
    # Plex Channels
    directory_item(utils.lang(30173), "plugin://%s?mode=channels" % v.ADDON_ID)
    # Plex user switch
    directory_item('%s%s' % (utils.lang(39200), utils.settings('username')),
                   "plugin://%s?mode=switchuser" % v.ADDON_ID)

    # some extra entries for settings and stuff
    directory_item(utils.lang(39201), "plugin://%s?mode=settings" % v.ADDON_ID)
    directory_item(utils.lang(39203),
                   "plugin://%s?mode=refreshplaylist" % v.ADDON_ID)
    directory_item(utils.lang(39204),
                   "plugin://%s?mode=manualsync" % v.ADDON_ID)
    xbmcplugin.endOfDirectory(int(argv[1]))


def switch_plex_user():
    """
    Signs out currently logged in user (if applicable). Triggers sign-in of a
    new user
    """
    # Guess these user avatars are a future feature. Skipping for now
    # Delete any userimages. Since there's always only 1 user: position = 0
    # position = 0
    # utils.window('EmbyAdditionalUserImage.%s' % position, clear=True)
    LOG.info("Plex home user switch requested")
    if not _log_out():
        return
    # First remove playlists of old user
    utils.delete_playlists()
    # Remove video nodes
    utils.delete_nodes()
    _log_in()


def create_listitem(item, append_show_title=False, append_sxxexx=False):
    """
    Feed with a Kodi json item response to get a xbmcgui.ListItem() with
    everything set and ready.
    """
    title = item['title']
    listitem = ListItem(title)
    listitem.setProperty('IsPlayable', 'true')
    metadata = {
        'duration': str(item['runtime'] / 60),
        'Plot': item['plot'],
        'Playcount': item['playcount']
    }
    if 'episode' in item:
        episode = item['episode']
        metadata['Episode'] = episode
    if 'season' in item:
        season = item['season']
        metadata['Season'] = season
    if season and episode:
        listitem.setProperty('episodeno', 's%.2de%.2d' % (season, episode))
        if append_sxxexx is True:
            title = 'S%.2dE%.2d - %s' % (season, episode, title)
    if 'firstaired' in item:
        metadata['Premiered'] = item['firstaired']
    if 'showtitle' in item:
        metadata['TVshowTitle'] = item['showtitle']
        if append_show_title is True:
            title = item['showtitle'] + ' - ' + title
    if 'rating' in item:
        metadata['Rating'] = str(round(float(item['rating']), 1))
    if 'director' in item:
        metadata['Director'] = item['director']
    if 'writer' in item:
        metadata['Writer'] = item['writer']
    if 'cast' in item:
        cast = []
        castandrole = []
        for person in item['cast']:
            name = person['name']
            cast.append(name)
            castandrole.append((name, person['role']))
        metadata['Cast'] = cast
        metadata['CastAndRole'] = castandrole

    metadata['Title'] = title
    metadata['mediatype'] = 'episode'
    metadata['dbid'] = str(item['episodeid'])
    listitem.setLabel(title)
    listitem.setInfo(type='Video', infoLabels=metadata)

    listitem.setProperty('resumetime', str(item['resume']['position']))
    listitem.setProperty('totaltime', str(item['resume']['total']))
    listitem.setArt(item['art'])
    listitem.setThumbnailImage(item['art'].get('thumb', ''))
    listitem.setArt({'icon': 'DefaultTVShows.png'})
    listitem.setProperty('fanart_image', item['art'].get('tvshow.fanart', ''))
    try:
        listitem.addContextMenuItems([(utils.lang(30032),
                                       'XBMC.Action(Info)',)])
    except TypeError:
        # Kodi fuck-up
        pass
    for key, value in item['streamdetails'].iteritems():
        for stream in value:
            listitem.addStreamInfo(key, stream)
    return listitem


def next_up_episodes(tagname, limit):
    """
    List the next up episodes for tagname.
    """
    count = 0
    # if the addon is called with nextup parameter,
    # we return the nextepisodes list of the given tagname
    xbmcplugin.setContent(int(argv[1]), 'episodes')
    # First we get a list of all the TV shows - filtered by tag
    params = {
        'sort': {'order': "descending", 'method': "lastplayed"},
        'filter': {
            'and': [
                {'operator': "true", 'field': "inprogress", 'value': ""},
                {'operator': "is", 'field': "tag", 'value': "%s" % tagname}
            ]},
        'properties': ['title', 'studio', 'mpaa', 'file', 'art']
    }
    for item in js.get_tv_shows(params):
        if utils.settings('ignoreSpecialsNextEpisodes') == "true":
            params = {
                'tvshowid': item['tvshowid'],
                'sort': {'method': "episode"},
                'filter': {
                    'and': [
                        {'operator': "lessthan",
                         'field': "playcount",
                         'value': "1"},
                        {'operator': "greaterthan",
                         'field': "season",
                         'value': "0"}]},
                'properties': [
                    "title", "playcount", "season", "episode", "showtitle",
                    "plot", "file", "rating", "resume", "tvshowid", "art",
                    "streamdetails", "firstaired", "runtime", "writer",
                    "dateadded", "lastplayed"
                ],
                'limits': {"end": 1}
            }
        else:
            params = {
                'tvshowid': item['tvshowid'],
                'sort': {'method': "episode"},
                'filter': {
                    'operator': "lessthan",
                    'field': "playcount",
                    'value': "1"},
                'properties': [
                    "title", "playcount", "season", "episode", "showtitle",
                    "plot", "file", "rating", "resume", "tvshowid", "art",
                    "streamdetails", "firstaired", "runtime", "writer",
                    "dateadded", "lastplayed"
                ],
                'limits': {"end": 1}
            }
        for episode in js.get_episodes(params):
            xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                        url=episode['file'],
                                        listitem=create_listitem(episode))
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=int(argv[1]))


def in_progress_episodes(tagname, limit):
    """
    List the episodes that are in progress for tagname
    """
    count = 0
    # if the addon is called with inprogressepisodes parameter,
    # we return the inprogressepisodes list of the given tagname
    xbmcplugin.setContent(int(argv[1]), 'episodes')
    # First we get a list of all the in-progress TV shows - filtered by tag
    params = {
        'sort': {'order': "descending", 'method': "lastplayed"},
        'filter': {
            'and': [
                {'operator': "true", 'field': "inprogress", 'value': ""},
                {'operator': "is", 'field': "tag", 'value': "%s" % tagname}
            ]},
        'properties': ['title', 'studio', 'mpaa', 'file', 'art']
    }
    for item in js.get_tv_shows(params):
        params = {
            'tvshowid': item['tvshowid'],
            'sort': {'method': "episode"},
            'filter': {
                'operator': "true",
                'field': "inprogress",
                'value': ""},
            'properties': ["title", "playcount", "season", "episode",
                           "showtitle", "plot", "file", "rating", "resume",
                           "tvshowid", "art", "cast", "streamdetails",
                           "firstaired", "runtime", "writer", "dateadded",
                           "lastplayed"]
        }
        for episode in js.get_episodes(params):
            xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                        url=episode['file'],
                                        listitem=create_listitem(episode))
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=int(argv[1]))


def recent_episodes(mediatype, tagname, limit):
    """
    List the recently added episodes for tagname
    """
    count = 0
    # if the addon is called with recentepisodes parameter,
    # we return the recentepisodes list of the given tagname
    xbmcplugin.setContent(int(argv[1]), 'episodes')
    append_show_title = utils.settings('RecentTvAppendShow') == 'true'
    append_sxxexx = utils.settings('RecentTvAppendSeason') == 'true'
    # First we get a list of all the TV shows - filtered by tag
    show_ids = set()
    params = {
        'sort': {'order': "descending", 'method': "dateadded"},
        'filter': {'operator': "is", 'field': "tag", 'value': "%s" % tagname},
    }
    for tv_show in js.get_tv_shows(params):
        show_ids.add(tv_show['tvshowid'])
    params = {
        'sort': {'order': "descending", 'method': "dateadded"},
        'properties': ["title", "playcount", "season", "episode", "showtitle",
            "plot", "file", "rating", "resume", "tvshowid", "art",
            "streamdetails", "firstaired", "runtime", "cast", "writer",
            "dateadded", "lastplayed"],
        "limits": {"end": limit}
    }
    if utils.settings('TVShowWatched') == 'false':
        params['filter'] = {
            'operator': "lessthan",
            'field': "playcount",
            'value': "1"
        }
    for episode in js.get_episodes(params):
        if episode['tvshowid'] in show_ids:
            listitem = create_listitem(episode,
                                       append_show_title=append_show_title,
                                       append_sxxexx=append_sxxexx)
            xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                        url=episode['file'],
                                        listitem=listitem)
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=int(argv[1]))


def get_video_files(plex_id, params):
    """
    GET VIDEO EXTRAS FOR LISTITEM

    returns the video files for the item as plugin listing, can be used for
    browsing the actual files or videoextras etc.
    """
    if plex_id is None:
        filename = params.get('filename')
        if filename is not None:
            filename = filename[0]
            import re
            regex = re.compile(r'''library/metadata/(\d+)''')
            filename = regex.findall(filename)
            try:
                plex_id = filename[0]
            except IndexError:
                pass

    if plex_id is None:
        LOG.info('No Plex ID found, abort getting Extras')
        return xbmcplugin.endOfDirectory(int(argv[1]))

    item = PF.GetPlexMetadata(plex_id)
    try:
        path = utils.try_decode(item[0][0][0].attrib['file'])
    except (TypeError, IndexError, AttributeError, KeyError):
        LOG.error('Could not get file path for item %s', plex_id)
        return xbmcplugin.endOfDirectory(int(argv[1]))
    # Assign network protocol
    if path.startswith('\\\\'):
        path = path.replace('\\\\', 'smb://')
        path = path.replace('\\', '/')
    # Plex returns Windows paths as e.g. 'c:\slfkjelf\slfje\file.mkv'
    elif '\\' in path:
        path = path.replace('\\', '\\\\')
    # Directory only, get rid of filename
    path = path.replace(path_ops.path.basename(path), '')
    if path_ops.exists(path):
        for root, dirs, files in path_ops.walk(path):
            for directory in dirs:
                item_path = utils.try_encode(path_ops.path.join(root,
                                                                directory))
                listitem = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                            url=item_path,
                                            listitem=listitem,
                                            isFolder=True)
            for file in files:
                item_path = utils.try_encode(path_ops.path.join(root, file))
                listitem = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                            url=file,
                                            listitem=listitem)
            break
    else:
        LOG.error('Kodi cannot access folder %s', path)
    xbmcplugin.endOfDirectory(int(argv[1]))


@utils.catch_exceptions(warnuser=False)
def extra_fanart(plex_id, plex_path):
    """
    Get extrafanart for listitem
    will be called by skinhelper script to get the extrafanart
    for tvshows we get the plex_id just from the path
    """
    LOG.debug('Called with plex_id: %s, plex_path: %s', plex_id, plex_path)
    if not plex_id:
        if "plugin.video.plexkodiconnect" in plex_path:
            plex_id = plex_path.split("/")[-2]
    if not plex_id:
        LOG.error('Could not get a plex_id, aborting')
        return xbmcplugin.endOfDirectory(int(argv[1]))

    # We need to store the images locally for this to work
    # because of the caching system in xbmc
    fanart_dir = path_ops.translate_path("special://thumbnails/plex/%s/"
                                         % plex_id)
    if not path_ops.exists(fanart_dir):
        # Download the images to the cache directory
        path_ops.makedirs(fanart_dir)
        xml = PF.GetPlexMetadata(plex_id)
        if xml is None:
            LOG.error('Could not download metadata for %s', plex_id)
            return xbmcplugin.endOfDirectory(int(argv[1]))

        api = API(xml[0])
        backdrops = api.artwork()['Backdrop']
        for count, backdrop in enumerate(backdrops):
            # Same ordering as in artwork
            art_file = utils.try_encode(path_ops.path.join(
                fanart_dir, "fanart%.3d.jpg" % count))
            listitem = ListItem("%.3d" % count, path=art_file)
            xbmcplugin.addDirectoryItem(
                handle=int(argv[1]),
                url=art_file,
                listitem=listitem)
            path_ops.copyfile(backdrop, utils.try_decode(art_file))
    else:
        LOG.info("Found cached backdrop.")
        # Use existing cached images
        fanart_dir = utils.try_decode(fanart_dir)
        for root, _, files in path_ops.walk(fanart_dir):
            root = utils.decode_path(root)
            for file in files:
                file = utils.decode_path(file)
                art_file = utils.try_encode(path_ops.path.join(root, file))
                listitem = ListItem(file, path=art_file)
                xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                            url=art_file,
                                            listitem=listitem)
    xbmcplugin.endOfDirectory(int(argv[1]))


def _wait_for_auth():
    """
    Call to be sure that PKC is authenticated, e.g. for widgets on Kodi
    startup. Will wait for at most 30s, then fail if not authenticated.

    Will set xbmcplugin.endOfDirectory(int(argv[1]), False) if failed
    """
    counter = 0
    while utils.window('plex_authenticated') != 'true':
        counter += 1
        if counter == 300:
            LOG.error('Aborting view, we were not authenticated for PMS')
            xbmcplugin.endOfDirectory(int(argv[1]), False)
            return False
        sleep(100)
    return True


def on_deck_episodes(viewid, tagname, limit):
    """
    Retrieves Plex On Deck items, currently only for TV shows

    Input:
        viewid:             Plex id of the library section, e.g. '1'
        tagname:            Name of the Plex library, e.g. "My Movies"
        limit:              Max. number of items to retrieve, e.g. 50
    """
    xbmcplugin.setContent(int(argv[1]), 'episodes')
    append_show_title = utils.settings('OnDeckTvAppendShow') == 'true'
    append_sxxexx = utils.settings('OnDeckTvAppendSeason') == 'true'
    if utils.settings('OnDeckTVextended') == 'false':
        # Chances are that this view is used on Kodi startup
        # Wait till we've connected to a PMS. At most 30s
        if not _wait_for_auth():
            return
        xml = DU().downloadUrl('{server}/library/sections/%s/onDeck' % viewid)
        if xml in (None, 401):
            LOG.error('Could not download PMS xml for view %s', viewid)
            xbmcplugin.endOfDirectory(int(argv[1]), False)
            return
        # We're using another python instance - need to load some vars
        if utils.settings('useDirectPaths') == '1':
            state.DIRECT_PATHS = True
            state.REPLACE_SMB_PATH = utils.settings('replaceSMB') == 'true'
            state.REMAP_PATH = utils.settings('remapSMB') == 'true'
            if state.REMAP_PATH:
                initialsetup.set_replace_paths()
            # Let's NOT check paths for widgets!
            state.PATH_VERIFIED = True
        counter = 0
        for item in xml:
            api = API(item)
            listitem = api.create_listitem(
                append_show_title=append_show_title,
                append_sxxexx=append_sxxexx)
            if api.resume_point():
                listitem.setProperty('resumetime', str(api.resume_point()))
            path = api.path(force_first_media=True)
            xbmcplugin.addDirectoryItem(
                handle=int(argv[1]),
                url=path,
                listitem=listitem)
            counter += 1
            if counter == limit:
                break
        xbmcplugin.endOfDirectory(
            handle=int(argv[1]),
            cacheToDisc=utils.settings('enableTextureCache') == 'true')
        return

    # if the addon is called with nextup parameter,
    # we return the nextepisodes list of the given tagname
    # First we get a list of all the TV shows - filtered by tag
    params = {
        'sort': {'order': "descending", 'method': "lastplayed"},
        'filter': {
            'and': [
                {'operator': "true", 'field': "inprogress", 'value': ""},
                {'operator': "is", 'field': "tag", 'value': "%s" % tagname}
            ]}
    }
    items = js.get_tv_shows(params)
    if not items:
        # Now items retrieved - empty directory
        xbmcplugin.endOfDirectory(handle=int(argv[1]))
        return

    params = {
        'sort': {'method': "episode"},
        'limits': {"end": 1},
        'properties': [
            "title", "playcount", "season", "episode", "showtitle",
            "plot", "file", "rating", "resume", "tvshowid", "art",
            "streamdetails", "firstaired", "runtime", "cast", "writer",
            "dateadded", "lastplayed"
        ],
    }
    if utils.settings('ignoreSpecialsNextEpisodes') == "true":
        params['filter'] = {
            'and': [
                {'operator': "lessthan", 'field': "playcount", 'value': "1"},
                {'operator': "greaterthan", 'field': "season", 'value': "0"}
            ]
        }
    else:
        params['filter'] = {
            'or': [
                {'operator': "lessthan", 'field': "playcount", 'value': "1"},
                {'operator': "true", 'field': "inprogress", 'value': ""}
            ]
        }

    # Are there any episodes still in progress/not yet finished watching?!?
    # Then we should show this episode, NOT the "next up"
    inprog_params = {
        'sort': {'method': "episode"},
        'filter': {'operator': "true", 'field': "inprogress", 'value': ""},
        'properties': params['properties']
    }

    count = 0
    for item in items:
        inprog_params['tvshowid'] = item['tvshowid']
        episodes = js.get_episodes(inprog_params)
        if not episodes:
            # No, there are no episodes not yet finished. Get "next up"
            params['tvshowid'] = item['tvshowid']
            episodes = js.get_episodes(params)
            if not episodes:
                # Also no episodes currently coming up
                continue
        for episode in episodes:
            # There will always be only 1 episode ('limit=1')
            listitem = create_listitem(episode,
                                       append_show_title=append_show_title,
                                       append_sxxexx=append_sxxexx)
            xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                        url=episode['file'],
                                        listitem=listitem,
                                        isFolder=False)
        count += 1
        if count >= limit:
            break
    xbmcplugin.endOfDirectory(handle=int(argv[1]))


def playlists(content_type):
    """
    Lists all Plex playlists of the media type plex_playlist_type
    content_type: 'audio', 'video'
    """
    LOG.debug('Listing Plex %s playlists', content_type)
    if not _wait_for_auth():
        return
    xbmcplugin.setContent(int(argv[1]), 'files')
    from .playlists.pms import all_playlists
    xml = all_playlists()
    if xml is None:
        return
    for item in xml:
        api = API(item)
        if not api.playlist_type() == content_type:
            continue
        listitem = ListItem(api.title())
        listitem.setArt({'thumb': api.one_artwork('composite')})
        url = "plugin://%s/" % v.ADDON_ID
        key = api.path_and_plex_id()
        params = {
            'mode': "browseplex",
            'key': key,
        }
        xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                    url="%s?%s" % (url, urlencode(params)),
                                    isFolder=True,
                                    listitem=listitem)
    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def hub(content_type):
    """
    Plus hub endpoint pms:port/hubs. Need to separate Kodi types with
    content_type:
        audio, video, image
    """
    xml = PF.get_plex_hub()
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not get Plex hub listing')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)
    for entry in xml:
        api = API(entry)
        if content_type == 'video' and api.plex_type() in v.PLEX_VIDEOTYPES:
            __build_folder(entry)
        elif content_type == 'audio' and api.plex_type() in v.PLEX_AUDIOTYPES:
            __build_folder(entry)
        elif content_type == 'image' and api.plex_type() == v.PLEX_TYPE_PHOTO:
            __build_folder(entry)
    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def watchlater():
    """
    Listing for plex.tv Watch Later section (if signed in to plex.tv)
    """
    if utils.window('plex_token') == '':
        LOG.error('No watch later - not signed in to plex.tv')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)
    if utils.window('plex_restricteduser') == 'true':
        LOG.error('No watch later - restricted user')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)

    xml = DU().downloadUrl('https://plex.tv/pms/playlists/queue/all',
                           authenticate=False,
                           headerOptions={'X-Plex-Token': utils.window('plex_token')})
    if xml in (None, 401):
        LOG.error('Could not download watch later list from plex.tv')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)

    LOG.info('Displaying watch later plex.tv items')
    xbmcplugin.setContent(int(argv[1]), 'movies')
    direct_paths = utils.settings('useDirectPaths') == '1'
    for item in xml:
        __build_item(item, direct_paths)
    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def channels():
    """
    Listing for Plex Channels
    """
    xml = DU().downloadUrl('{server}/channels/all')
    try:
        xml[0].attrib
    except (ValueError, AttributeError, IndexError, TypeError):
        LOG.error('Could not download Plex Channels')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)

    LOG.info('Displaying Plex Channels')
    xbmcplugin.setContent(int(argv[1]), 'files')
    for method in v.SORT_METHODS_DIRECTORY:
        xbmcplugin.addSortMethod(int(argv[1]), getattr(xbmcplugin, method))
    for item in xml:
        __build_folder(item)
    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def browse_plex(key=None, plex_section_id=None):
    """
    Lists the content of a Plex folder, e.g. channels. Either pass in key (to
    be used directly for PMS url {server}<key>) or the plex_section_id
    """
    LOG.debug('Browsing to key %s, section %s', key, plex_section_id)
    if key:
        xml = DU().downloadUrl('{server}%s' % key)
    else:
        xml = PF.GetPlexSectionResults(plex_section_id)
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not browse to key %s, section %s',
                  key, plex_section_id)
        return xbmcplugin.endOfDirectory(int(argv[1]), False)

    photos = False
    movies = False
    clips = False
    tvshows = False
    episodes = False
    songs = False
    artists = False
    albums = False
    musicvideos = False
    direct_paths = utils.settings('useDirectPaths') == '1'
    for item in xml:
        if item.tag == 'Directory':
            __build_folder(item, plex_section_id=plex_section_id)
        else:
            typus = item.attrib.get('type')
            __build_item(item, direct_paths)
            if typus == v.PLEX_TYPE_PHOTO:
                photos = True
            elif typus == v.PLEX_TYPE_MOVIE:
                movies = True
            elif typus == v.PLEX_TYPE_CLIP:
                clips = True
            elif typus in (v.PLEX_TYPE_SHOW, v.PLEX_TYPE_SEASON):
                tvshows = True
            elif typus == v.PLEX_TYPE_EPISODE:
                episodes = True
            elif typus == v.PLEX_TYPE_SONG:
                songs = True
            elif typus == v.PLEX_TYPE_ARTIST:
                artists = True
            elif typus == v.PLEX_TYPE_ALBUM:
                albums = True
            elif typus == v.PLEX_TYPE_MUSICVIDEO:
                musicvideos = True

    # Set the correct content type
    if movies is True:
        LOG.debug('Setting view to movies')
        xbmcplugin.setContent(int(argv[1]), 'movies')
        sort_methods = v.SORT_METHODS_MOVIES
    elif clips is True:
        LOG.debug('Clips -> Setting view to movies')
        xbmcplugin.setContent(int(argv[1]), 'movies')
        sort_methods = v.SORT_METHODS_CLIPS
    elif photos is True:
        LOG.debug('Setting view to images')
        xbmcplugin.setContent(int(argv[1]), 'images')
        sort_methods = v.SORT_METHODS_PHOTOS
    elif tvshows is True:
        LOG.debug('Setting view to tvshows')
        xbmcplugin.setContent(int(argv[1]), 'tvshows')
        sort_methods = v.SORT_METHOD_TVSHOWS
    elif episodes is True:
        LOG.debug('Setting view to episodes')
        xbmcplugin.setContent(int(argv[1]), 'episodes')
        sort_methods = v.SORT_METHODS_EPISODES
    elif songs is True:
        LOG.debug('Setting view to songs')
        xbmcplugin.setContent(int(argv[1]), 'songs')
        sort_methods = v.SORT_METHODS_SONGS
    elif artists is True:
        LOG.debug('Setting view to artists')
        xbmcplugin.setContent(int(argv[1]), 'artists')
        sort_methods = v.SORT_METHODS_ARTISTS
    elif albums is True:
        LOG.debug('Setting view to albums')
        xbmcplugin.setContent(int(argv[1]), 'albums')
        sort_methods = v.SORT_METHODS_ALBUMS
    elif musicvideos is True:
        LOG.debug('Setting view to musicvideos')
        xbmcplugin.setContent(int(argv[1]), 'musicvideos')
        sort_methods = v.SORT_METHODS_MOVIES
    else:
        LOG.debug('Setting view to files')
        xbmcplugin.setContent(int(argv[1]), 'files')
        sort_methods = v.SORT_METHODS_DIRECTORY

    for method in sort_methods:
        LOG.debug('Adding Kodi sort method %s', method)
        xbmcplugin.addSortMethod(int(argv[1]), getattr(xbmcplugin, method))

    # Set the Kodi title for this view
    title = xml.attrib.get('librarySectionTitle', xml.attrib.get('title1'))
    xbmcplugin.setPluginCategory(int(argv[1]), title)

    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=utils.settings('enableTextureCache') == 'true')


def __build_folder(xml_element, plex_section_id=None):
    url = "plugin://%s/" % v.ADDON_ID
    key = xml_element.get('fastKey', xml_element.get('key'))
    if not key.startswith('/'):
        key = '/library/sections/%s/%s' % (plex_section_id, key)
    params = {
        'mode': "browseplex",
        'key': key,
    }
    if plex_section_id:
        params['id'] = plex_section_id
    listitem = ListItem(xml_element.get('title'))
    thumb = xml_element.get('thumb') or \
        'special://home/addons/%s/icon.png' % v.ADDON_ID
    art = xml_element.get('art') or \
        'special://home/addons/%s/fanart.jpg' % v.ADDON_ID
    listitem.setThumbnailImage(thumb)
    listitem.setArt({'fanart': art, 'landscape': art})
    xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                url="%s?%s" % (url, urlencode(params)),
                                isFolder=True,
                                listitem=listitem)


def __build_item(xml_element, direct_paths):
    api = API(xml_element)
    listitem = api.create_listitem()
    resume = api.resume_point()
    if resume:
        listitem.setProperty('resumetime', str(resume))
    if (api.path_and_plex_id().startswith('/system/services') or
            api.path_and_plex_id().startswith('http')):
        params = {
            'mode': 'plex_node',
            'key': xml_element.attrib.get('key'),
            'offset': xml_element.attrib.get('viewOffset', '0'),
        }
        url = "plugin://%s?%s" % (v.ADDON_ID, urlencode(params))
    elif api.plex_type() == v.PLEX_TYPE_PHOTO:
        url = api.get_picture_path()
    else:
        url = api.path(direct_paths=direct_paths)
    xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                url=url,
                                listitem=listitem)


def extras(plex_id):
    """
    Lists all extras for plex_id
    """
    xbmcplugin.setContent(int(argv[1]), 'movies')
    xml = PF.GetPlexMetadata(plex_id)
    try:
        xml[0].attrib
    except (TypeError, IndexError, KeyError):
        xbmcplugin.endOfDirectory(int(argv[1]))
        return
    for item in API(xml[0]).extras():
        api = API(item)
        listitem = api.create_listitem()
        xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                    url=api.path(),
                                    listitem=listitem)
    xbmcplugin.endOfDirectory(int(argv[1]))


def create_new_pms():
    """
    Opens dialogs for the user the plug in the PMS details
    """
    # "Enter your Plex Media Server's IP or URL. Examples are:"
    utils.messageDialog(utils.lang(29999),
                        '%s\n%s\n%s' % (utils.lang(39215),
                                        '192.168.1.2',
                                        'plex.myServer.org'))
    address = utils.dialog('input', "Enter PMS IP or URL")
    if address == '':
        return
    port = utils.dialog('input', "Enter PMS port", '32400', type='{numeric}')
    if port == '':
        return
    url = '%s:%s' % (address, port)
    # "Does your Plex Media Server support SSL connections?
    # (https instead of http)"
    https = utils.yesno_dialog(utils.lang(29999), utils.lang(39217))
    if https:
        url = 'https://%s' % url
    else:
        url = 'http://%s' % url
    https = 'true' if https else 'false'
    machine_identifier = PF.GetMachineIdentifier(url)
    if machine_identifier is None:
        # "Error contacting url
        # Abort (Yes) or save address anyway (No)"
        if utils.yesno_dialog(utils.lang(29999),
                              '%s %s. %s' % (utils.lang(39218),
                                             url,
                                             utils.lang(39219))):
            return
        else:
            utils.settings('plex_machineIdentifier', '')
    else:
        utils.settings('plex_machineIdentifier', machine_identifier)
    LOG.info('Set new PMS to https %s, address %s, port %s, machineId %s',
             https, address, port, machine_identifier)
    utils.settings('https', value=https)
    utils.settings('ipaddress', value=address)
    utils.settings('port', value=port)
    # Chances are this is a local PMS, so disable SSL certificate check
    utils.settings('sslverify', value='false')

    # Sign out to trigger new login
    if _log_out():
        # Only login again if logout was successful
        _log_in()


def _log_in():
    """
    Resets (clears) window properties to enable (re-)login

    SUSPEND_LIBRARY_THREAD is set to False in service.py if user was signed
    out!
    """
    utils.plex_command('RUN_LIB_SCAN', 'full')
    # Restart user client
    utils.plex_command('SUSPEND_USER_CLIENT', 'False')


def _log_out():
    """
    Finishes lib scans, logs out user.

    Returns True if successfully signed out, False otherwise
    """
    # Resetting, please wait
    utils.dialog('notification',
                 utils.lang(29999),
                 utils.lang(39207),
                 icon='{plex}',
                 time=3000,
                 sound=False)
    # Pause library sync thread
    utils.plex_command('SUSPEND_LIBRARY_THREAD', 'True')
    # Wait max for 10 seconds for all lib scans to shutdown
    counter = 0
    while utils.window('plex_dbScan') == 'true':
        if counter > 200:
            # Failed to reset PMS and plex.tv connects. Try to restart Kodi.
            utils.messageDialog(utils.lang(29999), utils.lang(39208))
            # Resuming threads, just in case
            utils.plex_command('SUSPEND_LIBRARY_THREAD', 'False')
            LOG.error("Could not stop library sync, aborting")
            return False
        counter += 1
        sleep(50)
    LOG.debug("Successfully stopped library sync")

    counter = 0
    # Log out currently signed in user:
    utils.window('plex_serverStatus', value='401')
    utils.plex_command('PMS_STATUS', '401')
    # Above method needs to have run its course! Hence wait
    while utils.window('plex_serverStatus') == "401":
        if counter > 100:
            # 'Failed to reset PKC. Try to restart Kodi.'
            utils.messageDialog(utils.lang(29999), utils.lang(39208))
            LOG.error("Could not sign out user, aborting")
            return False
        counter += 1
        sleep(50)
    # Suspend the user client during procedure
    utils.plex_command('SUSPEND_USER_CLIENT', 'True')
    return True
