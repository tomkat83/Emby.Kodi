# -*- coding: utf-8 -*-
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

from PlexFunctions import GetPlexMetadata, GetPlexSectionResults, \
    GetMachineIdentifier
from PlexAPI import API
import json_rpc as js
import variables as v

###############################################################################
log = getLogger("PLEX."+__name__)

try:
    HANDLE = int(argv[1])
    ARGV_0 = argv[0]
except IndexError:
    pass
###############################################################################


def chooseServer():
    """
    Lets user choose from list of PMS
    """
    log.info("Choosing PMS server requested, starting")

    import initialsetup
    setup = initialsetup.InitialSetup()
    server = setup.pick_pms(showDialog=True)
    if server is None:
        log.error('We did not connect to a new PMS, aborting')
        plex_command('SUSPEND_USER_CLIENT', 'False')
        plex_command('SUSPEND_LIBRARY_THREAD', 'False')
        return

    log.info("User chose server %s" % server['name'])
    setup.write_pms_to_settings(server)

    if not __LogOut():
        return

    from utils import wipe_database
    # Wipe Kodi and Plex database as well as playlists and video nodes
    wipe_database()

    # Log in again
    __LogIn()
    log.info("Choosing new PMS complete")
    # '<PMS> connected'
    dialog('notification',
           lang(29999),
           '%s %s' % (server['name'], lang(39220)),
           icon='{plex}',
           time=3000,
           sound=False)


def togglePlexTV():
    if settings('plexToken'):
        log.info('Reseting plex.tv credentials in settings')
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
        log.info('Login to plex.tv')
        import initialsetup
        initialsetup.InitialSetup().plex_tv_sign_in()
    dialog('notification',
           lang(29999),
           lang(39221),
           icon='{plex}',
           time=3000,
           sound=False)


##### DO RESET AUTH #####
def resetAuth():
    # User tried login and failed too many times
    resp = dialog('yesno', heading="{plex}", line1=lang(39206))
    if resp == 1:
        log.info("Reset login attempts.")
        plex_command('PMS_STATUS', 'Auth')
    else:
        executebuiltin('Addon.OpenSettings(plugin.video.plexkodiconnect)')


def addDirectoryItem(label, path, folder=True):
    li = ListItem(label, path=path)
    li.setThumbnailImage("special://home/addons/plugin.video.plexkodiconnect/icon.png")
    li.setArt({"fanart":"special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    li.setArt({"landscape":"special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=path, listitem=li, isFolder=folder)


def doMainListing(content_type=None):
    log.debug('Do main listing with content_type: %s' % content_type)
    xbmcplugin.setContent(HANDLE, 'files')
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
                addDirectoryItem(label, path)
            elif (node_type != 'photos' and
                    content_type not in ('image', 'audio')):
                addDirectoryItem(label, path)

    # Plex Watch later
    if content_type not in ('image', 'audio'):
        addDirectoryItem(lang(39211),
                         "plugin://%s?mode=watchlater" % v.ADDON_ID)
    # Plex Channels
    addDirectoryItem(lang(30173),
                     "plugin://%s?mode=channels" % v.ADDON_ID)
    # Plex user switch
    addDirectoryItem(lang(39200),
                     "plugin://%s?mode=switchuser" % v.ADDON_ID)

    # some extra entries for settings and stuff
    addDirectoryItem(lang(39201),
                     "plugin://%s?mode=settings" % v.ADDON_ID)
    addDirectoryItem(lang(39203),
                     "plugin://%s?mode=refreshplaylist" % v.ADDON_ID)
    addDirectoryItem(lang(39204),
                     "plugin://%s?mode=manualsync" % v.ADDON_ID)
    xbmcplugin.endOfDirectory(HANDLE)


def switchPlexUser():
    """
    Signs out currently logged in user (if applicable). Triggers sign-in of a
    new user
    """
    # Guess these user avatars are a future feature. Skipping for now
    # Delete any userimages. Since there's always only 1 user: position = 0
    # position = 0
    # window('EmbyAdditionalUserImage.%s' % position, clear=True)
    log.info("Plex home user switch requested")
    if not __LogOut():
        return

    # First remove playlists of old user
    from utils import delete_playlists, delete_nodes
    delete_playlists()
    # Remove video nodes
    delete_nodes()
    __LogIn()


#### SHOW SUBFOLDERS FOR NODE #####
def GetSubFolders(nodeindex):
    nodetypes = ["",".recent",".recentepisodes",".inprogress",".inprogressepisodes",".unwatched",".nextepisodes",".sets",".genres",".random",".recommended"]
    for node in nodetypes:
        title = window('Plex.nodes.%s%s.title' %(nodeindex,node))
        if title:
            path = window('Plex.nodes.%s%s.content' %(nodeindex,node))
            addDirectoryItem(title, path)
    xbmcplugin.endOfDirectory(HANDLE)


##### LISTITEM SETUP FOR VIDEONODES #####
def createListItem(item, append_show_title=False, append_sxxexx=False):
    log.debug('createListItem called with append_show_title %s, append_sxxexx '
              '%s, item: %s', append_show_title, append_sxxexx, item)
    title = item['title']
    li = ListItem(title)
    li.setProperty('IsPlayable', 'true')
    metadata = {
        'duration': str(item['runtime']/60),
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
        li.setProperty('episodeno', 's%.2de%.2d' % (season, episode))
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
    li.setLabel(title)
    li.setInfo(type='Video', infoLabels=metadata)

    li.setProperty('resumetime', str(item['resume']['position']))
    li.setProperty('totaltime', str(item['resume']['total']))
    li.setArt(item['art'])
    li.setThumbnailImage(item['art'].get('thumb', ''))
    li.setArt({'icon': 'DefaultTVShows.png'})
    li.setProperty('fanart_image', item['art'].get('tvshow.fanart', ''))
    try:
        li.addContextMenuItems([(lang(30032), 'XBMC.Action(Info)',)])
    except TypeError:
        # Kodi fuck-up
        pass
    for key, value in item['streamdetails'].iteritems():
        for stream in value:
            li.addStreamInfo(key, stream)
    return li

##### GET NEXTUP EPISODES FOR TAGNAME #####    
def getNextUpEpisodes(tagname, limit):
    count = 0
    # if the addon is called with nextup parameter,
    # we return the nextepisodes list of the given tagname
    xbmcplugin.setContent(HANDLE, 'episodes')
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
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=episode['file'],
                                        listitem=createListItem(episode))
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=HANDLE)


##### GET INPROGRESS EPISODES FOR TAGNAME #####
def getInProgressEpisodes(tagname, limit):
    count = 0
    # if the addon is called with inprogressepisodes parameter,
    # we return the inprogressepisodes list of the given tagname
    xbmcplugin.setContent(HANDLE, 'episodes')
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
                "tvshowid", "art", "cast", "streamdetails", "firstaired",
                "runtime", "writer", "dateadded", "lastplayed"]
        }
        for episode in js.get_episodes(params):
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=episode['file'],
                                        listitem=createListItem(episode))
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=HANDLE)

##### GET RECENT EPISODES FOR TAGNAME #####    
# def getRecentEpisodes(tagname, limit):
def getRecentEpisodes(viewid, mediatype, tagname, limit):
    count = 0
    # if the addon is called with recentepisodes parameter,
    # we return the recentepisodes list of the given tagname
    xbmcplugin.setContent(HANDLE, 'episodes')
    append_show_title = settings('RecentTvAppendShow') == 'true'
    append_sxxexx = settings('RecentTvAppendSeason') == 'true'
    # First we get a list of all the TV shows - filtered by tag
    allshowsIds = set()
    params = {
        'sort': {'order': "descending", 'method': "dateadded"},
        'filter': {'operator': "is", 'field': "tag", 'value': "%s" % tagname},
    }
    for tv_show in js.get_tv_shows(params):
        allshowsIds.add(tv_show['tvshowid'])
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
        if episode['tvshowid'] in allshowsIds:
            listitem = createListItem(episode,
                                append_show_title=append_show_title,
                                append_sxxexx=append_sxxexx)
            xbmcplugin.addDirectoryItem(
                        handle=HANDLE,
                        url=episode['file'],
                        listitem=listitem)
            count += 1
        if count == limit:
            break
    xbmcplugin.endOfDirectory(handle=HANDLE)


def getVideoFiles(plexId, params):
    """
    GET VIDEO EXTRAS FOR LISTITEM

    returns the video files for the item as plugin listing, can be used for
    browsing the actual files or videoextras etc.
    """
    if plexId is None:
        filename = params.get('filename')
        if filename is not None:
            filename = filename[0]
            import re
            regex = re.compile(r'''library/metadata/(\d+)''')
            filename = regex.findall(filename)
            try:
                plexId = filename[0]
            except IndexError:
                pass

    if plexId is None:
        log.info('No Plex ID found, abort getting Extras')
        return xbmcplugin.endOfDirectory(HANDLE)

    item = GetPlexMetadata(plexId)
    try:
        path = item[0][0][0].attrib['file']
    except:
        log.error('Could not get file path for item %s' % plexId)
        return xbmcplugin.endOfDirectory(HANDLE)
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
                li = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=HANDLE,
                                            url=item_path,
                                            listitem=li,
                                            isFolder=True)
            for file in files:
                item_path = try_encode(join(root, file))
                li = ListItem(item_path, path=item_path)
                xbmcplugin.addDirectoryItem(handle=HANDLE,
                                            url=file,
                                            listitem=li)
            break
    else:
        log.error('Kodi cannot access folder %s' % path)
    xbmcplugin.endOfDirectory(HANDLE)


@catch_exceptions(warnuser=False)
def getExtraFanArt(plexid, plexPath):
    """
    Get extrafanart for listitem
    will be called by skinhelper script to get the extrafanart
    for tvshows we get the plexid just from the path
    """
    log.debug('Called with plexid: %s, plexPath: %s' % (plexid, plexPath))
    if not plexid:
        if "plugin.video.plexkodiconnect" in plexPath:
            plexid = plexPath.split("/")[-2]
    if not plexid:
        log.error('Could not get a plexid, aborting')
        return xbmcplugin.endOfDirectory(HANDLE)

    # We need to store the images locally for this to work
    # because of the caching system in xbmc
    fanartDir = try_decode(translatePath(
        "special://thumbnails/plex/%s/" % plexid))
    if not exists_dir(fanartDir):
        # Download the images to the cache directory
        makedirs(fanartDir)
        xml = GetPlexMetadata(plexid)
        if xml is None:
            log.error('Could not download metadata for %s' % plexid)
            return xbmcplugin.endOfDirectory(HANDLE)

        api = API(xml[0])
        backdrops = api.artwork()['Backdrop']
        for count, backdrop in enumerate(backdrops):
            # Same ordering as in artwork
            fanartFile = try_encode(join(fanartDir, "fanart%.3d.jpg" % count))
            li = ListItem("%.3d" % count, path=fanartFile)
            xbmcplugin.addDirectoryItem(
                handle=HANDLE,
                url=fanartFile,
                listitem=li)
            copyfile(backdrop, try_decode(fanartFile))
    else:
        log.info("Found cached backdrop.")
        # Use existing cached images
        for root, dirs, files in walk(fanartDir):
            for file in files:
                fanartFile = try_encode(join(root, file))
                li = ListItem(file, path=fanartFile)
                xbmcplugin.addDirectoryItem(handle=HANDLE,
                                            url=fanartFile,
                                            listitem=li)
    xbmcplugin.endOfDirectory(HANDLE)


def getOnDeck(viewid, mediatype, tagname, limit):
    """
    Retrieves Plex On Deck items, currently only for TV shows

    Input:
        viewid:             Plex id of the library section, e.g. '1'
        mediatype:          Kodi mediatype, e.g. 'tvshows', 'movies',
                            'homevideos', 'photos'
        tagname:            Name of the Plex library, e.g. "My Movies"
        limit:              Max. number of items to retrieve, e.g. 50
    """
    xbmcplugin.setContent(HANDLE, 'episodes')
    append_show_title = settings('OnDeckTvAppendShow') == 'true'
    append_sxxexx = settings('OnDeckTvAppendSeason') == 'true'
    directpaths = settings('useDirectPaths') == 'true'
    if settings('OnDeckTVextended') == 'false':
        # Chances are that this view is used on Kodi startup
        # Wait till we've connected to a PMS. At most 30s
        counter = 0
        while window('plex_authenticated') != 'true':
            counter += 1
            if counter >= 300:
                log.error('Aborting On Deck view, we were not authenticated '
                          'for the PMS')
                return xbmcplugin.endOfDirectory(HANDLE, False)
            sleep(100)
        xml = downloadutils.DownloadUtils().downloadUrl(
            '{server}/library/sections/%s/onDeck' % viewid)
        if xml in (None, 401):
            log.error('Could not download PMS xml for view %s' % viewid)
            return xbmcplugin.endOfDirectory(HANDLE)
        limitcounter = 0
        for item in xml:
            api = API(item)
            listitem = api.create_listitem(
                append_show_title=append_show_title,
                append_sxxexx=append_sxxexx)
            if directpaths:
                url = api.file_path()
            else:
                url = ('plugin://%s.tvshows/?plex_id=%s&plex_type=%s&mode=play&filename=%s'
                       % (v.ADDON_ID,
                          api.plex_id(),
                          api.plex_type(),
                          api.file_name(force_first_media=True)))
            if api.resume_point():
                listitem.setProperty('resumetime',
                                     str(api.resume_point()))
            xbmcplugin.addDirectoryItem(
                handle=HANDLE,
                url=url,
                listitem=listitem)
            limitcounter += 1
            if limitcounter == limit:
                break
        return xbmcplugin.endOfDirectory(
            handle=HANDLE,
            cacheToDisc=settings('enableTextureCache') == 'true')

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
        xbmcplugin.endOfDirectory(handle=HANDLE)
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
            listitem = createListItem(episode,
                                      append_show_title=append_show_title,
                                      append_sxxexx=append_sxxexx)
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=episode['file'],
                                        listitem=listitem,
                                        isFolder=False)
        count += 1
        if count >= limit:
            break
    xbmcplugin.endOfDirectory(handle=HANDLE)


def watchlater():
    """
    Listing for plex.tv Watch Later section (if signed in to plex.tv)
    """
    if window('plex_token') == '':
        log.error('No watch later - not signed in to plex.tv')
        return xbmcplugin.endOfDirectory(HANDLE, False)
    if window('plex_restricteduser') == 'true':
        log.error('No watch later - restricted user')
        return xbmcplugin.endOfDirectory(HANDLE, False)

    xml = downloadutils.DownloadUtils().downloadUrl(
        'https://plex.tv/pms/playlists/queue/all',
        authenticate=False,
        headerOptions={'X-Plex-Token': window('plex_token')})
    if xml in (None, 401):
        log.error('Could not download watch later list from plex.tv')
        return xbmcplugin.endOfDirectory(HANDLE, False)

    log.info('Displaying watch later plex.tv items')
    xbmcplugin.setContent(HANDLE, 'movies')
    for item in xml:
        __build_item(item)

    xbmcplugin.endOfDirectory(
        handle=HANDLE,
        cacheToDisc=settings('enableTextureCache') == 'true')


def channels():
    """
    Listing for Plex Channels
    """
    xml = downloadutils.DownloadUtils().downloadUrl('{server}/channels/all')
    try:
        xml[0].attrib
    except (ValueError, AttributeError, IndexError, TypeError):
        log.error('Could not download Plex Channels')
        return xbmcplugin.endOfDirectory(HANDLE, False)

    log.info('Displaying Plex Channels')
    xbmcplugin.setContent(HANDLE, 'files')
    for method in v.SORT_METHODS_DIRECTORY:
        xbmcplugin.addSortMethod(HANDLE, getattr(xbmcplugin, method))
    for item in xml:
        __build_folder(item)
    xbmcplugin.endOfDirectory(
        handle=HANDLE,
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
        log.error('Could not browse to %s' % key)
        return xbmcplugin.endOfDirectory(HANDLE, False)

    photos = False
    movies = False
    clips = False
    tvshows = False
    episodes = False
    songs = False
    artists = False
    albums = False
    musicvideos = False
    for item in xml:
        if item.tag == 'Directory':
            __build_folder(item, plex_section_id=plex_section_id)
        else:
            typus = item.attrib.get('type')
            __build_item(item)
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
        xbmcplugin.setContent(HANDLE, 'movies')
        sort_methods = v.SORT_METHODS_MOVIES
    elif clips is True:
        xbmcplugin.setContent(HANDLE, 'movies')
        sort_methods = v.SORT_METHODS_CLIPS
    elif photos is True:
        xbmcplugin.setContent(HANDLE, 'images')
        sort_methods = v.SORT_METHODS_PHOTOS
    elif tvshows is True:
        xbmcplugin.setContent(HANDLE, 'tvshows')
        sort_methods = v.SORT_METHOD_TVSHOWS
    elif episodes is True:
        xbmcplugin.setContent(HANDLE, 'episodes')
        sort_methods = v.SORT_METHODS_EPISODES
    elif songs is True:
        xbmcplugin.setContent(HANDLE, 'songs')
        sort_methods = v.SORT_METHODS_SONGS
    elif artists is True:
        xbmcplugin.setContent(HANDLE, 'artists')
        sort_methods = v.SORT_METHODS_ARTISTS
    elif albums is True:
        xbmcplugin.setContent(HANDLE, 'albums')
        sort_methods = v.SORT_METHODS_ALBUMS
    elif musicvideos is True:
        xbmcplugin.setContent(HANDLE, 'musicvideos')
        sort_methods = v.SORT_METHODS_MOVIES
    else:
        xbmcplugin.setContent(HANDLE, 'files')
        sort_methods = v.SORT_METHODS_DIRECTORY

    for method in sort_methods:
        xbmcplugin.addSortMethod(HANDLE, getattr(xbmcplugin, method))

    # Set the Kodi title for this view
    title = xml.attrib.get('librarySectionTitle', xml.attrib.get('title1'))
    xbmcplugin.setPluginCategory(HANDLE, title)

    xbmcplugin.endOfDirectory(
        handle=HANDLE,
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
    xbmcplugin.addDirectoryItem(handle=HANDLE,
                                url="%s?%s" % (url, urlencode(params)),
                                isFolder=True,
                                listitem=listitem)


def __build_item(xml_element):
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
        url = 'plugin://%s/?plex_id=%s&plex_type=%s&mode=play&filename=%s' \
              % (v.ADDON_TYPE[api.plex_type()],
                 api.plex_id(),
                 api.plex_type(),
                 api.file_name(force_first_media=True))
    if api.resume_point():
        listitem.setProperty('resumetime', str(api.resume_point()))
    xbmcplugin.addDirectoryItem(handle=HANDLE,
                                url=url,
                                listitem=listitem)


def enterPMS():
    """
    Opens dialogs for the user the plug in the PMS details
    """
    # "Enter your Plex Media Server's IP or URL. Examples are:"
    dialog('ok', lang(29999), lang(39215), '192.168.1.2', 'plex.myServer.org')
    ip = dialog('input', "Enter PMS IP or URL")
    if ip == '':
        return
    port = dialog('input', "Enter PMS port", '32400', type='{numeric}')
    if port == '':
        return
    url = '%s:%s' % (ip, port)
    # "Does your Plex Media Server support SSL connections?
    # (https instead of http)"
    https = dialog('yesno', lang(29999), lang(39217))
    if https:
        url = 'https://%s' % url
    else:
        url = 'http://%s' % url
    https = 'true' if https else 'false'

    machineIdentifier = GetMachineIdentifier(url)
    if machineIdentifier is None:
        # "Error contacting url
        # Abort (Yes) or save address anyway (No)"
        if dialog('yesno',
                  lang(29999),
                  '%s %s. %s' % (lang(39218), url, lang(39219))):
            return
        else:
            settings('plex_machineIdentifier', '')
    else:
        settings('plex_machineIdentifier', machineIdentifier)
    log.info('Set new PMS to https %s, ip %s, port %s, machineIdentifier %s'
             % (https, ip, port, machineIdentifier))
    settings('https', value=https)
    settings('ipaddress', value=ip)
    settings('port', value=port)
    # Chances are this is a local PMS, so disable SSL certificate check
    settings('sslverify', value='false')

    # Sign out to trigger new login
    if __LogOut():
        # Only login again if logout was successful
        __LogIn()


def __LogIn():
    """
    Resets (clears) window properties to enable (re-)login

    SUSPEND_LIBRARY_THREAD is set to False in service.py if user was signed
    out!
    """
    plex_command('RUN_LIB_SCAN', 'full')
    # Restart user client
    plex_command('SUSPEND_USER_CLIENT', 'False')


def __LogOut():
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
            log.error("Could not stop library sync, aborting")
            return False
        counter += 1
        sleep(50)
    log.debug("Successfully stopped library sync")

    counter = 0
    # Log out currently signed in user:
    window('plex_serverStatus', value='401')
    plex_command('PMS_STATUS', '401')
    # Above method needs to have run its course! Hence wait
    while window('plex_serverStatus') == "401":
        if counter > 100:
            # 'Failed to reset PKC. Try to restart Kodi.'
            dialog('ok', lang(29999), lang(39208))
            log.error("Could not sign out user, aborting")
            return False
        counter += 1
        sleep(50)
    # Suspend the user client during procedure
    plex_command('SUSPEND_USER_CLIENT', 'True')
    return True
