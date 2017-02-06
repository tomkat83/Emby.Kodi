# -*- coding: utf-8 -*-
###############################################################################
import logging
from os import path as os_path
from sys import argv
from urllib import urlencode

import xbmcplugin
from xbmc import sleep, Player, executebuiltin, getCondVisibility, \
    translatePath
from xbmcgui import ListItem

from utils import window, settings, language as lang, dialog, tryDecode,\
    tryEncode, CatchExceptions, JSONRPC
import downloadutils
import playbackutils as pbutils

from PlexFunctions import GetPlexMetadata, GetPlexSectionResults, \
    GetMachineIdentifier
from PlexAPI import API
from PKC_listitem import convert_PKC_to_listitem
from playqueue import Playqueue
import variables as v

###############################################################################
log = logging.getLogger("PLEX."+__name__)

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
    server = setup.PickPMS(showDialog=True)
    if server is None:
        log.error('We did not connect to a new PMS, aborting')
        window('suspend_Userclient', clear=True)
        window('suspend_LibraryThread', clear=True)
        return

    log.info("User chose server %s" % server['name'])
    setup.WritePMStoSettings(server)

    if not __LogOut():
        return

    from utils import deletePlaylists, deleteNodes
    # First remove playlists
    deletePlaylists()
    # Remove video nodes
    deleteNodes()

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
        settings('plexToken', value=""),
        settings('plexid', value="")
        settings('plexHomeSize', value="1")
        settings('plexAvatar', value="")
        settings('plex_status', value="Not logged in to plex.tv")

        window('plex_token', clear=True)
        window('plex_username', clear=True)
    else:
        log.info('Login to plex.tv')
        import initialsetup
        initialsetup.InitialSetup().PlexTVSignIn()
    dialog('notification',
           lang(29999),
           lang(39221),
           icon='{plex}',
           time=3000,
           sound=False)


def Plex_Node(url, viewOffset, plex_type, playdirectly=False):
    """
    Called only for a SINGLE element for Plex.tv watch later

    Always to return with a "setResolvedUrl"
    """
    log.info('Plex_Node called with url: %s, viewOffset: %s'
             % (url, viewOffset))
    # Plex redirect, e.g. watch later. Need to get actual URLs
    xml = downloadutils.DownloadUtils().downloadUrl(url)
    try:
        xml[0].attrib
    except:
        log.error('Could not download PMS metadata')
        return
    if viewOffset != '0':
        try:
            viewOffset = int(v.PLEX_TO_KODI_TIMEFACTOR *
                             float(viewOffset))
        except:
            pass
        else:
            window('plex_customplaylist.seektime', value=str(viewOffset))
            log.info('Set resume point to %s' % str(viewOffset))
    typus = v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[plex_type]
    playqueue = Playqueue().get_playqueue_from_type(typus)
    result = pbutils.PlaybackUtils(xml, playqueue).play(
        None,
        kodi_id='plexnode',
        plex_lib_UUID=xml.attrib.get('librarySectionUUID'))
    if result.listitem:
        listitem = convert_PKC_to_listitem(result.listitem)
    else:
        return
    if playdirectly:
        Player().play(listitem.getfilename(), listitem)
    else:
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem)


##### DO RESET AUTH #####
def resetAuth():
    # User tried login and failed too many times
    resp = dialog('yesno', heading="{plex}", line1=lang(39206))
    if resp == 1:
        log.info("Reset login attempts.")
        window('plex_serverStatus', value="Auth")
    else:
        executebuiltin('Addon.OpenSettings(plugin.video.plexkodiconnect)')


def addDirectoryItem(label, path, folder=True):
    li = ListItem(label, path=path)
    li.setThumbnailImage("special://home/addons/plugin.video.plexkodiconnect/icon.png")
    li.setArt({"fanart":"special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    li.setArt({"landscape":"special://home/addons/plugin.video.plexkodiconnect/fanart.jpg"})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=path, listitem=li, isFolder=folder)


def doMainListing():
    xbmcplugin.setContent(HANDLE, 'files')
    # Get emby nodes from the window props
    plexprops = window('Plex.nodes.total')
    if plexprops:
        totalnodes = int(plexprops)
        for i in range(totalnodes):
            path = window('Plex.nodes.%s.index' % i)
            if not path:
                path = window('Plex.nodes.%s.content' % i)
            label = window('Plex.nodes.%s.title' % i)
            node_type = window('Plex.nodes.%s.type' % i)
            #because we do not use seperate entrypoints for each content type, we need to figure out which items to show in each listing.
            #for now we just only show picture nodes in the picture library video nodes in the video library and all nodes in any other window
            if path and getCondVisibility("Window.IsActive(Pictures)") and node_type == "photos":
                addDirectoryItem(label, path)
            elif path and getCondVisibility("Window.IsActive(VideoLibrary)") and node_type != "photos":
                addDirectoryItem(label, path)
            elif path and not getCondVisibility("Window.IsActive(VideoLibrary) | Window.IsActive(Pictures) | Window.IsActive(MusicLibrary)"):
                addDirectoryItem(label, path)

    # Plex Watch later
    addDirectoryItem(lang(39211),
                     "plugin://plugin.video.plexkodiconnect/?mode=watchlater")
    # Plex user switch
    addDirectoryItem(lang(39200) + window('plex_username'),
                     "plugin://plugin.video.plexkodiconnect/"
                     "?mode=switchuser")

    #experimental live tv nodes
    # addDirectoryItem("Live Tv Channels (experimental)", "plugin://plugin.video.plexkodiconnect/?mode=browsecontent&type=tvchannels&folderid=root")
    # addDirectoryItem("Live Tv Recordings (experimental)", "plugin://plugin.video.plexkodiconnect/?mode=browsecontent&type=recordings&folderid=root")

    # some extra entries for settings and stuff. TODO --> localize the labels
    addDirectoryItem(lang(39201), "plugin://plugin.video.plexkodiconnect/?mode=settings")
    # addDirectoryItem("Add user to session", "plugin://plugin.video.plexkodiconnect/?mode=adduser")
    addDirectoryItem(lang(39203), "plugin://plugin.video.plexkodiconnect/?mode=refreshplaylist")
    addDirectoryItem(lang(39204), "plugin://plugin.video.plexkodiconnect/?mode=manualsync")
    xbmcplugin.endOfDirectory(HANDLE)


##### Generate a new deviceId
def resetDeviceId():
    deviceId_old = window('plex_client_Id')
    from clientinfo import getDeviceId
    try:
        deviceId = getDeviceId(reset=True)
    except Exception as e:
        log.error("Failed to generate a new device Id: %s" % e)
        dialog('ok', lang(29999), lang(33032))
    else:
        log.info("Successfully removed old deviceId: %s New deviceId: %s"
                 % (deviceId_old, deviceId))
        # "Kodi will now restart to apply the changes"
        dialog('ok', lang(29999), lang(33033))
        executebuiltin('RestartApp')


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
    from utils import deletePlaylists, deleteNodes
    deletePlaylists()
    # Remove video nodes
    deleteNodes()
    __LogIn()


##### REFRESH EMBY PLAYLISTS #####
def refreshPlaylist():
    log.info('Requesting playlist/nodes refresh')
    window('plex_runLibScan', value="views")


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
def createListItem(item, appendShowTitle=False, appendSxxExx=False):
    title = item['title']
    li = ListItem(title)
    li.setProperty('IsPlayable', "true")

    metadata = {
        'duration': str(item['runtime']/60),
        'Plot': item['plot'],
        'Playcount': item['playcount']
    }

    if "episode" in item:
        episode = item['episode']
        metadata['Episode'] = episode

    if "season" in item:
        season = item['season']
        metadata['Season'] = season

    if season and episode:
        li.setProperty('episodeno', "s%.2de%.2d" % (season, episode))
        if appendSxxExx is True:
            title = "S%.2dE%.2d - %s" % (season, episode, title)

    if "firstaired" in item:
        metadata['Premiered'] = item['firstaired']

    if "showtitle" in item:
        metadata['TVshowTitle'] = item['showtitle']
        if appendShowTitle is True:
            title = item['showtitle'] + ' - ' + title

    if "rating" in item:
        metadata['Rating'] = str(round(float(item['rating']),1))

    if "director" in item:
        metadata['Director'] = " / ".join(item['director'])

    if "writer" in item:
        metadata['Writer'] = " / ".join(item['writer'])

    if "cast" in item:
        cast = []
        castandrole = []
        for person in item['cast']:
            name = person['name']
            cast.append(name)
            castandrole.append((name, person['role']))
        metadata['Cast'] = cast
        metadata['CastAndRole'] = castandrole

    metadata['Title'] = title
    li.setLabel(title)

    li.setInfo(type="Video", infoLabels=metadata)  
    li.setProperty('resumetime', str(item['resume']['position']))
    li.setProperty('totaltime', str(item['resume']['total']))
    li.setArt(item['art'])
    li.setThumbnailImage(item['art'].get('thumb',''))
    li.setArt({'icon': 'DefaultTVShows.png'})
    li.setProperty('dbid', str(item['episodeid']))
    li.setProperty('fanart_image', item['art'].get('tvshow.fanart',''))
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
    result = JSONRPC('VideoLibrary.GetTVShows').execute(params)

    # If we found any, find the oldest unwatched show for each one.
    try:
        items = result['result']['tvshows']
    except (KeyError, TypeError):
        pass
    else:
        for item in items:
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

            result = JSONRPC('VideoLibrary.GetEpisodes').execute(params)
            try:
                episodes = result['result']['episodes']
            except (KeyError, TypeError):
                pass
            else:
                for episode in episodes:
                    li = createListItem(episode)
                    xbmcplugin.addDirectoryItem(handle=HANDLE,
                                                url=episode['file'],
                                                listitem=li)
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
    result = JSONRPC('VideoLibrary.GetTVShows').execute(params)
    # If we found any, find the oldest unwatched show for each one.
    try:
        items = result['result']['tvshows']
    except (KeyError, TypeError):
        pass
    else:
        for item in items:
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
            result = JSONRPC('VideoLibrary.GetEpisodes').execute(params)
            try:
                episodes = result['result']['episodes']
            except (KeyError, TypeError):
                pass
            else:
                for episode in episodes:
                    li = createListItem(episode)
                    xbmcplugin.addDirectoryItem(handle=HANDLE,
                                                url=episode['file'],
                                                listitem=li)
                    count += 1

            if count == limit:
                break

    xbmcplugin.endOfDirectory(handle=HANDLE)

##### GET RECENT EPISODES FOR TAGNAME #####    
# def getRecentEpisodes(tagname, limit):
def getRecentEpisodes(viewid, mediatype, tagname, limit):
    """
    Retrieves Plex Recent Episodes items, currently only for TV shows

    Input:
        viewid:             Plex id of the library section, e.g. '1'
        mediatype:          Kodi mediatype, e.g. 'tvshows', 'movies',
                            'homevideos', 'photos'
        tagname:            Name of the Plex library, e.g. "My Movies"
        limit:              Max. number of items to retrieve, e.g. 50
    """
    xbmcplugin.setContent(HANDLE, 'episodes')
    appendShowTitle = settings('RecentTvAppendShow') == 'true'
    appendSxxExx = settings('RecentTvAppendSeason') == 'true'
    directpaths = settings('useDirectPaths') == 'true'
    # Chances are that this view is used on Kodi startup
    # Wait till we've connected to a PMS. At most 30s
    counter = 0
    while window('plex_authenticated') != 'true':
        counter += 1
        if counter >= 300:
            log.error('Aborting Recent Episodes view, we were not authenticated '
                      'for the PMS')
            return xbmcplugin.endOfDirectory(HANDLE, False)
        sleep(100)
    xml = downloadutils.DownloadUtils().downloadUrl(
        '{server}/library/sections/%s/recentlyAdded' % viewid)
    if xml in (None, 401):
        log.error('Could not download PMS xml for view %s' % viewid)
        return xbmcplugin.endOfDirectory(HANDLE, False)
    for limitcounter, item in enumerate(xml, start=1):
        api = API(item)
        listitem = api.CreateListItemFromPlexItem(
            appendShowTitle=appendShowTitle,
            appendSxxExx=appendSxxExx)
        api.AddStreamInfo(listitem)
        api.set_listitem_artwork(listitem)
        if directpaths:
            url = api.getFilePath()
        else:
            params = {
                'mode': "play",
                'id': api.getRatingKey(),
                'dbid': listitem.getProperty('dbid')
            }
            url = "plugin://plugin.video.plexkodiconnect/tvshows/?%s" \
                  % urlencode(params)
        xbmcplugin.addDirectoryItem(
            handle=HANDLE,
            url=url,
            listitem=listitem)
        if limitcounter == limit:
            break
    xbmcplugin.endOfDirectory(
        handle=HANDLE,
        cacheToDisc=settings('enableTextureCache') == 'true')


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
    # Directory only, get rid of filename (!! exists() needs /  or \ at end)
    path = path.replace(os_path.basename(path), '')
    # Only proceed if we can access this folder
    import xbmcvfs
    if xbmcvfs.exists(path):
        # Careful, returns encoded strings!
        dirs, files = xbmcvfs.listdir(path)
        for file in files:
            file = path + tryDecode(file)
            li = ListItem(file, path=file)
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=tryEncode(file),
                                        listitem=li)
        for dir in dirs:
            dir = path + tryDecode(dir)
            li = ListItem(dir, path=dir)
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=tryEncode(dir),
                                        listitem=li,
                                        isFolder=True)
    else:
        log.warn('Kodi cannot access folder %s' % path)
    xbmcplugin.endOfDirectory(HANDLE)


@CatchExceptions(warnuser=False)
def getExtraFanArt(plexid, plexPath):
    """
    Get extrafanart for listitem
    will be called by skinhelper script to get the extrafanart
    for tvshows we get the plexid just from the path
    """
    import xbmcvfs
    log.debug('Called with plexid: %s, plexPath: %s' % (plexid, plexPath))
    if not plexid:
        if "plugin.video.plexkodiconnect" in plexPath:
            plexid = plexPath.split("/")[-2]
    if not plexid:
        log.error('Could not get a plexid, aborting')
        return xbmcplugin.endOfDirectory(HANDLE)

    # We need to store the images locally for this to work
    # because of the caching system in xbmc
    fanartDir = tryDecode(translatePath(
        "special://thumbnails/plex/%s/" % plexid))
    if not xbmcvfs.exists(fanartDir):
        # Download the images to the cache directory
        xbmcvfs.mkdirs(tryEncode(fanartDir))
        xml = GetPlexMetadata(plexid)
        if xml is None:
            log.error('Could not download metadata for %s' % plexid)
            return xbmcplugin.endOfDirectory(HANDLE)

        api = API(xml[0])
        backdrops = api.getAllArtwork()['Backdrop']
        for count, backdrop in enumerate(backdrops):
            # Same ordering as in artwork
            if os_path.supports_unicode_filenames:
                fanartFile = os_path.join(fanartDir,
                                          "fanart%.3d.jpg" % count)
            else:
                fanartFile = os_path.join(
                    tryEncode(fanartDir),
                    tryEncode("fanart%.3d.jpg" % count))
            li = ListItem("%.3d" % count, path=fanartFile)
            xbmcplugin.addDirectoryItem(
                handle=HANDLE,
                url=fanartFile,
                listitem=li)
            xbmcvfs.copy(backdrop, fanartFile)
    else:
        log.info("Found cached backdrop.")
        # Use existing cached images
        dirs, files = xbmcvfs.listdir(fanartDir)
        for file in files:
            fanartFile = os_path.join(fanartDir, tryDecode(file))
            li = ListItem(file, path=fanartFile)
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=fanartFile,
                                        listitem=li)
    xbmcplugin.endOfDirectory(HANDLE)


def RunLibScan(mode):
    if window('plex_online') != "true":
        # Server is not online, do not run the sync
        dialog('ok', lang(29999), lang(39205))
    else:
        window('plex_runLibScan', value='full')


def BrowsePlexContent(viewid, mediatype="", folderid=""):
    """
    Browse Plex Photos:
        viewid:          PMS name of the library
        mediatype:       mediatype, 'photos'
        nodetype:        e.g. 'ondeck' (TBD!!)
    """
    log.debug("BrowsePlexContent called with viewid: %s, mediatype: "
              "%s, folderid: %s" % (viewid, mediatype, folderid))

    if not folderid:
        # Top-level navigation, so get the content of this section
        # Get all sections
        xml = GetPlexSectionResults(
            viewid,
            containerSize=int(settings('limitindex')))
        try:
            xml.attrib
        except AttributeError:
            log.error("Error download section %s" % viewid)
            return xbmcplugin.endOfDirectory(HANDLE, False)
    else:
        # folderid was passed so we can directly access the folder
        xml = downloadutils.DownloadUtils().downloadUrl(
            "{server}%s" % folderid)
        try:
            xml.attrib
        except AttributeError:
            log.error("Error downloading %s" % folderid)
            return xbmcplugin.endOfDirectory(HANDLE, False)

    # Set the folder's name
    xbmcplugin.setPluginCategory(HANDLE,
                                 xml.attrib.get('librarySectionTitle'))

    # set the correct params for the content type
    if mediatype == "photos":
        xbmcplugin.setContent(HANDLE, 'photos')

    # process the listing
    for item in xml:
        api = API(item)
        if item.tag == 'Directory':
            li = ListItem(item.attrib.get('title', 'Missing title'))
            # for folders we add an additional browse request, passing the
            # folderId
            li.setProperty('IsFolder', 'true')
            li.setProperty('IsPlayable', 'false')
            path = "%s?id=%s&mode=browseplex&type=%s&folderid=%s" \
                   % (ARGV_0, viewid, mediatype, api.getKey())
            api.set_listitem_artwork(li)
            xbmcplugin.addDirectoryItem(handle=HANDLE,
                                        url=path,
                                        listitem=li,
                                        isFolder=True)
        else:
            li = api.CreateListItemFromPlexItem()
            api.set_listitem_artwork(li)
            xbmcplugin.addDirectoryItem(
                handle=HANDLE,
                url=li.getProperty("path"),
                listitem=li)

    xbmcplugin.addSortMethod(HANDLE,
                             xbmcplugin.SORT_METHOD_VIDEO_TITLE)
    xbmcplugin.addSortMethod(HANDLE,
                             xbmcplugin.SORT_METHOD_DATE)
    xbmcplugin.addSortMethod(HANDLE,
                             xbmcplugin.SORT_METHOD_VIDEO_RATING)
    xbmcplugin.addSortMethod(HANDLE,
                             xbmcplugin.SORT_METHOD_VIDEO_RUNTIME)

    xbmcplugin.endOfDirectory(
        handle=HANDLE,
        cacheToDisc=settings('enableTextureCache') == 'true')


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
    appendShowTitle = settings('OnDeckTvAppendShow') == 'true'
    appendSxxExx = settings('OnDeckTvAppendSeason') == 'true'
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
            listitem = api.CreateListItemFromPlexItem(
                appendShowTitle=appendShowTitle,
                appendSxxExx=appendSxxExx)
            api.AddStreamInfo(listitem)
            api.set_listitem_artwork(listitem)
            if directpaths:
                url = api.getFilePath()
            else:
                params = {
                    'mode': "play",
                    'id': api.getRatingKey(),
                    'dbid': listitem.getProperty('dbid')
                }
                url = "plugin://plugin.video.plexkodiconnect/tvshows/?%s" \
                      % urlencode(params)
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
    result = JSONRPC('VideoLibrary.GetTVShows').execute(params)
    # If we found any, find the oldest unwatched show for each one.
    try:
        items = result['result'][mediatype]
    except (KeyError, TypeError):
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
        result = JSONRPC('VideoLibrary.GetEpisodes').execute(inprog_params)
        try:
            episodes = result['result']['episodes']
        except (KeyError, TypeError):
            # No, there are no episodes not yet finished. Get "next up"
            params['tvshowid'] = item['tvshowid']
            result = JSONRPC('VideoLibrary.GetEpisodes').execute(params)
            try:
                episodes = result['result']['episodes']
            except (KeyError, TypeError):
                # Also no episodes currently coming up
                continue
        for episode in episodes:
            # There will always be only 1 episode ('limit=1')
            li = createListItem(episode,
                                appendShowTitle=appendShowTitle,
                                appendSxxExx=appendSxxExx)
            xbmcplugin.addDirectoryItem(
                handle=HANDLE,
                url=episode['file'],
                listitem=li,
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
    url = "plugin://plugin.video.plexkodiconnect/"
    params = {
        'mode': "Plex_Node",
    }
    for item in xml:
        api = API(item)
        listitem = api.CreateListItemFromPlexItem()
        api.AddStreamInfo(listitem)
        api.set_listitem_artwork(listitem)
        params['id'] = item.attrib.get('key')
        params['viewOffset'] = item.attrib.get('viewOffset', '0')
        params['plex_type'] = item.attrib.get('type')
        xbmcplugin.addDirectoryItem(
            handle=HANDLE,
            url="%s?%s" % (url, urlencode(params)),
            listitem=listitem)

    xbmcplugin.endOfDirectory(
        handle=HANDLE,
        cacheToDisc=settings('enableTextureCache') == 'true')


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
    Resets (clears) window properties to enable (re-)login:
        suspend_Userclient
        plex_runLibScan: set to 'full' to trigger lib sync

    suspend_LibraryThread is cleared in service.py if user was signed out!
    """
    window('plex_runLibScan', value='full')
    # Restart user client
    window('suspend_Userclient', clear=True)


def __LogOut():
    """
    Finishes lib scans, logs out user. The following window attributes are set:
        suspend_LibraryThread: 'true'
        suspend_Userclient: 'true'

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
    window('suspend_LibraryThread', value='true')
    # Wait max for 10 seconds for all lib scans to shutdown
    counter = 0
    while window('plex_dbScan') == 'true':
        if counter > 200:
            # Failed to reset PMS and plex.tv connects. Try to restart Kodi.
            dialog('ok', lang(29999), lang(39208))
            # Resuming threads, just in case
            window('suspend_LibraryThread', clear=True)
            log.error("Could not stop library sync, aborting")
            return False
        counter += 1
        sleep(50)
    log.debug("Successfully stopped library sync")

    # Log out currently signed in user:
    window('plex_serverStatus', value="401")
    # Above method needs to have run its course! Hence wait
    counter = 0
    while window('plex_serverStatus') == "401":
        if counter > 100:
            # 'Failed to reset PKC. Try to restart Kodi.'
            dialog('ok', lang(29999), lang(39208))
            log.error("Could not sign out user, aborting")
            return False
        counter += 1
        sleep(50)
    # Suspend the user client during procedure
    window('suspend_Userclient', value='true')
    return True
