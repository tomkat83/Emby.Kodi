# -*- coding: utf-8 -*-
#
# Loads of different functions called in SEPARATE Python instances through
# e.g. plugin://... calls. Hence be careful to only rely on window variables.
#
###############################################################################
from logging import getLogger
from shutil import copyfile
from os import walk, makedirs
from os.path import basename, join
from sys import argv
from urllib import urlencode

import xbmcplugin
from xbmc import sleep, executebuiltin, translatePath
from xbmcgui import ListItem

from utils import window, settings, language as lang, dialog, try_encode, \
    catch_exceptions, exists_dir, plex_command, try_decode
import downloadutils
import initialsetup
from PlexFunctions import GetPlexMetadata, GetPlexSectionResults, \
    GetMachineIdentifier
from PlexAPI import API
import json_rpc as js
import variables as v
# Be careful - your using state in another Python instance!
import state

###############################################################################
LOG = getLogger("PLEX." + __name__)

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
        plex_command('SUSPEND_USER_CLIENT', 'False')
        plex_command('SUSPEND_LIBRARY_THREAD', 'False')
        return

    LOG.info("User chose server %s", server['name'])
    setup.write_pms_to_settings(server)

    if not _log_out():
        return

    from utils import wipe_database
    # Wipe Kodi and Plex database as well as playlists and video nodes
    wipe_database()

    # Log in again
    _log_in()
    LOG.info("Choosing new PMS complete")
    # '<PMS> connected'
    dialog('notification',
           lang(29999),
           '%s %s' % (server['name'], lang(39220)),
           icon='{plex}',
           time=3000,
           sound=False)


def toggle_plex_tv_sign_in():
    """
    Signs out of Plex.tv if there was a token saved and thus deletes the token.
    Or signs in to plex.tv if the user was not logged in before.
    """
    if settings('plexToken'):
        LOG.info('Reseting plex.tv credentials in settings')
        settings('plexLogin', value="")
        settings('plexToken', value="")
        settings('plexid', value="")
        settings('plexHomeSize', value="1")
        settings('plexAvatar', value="")
        settings('plex_status', value=lang(39226))

        window('plex_token', clear=True)
        plex_command('PLEX_TOKEN', '')
        plex_command('PLEX_USERNAME', '')
    else:
        LOG.info('Login to plex.tv')
        initialsetup.InitialSetup().plex_tv_sign_in()
    dialog('notification',
           lang(29999),
           lang(39221),
           icon='{plex}',
           time=3000,
           sound=False)


def reset_authorization():
    """
    User tried login and failed too many times. Reset # of logins
    """
    resp = dialog('yesno', heading="{plex}", line1=lang(39206))
    if resp == 1:
        LOG.info("Reset login attempts.")
        plex_command('PMS_STATUS', 'Auth')
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
    plexprops = window('Plex.nodes.total')
    if plexprops:
        totalnodes = int(plexprops)
        for i in range(totalnodes):
            path = window('Plex.nodes.%s.index' % i)
            if not path:
                path = window('Plex.nodes.%s.content' % i)
                if not path:
                    continue
            label = window('Plex.nodes.%s.title' % i)
            node_type = window('Plex.nodes.%s.type' % i)
            # because we do not use seperate entrypoints for each content type,
            # we need to figure out which items to show in each listing. for
            # now we just only show picture nodes in the picture library video
            # nodes in the video library and all nodes in any other window
            if node_type == 'photos' and content_type == 'image':
                directory_item(label, path)
            elif (node_type != 'photos' and
                    content_type not in ('image', 'audio')):
                directory_item(label, path)

    # Plex Watch later
    if content_type not in ('image', 'audio'):
        directory_item(lang(39211),
                       "plugin://%s?mode=watchlater" % v.ADDON_ID)
    # Plex Channels
    directory_item(lang(30173),
                   "plugin://%s?mode=channels" % v.ADDON_ID)
    # Plex user switch
    directory_item('%s%s' % (lang(39200), settings('username')),
                   "plugin://%s?mode=switchuser" % v.ADDON_ID)

    # some extra entries for settings and stuff
    directory_item(lang(39201),
                   "plugin://%s?mode=settings" % v.ADDON_ID)
    directory_item(lang(39203),
                   "plugin://%s?mode=refreshplaylist" % v.ADDON_ID)
    directory_item(lang(39204),
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
    # window('EmbyAdditionalUserImage.%s' % position, clear=True)
    LOG.info("Plex home user switch requested")
    if not _log_out():
        return
    # First remove playlists of old user
    from utils import delete_playlists, delete_nodes
    delete_playlists()
    # Remove video nodes
    delete_nodes()
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
        listitem.addContextMenuItems([(lang(30032), 'XBMC.Action(Info)',)])
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
        if settings('ignoreSpecialsNextEpisodes') == "true":
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
    append_show_title = settings('RecentTvAppendShow') == 'true'
    append_sxxexx = settings('RecentTvAppendSeason') == 'true'
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
    if settings('TVShowWatched') == 'false':
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

    item = GetPlexMetadata(plex_id)
    try:
        path = item[0][0][0].attrib['file']
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
    path = path.replace(basename(path), '')
    if exists_dir(path):
        for root, dirs, files in walk(path):
            for directory in dirs:
                item_path = try_encode(join(root, directory))
                listitem = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                            url=item_path,
                                            listitem=listitem,
                                            isFolder=True)
            for file in files:
                item_path = try_encode(join(root, file))
                listitem = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                            url=file,
                                            listitem=listitem)
            break
    else:
        LOG.error('Kodi cannot access folder %s', path)
    xbmcplugin.endOfDirectory(int(argv[1]))


@catch_exceptions(warnuser=False)
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
    fanart_dir = try_decode(translatePath(
        "special://thumbnails/plex/%s/" % plex_id))
    if not exists_dir(fanart_dir):
        # Download the images to the cache directory
        makedirs(fanart_dir)
        xml = GetPlexMetadata(plex_id)
        if xml is None:
            LOG.error('Could not download metadata for %s', plex_id)
            return xbmcplugin.endOfDirectory(int(argv[1]))

        api = API(xml[0])
        backdrops = api.artwork()['Backdrop']
        for count, backdrop in enumerate(backdrops):
            # Same ordering as in artwork
            art_file = try_encode(join(fanart_dir, "fanart%.3d.jpg" % count))
            listitem = ListItem("%.3d" % count, path=art_file)
            xbmcplugin.addDirectoryItem(
                handle=int(argv[1]),
                url=art_file,
                listitem=listitem)
            copyfile(backdrop, try_decode(art_file))
    else:
        LOG.info("Found cached backdrop.")
        # Use existing cached images
        for root, _, files in walk(fanart_dir):
            for file in files:
                art_file = try_encode(join(root, file))
                listitem = ListItem(file, path=art_file)
                xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                            url=art_file,
                                            listitem=listitem)
    xbmcplugin.endOfDirectory(int(argv[1]))


def on_deck_episodes(viewid, tagname, limit):
    """
    Retrieves Plex On Deck items, currently only for TV shows

    Input:
        viewid:             Plex id of the library section, e.g. '1'
        tagname:            Name of the Plex library, e.g. "My Movies"
        limit:              Max. number of items to retrieve, e.g. 50
    """
    xbmcplugin.setContent(int(argv[1]), 'episodes')
    append_show_title = settings('OnDeckTvAppendShow') == 'true'
    append_sxxexx = settings('OnDeckTvAppendSeason') == 'true'
    if settings('OnDeckTVextended') == 'false':
        # Chances are that this view is used on Kodi startup
        # Wait till we've connected to a PMS. At most 30s
        counter = 0
        while window('plex_authenticated') != 'true':
            counter += 1
            if counter == 300:
                LOG.error('Aborting On Deck view, we were not authenticated '
                          'for the PMS')
                xbmcplugin.endOfDirectory(int(argv[1]), False)
                return
            sleep(100)
        xml = downloadutils.DownloadUtils().downloadUrl(
            '{server}/library/sections/%s/onDeck' % viewid)
        if xml in (None, 401):
            LOG.error('Could not download PMS xml for view %s', viewid)
            xbmcplugin.endOfDirectory(int(argv[1]), False)
            return
        # We're using another python instance - need to load some vars
        if settings('useDirectPaths') == '1':
            state.DIRECT_PATHS = True
            state.REPLACE_SMB_PATH = settings('replaceSMB') == 'true'
            state.REMAP_PATH = settings('remapSMB') == 'true'
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
            cacheToDisc=settings('enableTextureCache') == 'true')
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
    if settings('ignoreSpecialsNextEpisodes') == "true":
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


def watchlater():
    """
    Listing for plex.tv Watch Later section (if signed in to plex.tv)
    """
    if window('plex_token') == '':
        LOG.error('No watch later - not signed in to plex.tv')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)
    if window('plex_restricteduser') == 'true':
        LOG.error('No watch later - restricted user')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)

    xml = downloadutils.DownloadUtils().downloadUrl(
        'https://plex.tv/pms/playlists/queue/all',
        authenticate=False,
        headerOptions={'X-Plex-Token': window('plex_token')})
    if xml in (None, 401):
        LOG.error('Could not download watch later list from plex.tv')
        return xbmcplugin.endOfDirectory(int(argv[1]), False)

    LOG.info('Displaying watch later plex.tv items')
    xbmcplugin.setContent(int(argv[1]), 'movies')
    direct_paths = settings('useDirectPaths') == '1'
    for item in xml:
        __build_item(item, direct_paths)

    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=settings('enableTextureCache') == 'true')


def channels():
    """
    Listing for Plex Channels
    """
    xml = downloadutils.DownloadUtils().downloadUrl('{server}/channels/all')
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
        cacheToDisc=settings('enableTextureCache') == 'true')


def browse_plex(key=None, plex_section_id=None):
    """
    Lists the content of a Plex folder, e.g. channels. Either pass in key (to
    be used directly for PMS url {server}<key>) or the plex_section_id
    """
    if key:
        xml = downloadutils.DownloadUtils().downloadUrl('{server}%s' % key)
    else:
        xml = GetPlexSectionResults(plex_section_id)
    try:
        xml[0].attrib
    except (ValueError, AttributeError, IndexError, TypeError):
        LOG.error('Could not browse to %s', key)
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
    direct_paths = settings('useDirectPaths') == '1'
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
        xbmcplugin.setContent(int(argv[1]), 'movies')
        sort_methods = v.SORT_METHODS_MOVIES
    elif clips is True:
        xbmcplugin.setContent(int(argv[1]), 'movies')
        sort_methods = v.SORT_METHODS_CLIPS
    elif photos is True:
        xbmcplugin.setContent(int(argv[1]), 'images')
        sort_methods = v.SORT_METHODS_PHOTOS
    elif tvshows is True:
        xbmcplugin.setContent(int(argv[1]), 'tvshows')
        sort_methods = v.SORT_METHOD_TVSHOWS
    elif episodes is True:
        xbmcplugin.setContent(int(argv[1]), 'episodes')
        sort_methods = v.SORT_METHODS_EPISODES
    elif songs is True:
        xbmcplugin.setContent(int(argv[1]), 'songs')
        sort_methods = v.SORT_METHODS_SONGS
    elif artists is True:
        xbmcplugin.setContent(int(argv[1]), 'artists')
        sort_methods = v.SORT_METHODS_ARTISTS
    elif albums is True:
        xbmcplugin.setContent(int(argv[1]), 'albums')
        sort_methods = v.SORT_METHODS_ALBUMS
    elif musicvideos is True:
        xbmcplugin.setContent(int(argv[1]), 'musicvideos')
        sort_methods = v.SORT_METHODS_MOVIES
    else:
        xbmcplugin.setContent(int(argv[1]), 'files')
        sort_methods = v.SORT_METHODS_DIRECTORY

    for method in sort_methods:
        xbmcplugin.addSortMethod(int(argv[1]), getattr(xbmcplugin, method))

    # Set the Kodi title for this view
    title = xml.attrib.get('librarySectionTitle', xml.attrib.get('title1'))
    xbmcplugin.setPluginCategory(int(argv[1]), title)

    xbmcplugin.endOfDirectory(
        handle=int(argv[1]),
        cacheToDisc=settings('enableTextureCache') == 'true')


def __build_folder(xml_element, plex_section_id=None):
    url = "plugin://%s/" % v.ADDON_ID
    key = xml_element.attrib.get('fastKey', xml_element.attrib.get('key'))
    if not key.startswith('/'):
        key = '/library/sections/%s/%s' % (plex_section_id, key)
    params = {
        'mode': "browseplex",
        'key': key,
        'id': plex_section_id
    }
    listitem = ListItem(xml_element.attrib.get('title'))
    listitem.setArt({'thumb': xml_element.attrib.get('thumb'),
                     'poster': xml_element.attrib.get('art')})
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
    if api.resume_point():
        listitem.setProperty('resumetime', str(api.resume_point()))
    xbmcplugin.addDirectoryItem(handle=int(argv[1]),
                                url=url,
                                listitem=listitem)


def extras(plex_id):
    """
    Lists all extras for plex_id
    """
    xbmcplugin.setContent(int(argv[1]), 'movies')
    xml = GetPlexMetadata(plex_id)
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
    dialog('ok', lang(29999), lang(39215), '192.168.1.2', 'plex.myServer.org')
    address = dialog('input', "Enter PMS IP or URL")
    if address == '':
        return
    port = dialog('input', "Enter PMS port", '32400', type='{numeric}')
    if port == '':
        return
    url = '%s:%s' % (address, port)
    # "Does your Plex Media Server support SSL connections?
    # (https instead of http)"
    https = dialog('yesno', lang(29999), lang(39217))
    if https:
        url = 'https://%s' % url
    else:
        url = 'http://%s' % url
    https = 'true' if https else 'false'
    machine_identifier = GetMachineIdentifier(url)
    if machine_identifier is None:
        # "Error contacting url
        # Abort (Yes) or save address anyway (No)"
        if dialog('yesno',
                  lang(29999),
                  '%s %s. %s' % (lang(39218), url, lang(39219))):
            return
        else:
            settings('plex_machineIdentifier', '')
    else:
        settings('plex_machineIdentifier', machine_identifier)
    LOG.info('Set new PMS to https %s, address %s, port %s, machineId %s',
             https, address, port, machine_identifier)
    settings('https', value=https)
    settings('ipaddress', value=address)
    settings('port', value=port)
    # Chances are this is a local PMS, so disable SSL certificate check
    settings('sslverify', value='false')

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
    plex_command('RUN_LIB_SCAN', 'full')
    # Restart user client
    plex_command('SUSPEND_USER_CLIENT', 'False')


def _log_out():
    """
    Finishes lib scans, logs out user.

    Returns True if successfully signed out, False otherwise
    """
    # Resetting, please wait
    dialog('notification',
           lang(29999),
           lang(39207),
           icon='{plex}',
           time=3000,
           sound=False)
    # Pause library sync thread
    plex_command('SUSPEND_LIBRARY_THREAD', 'True')
    # Wait max for 10 seconds for all lib scans to shutdown
    counter = 0
    while window('plex_dbScan') == 'true':
        if counter > 200:
            # Failed to reset PMS and plex.tv connects. Try to restart Kodi.
            dialog('ok', lang(29999), lang(39208))
            # Resuming threads, just in case
            plex_command('SUSPEND_LIBRARY_THREAD', 'False')
            LOG.error("Could not stop library sync, aborting")
            return False
        counter += 1
        sleep(50)
    LOG.debug("Successfully stopped library sync")

    counter = 0
    # Log out currently signed in user:
    window('plex_serverStatus', value='401')
    plex_command('PMS_STATUS', '401')
    # Above method needs to have run its course! Hence wait
    while window('plex_serverStatus') == "401":
        if counter > 100:
            # 'Failed to reset PKC. Try to restart Kodi.'
            dialog('ok', lang(29999), lang(39208))
            LOG.error("Could not sign out user, aborting")
            return False
        counter += 1
        sleep(50)
    # Suspend the user client during procedure
    plex_command('SUSPEND_USER_CLIENT', 'True')
    return True
