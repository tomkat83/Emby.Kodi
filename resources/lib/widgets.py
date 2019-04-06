#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Code from script.module.metadatautils, kodidb.py

Loads of different functions called in SEPARATE Python instances through
e.g. plugin://... calls. Hence be careful to only rely on window variables.
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
try:
    from multiprocessing.pool import ThreadPool
    SUPPORTS_POOL = True
except Exception:
    SUPPORTS_POOL = False

import xbmc
import xbmcgui
import xbmcvfs

from .plex_api import API
from .plex_db import PlexDB
from . import json_rpc as js, utils, variables as v

LOG = getLogger('PLEX.widget')

# To easily use threadpool, we can only pass one argument
PLEX_TYPE = None
SECTION_ID = None
APPEND_SHOW_TITLE = None
APPEND_SXXEXX = None
# Need to chain the PMS keys
KEY = None


def get_listitem(xml_element):
    """
    Returns a valid xbmcgui.ListItem() for xml_element
    """
    item = generate_item(xml_element)
    prepare_listitem(item)
    return create_listitem(item, as_tuple=False)


def process_method_on_list(method_to_run, items):
    """
    helper method that processes a method on each listitem with pooling if the
    system supports it
    """
    all_items = []
    if SUPPORTS_POOL:
        pool = ThreadPool()
        try:
            all_items = pool.map(method_to_run, items)
        except Exception:
            # catch exception to prevent threadpool running forever
            utils.ERROR(notify=True)
        pool.close()
        pool.join()
    else:
        all_items = [method_to_run(item) for item in items]
    all_items = filter(None, all_items)
    return all_items


def get_clean_image(image):
    '''
    helper to strip all kodi tags/formatting of an image path/url
    Pass in either unicode or str; returns unicode
    '''
    if not image:
        return ""
    if not isinstance(image, str):
        image = image.encode('utf-8')
    if b"music@" in image:
        # fix for embedded images
        thumbcache = xbmc.getCacheThumbName(image)
        thumbcache = thumbcache.replace(b".tbn", b".jpg")
        thumbcache = b"special://thumbnails/%s/%s" % (thumbcache[0], thumbcache)
        if not xbmcvfs.exists(thumbcache):
            xbmcvfs.copy(image, thumbcache)
        image = thumbcache
    if image and b"image://" in image:
        image = image.replace(b"image://", b"")
        image = utils.unquote(image)
        if image.endswith("/"):
            image = image[:-1]
        return image
    else:
        return image.decode('utf-8')


def generate_item(xml_element):
    """
    Meant to be consumed by metadatautils.kodidb.prepare_listitem(), and then
    subsequently by metadatautils.kodidb.create_listitem()

    Do NOT set resumetime - otherwise Kodi always resumes at that time
    even if the user chose to start element from the beginning
        listitem.setProperty('resumetime', str(userdata['Resume']))

    The key 'file' needs to be set later with the item's path
    """
    try:
        if xml_element.tag in ('Directory', 'Playlist', 'Hub'):
            return _generate_folder(xml_element)
        else:
            return _generate_content(xml_element)
    except Exception:
        # Usefull to catch everything here since we're using threadpool
        LOG.error('xml that caused the crash: "%s": %s',
                  xml_element.tag, xml_element.attrib)
        utils.ERROR(notify=True)


def _generate_folder(xml_element):
    '''Generates "folder"/"directory" items that user can further navigate'''
    api = API(xml_element)
    art = api.artwork()
    return {
        'title': api.title(),
        'label': api.title(),
        'file': api.directory_path(section_id=SECTION_ID,
                                   plex_type=PLEX_TYPE,
                                   old_key=KEY),
        'icon': 'DefaultFolder.png',
        'art': {
            'thumb': art['thumb'] if 'thumb' in art else
                     (art['poster'] if 'poster' in art else
                      'special://home/addons/%s/icon.png' % v.ADDON_ID),
            'fanart': art['fanart'] if 'fanart' in art else
                      'special://home/addons/%s/fanart.jpg' % v.ADDON_ID},
        'isFolder': True,
        'type': '',
        'IsPlayable': 'false',
    }


def _generate_content(xml_element):
    api = API(xml_element)
    plex_type = api.plex_type()
    kodi_type = v.KODITYPE_FROM_PLEXTYPE[plex_type]
    userdata = api.userdata()
    _, _, tvshowtitle, season_no, episode_no = api.episode_data()
    db_item = xml_element.get('pkc_db_item')
    if db_item:
        # Item is synched to the Kodi db - let's use that info
        # (will thus e.g. include additional artwork or metadata)
        item = js.item_details(db_item['kodi_id'], kodi_type)
    else:
        people = api.people()
        cast = [{
            'name': x[0],
            'thumbnail': x[1],
            'role': x[2],
            'order': x[3],
        } for x in api.people_list()['actor']]
        item = {
            'cast': cast,
            'country': api.country_list(),
            'dateadded': api.date_created(),  # e.g '2019-01-03 19:40:59'
            'director': people['Director'],  # list of [str]
            'duration': userdata['Runtime'],
            'episode': episode_no,
            # 'file': '',  # e.g. 'videodb://tvshows/titles/20'
            'genre': api.genre_list(),
            # 'imdbnumber': '',  # e.g.'341663'
            'label': api.title(),  # e.g. '1x05. Category 55 Emergency Doomsday Crisis'
            'lastplayed': userdata['LastPlayedDate'],  # e.g. '2019-01-04 16:05:03'
            'mpaa': api.content_rating(),  # e.g. 'TV-MA'
            'originaltitle': '',  # e.g. 'Titans (2018)'
            'playcount': userdata['PlayCount'],  # [int]
            'plot': api.plot(),  # [str]
            'plotoutline': api.tagline(),
            'premiered': api.premiere_date(),  # '2018-10-12'
            'rating': api.audience_rating(),  # [float]
            'season': season_no,
            'sorttitle': api.sorttitle(),  # 'Titans (2018)'
            'studio': api.music_studio_list(),  # e.g. 'DC Universe'
            'tag': [],  # List of tags this item belongs to
            'tagline': api.tagline(),
            'thumbnail': '',  # e.g. 'image://https%3a%2f%2fassets.tv'
            'title': api.title(),  # 'Titans (2018)'
            'type': kodi_type,
            'trailer': api.trailer(),
            'tvshowtitle': tvshowtitle,
            'uniqueid': {
                'imdbnumber': api.provider('imdb') or '',
                'tvdb_id': api.provider('tvdb') or ''
            },
            'votes': '0',  # [str]!
            'writer': people['Writer'],  # list of [str]
            'year': api.year(),  # [int]
        }

        if plex_type in (v.PLEX_TYPE_EPISODE, v.PLEX_TYPE_SEASON, v.PLEX_TYPE_SHOW):
            leaves = api.leave_count()
            if leaves:
                item['extraproperties'] = leaves
        # Add all the artwork we can
        item['art'] = api.artwork(full_artwork=True)
        # Add all info for e.g. video and audio streams
        item['streamdetails'] = api.mediastreams()
        # Cleanup required due to the way metadatautils works
        if not item['lastplayed']:
            del item['lastplayed']
        for stream in item['streamdetails']['video']:
            stream['height'] = utils.cast(int, stream['height'])
            stream['width'] = utils.cast(int, stream['width'])
            stream['aspect'] = utils.cast(float, stream['aspect'])
        item['streamdetails']['subtitle'] = [{'language': x} for x in item['streamdetails']['subtitle']]
        # Resume point
        resume = api.resume_point()
        if resume:
            item['resume'] = {
                'position': resume,
                'total': userdata['Runtime']
            }

    item['icon'] = v.ICON_FROM_PLEXTYPE[plex_type]
    # Some customization
    if plex_type == v.PLEX_TYPE_EPISODE:
        # Prefix to the episode's title/label
        if season_no is not None and episode_no is not None:
            if APPEND_SXXEXX is True:
                item['title'] = "S%.2dE%.2d - %s" % (season_no, episode_no, item['title'])
        if APPEND_SHOW_TITLE is True:
            item['title'] = "%s - %s " % (tvshowtitle, item['title'])
        item['label'] = item['title']

    # Determine the path for this item
    key = api.path_and_plex_id()
    if key.startswith('/system/services') or key.startswith('http'):
        params = {
            'mode': 'plex_node',
            'key': key,
            'offset': xml_element.attrib.get('viewOffset', '0'),
        }
        url = utils.extend_url('plugin://%s' % v.ADDON_ID, params)
    elif plex_type == v.PLEX_TYPE_PHOTO:
        url = api.get_picture_path()
    else:
        url = api.path()
    if not db_item and plex_type == v.PLEX_TYPE_EPISODE:
        # Hack - Item is not synched to the Kodi database
        # We CANNOT use paths that show up in the Kodi paths table!
        url = url.replace('plugin.video.plexkodiconnect.tvshows',
                          'plugin.video.plexkodiconnect')
    item['file'] = url
    return item


def attach_kodi_ids(xml):
    """
    Attaches the kodi db_item to the xml's children, attribute 'pkc_db_item'
    """
    with PlexDB(lock=False) as plexdb:
        for child in xml:
            api = API(child)
            db_item = plexdb.item_by_id(api.plex_id(), api.plex_type())
            child.set('pkc_db_item', db_item)
    return xml


def prepare_listitem(item):
    """
    helper to convert kodi output from json api to compatible format for
    listitems

    Code from script.module.metadatautils, kodidb.py
    """
    try:
        # fix values returned from json to be used as listitem values
        properties = item.get("extraproperties", {})

        # set type
        for idvar in [
            ('episode', 'DefaultTVShows.png'),
            ('tvshow', 'DefaultTVShows.png'),
            ('movie', 'DefaultMovies.png'),
            ('song', 'DefaultAudio.png'),
            ('album', 'DefaultAudio.png'),
            ('artist', 'DefaultArtist.png'),
            ('musicvideo', 'DefaultMusicVideos.png'),
            ('recording', 'DefaultTVShows.png'),
                ('channel', 'DefaultAddonPVRClient.png')]:
            dbid = item.get(idvar[0] + "id")
            if dbid:
                properties["DBID"] = str(dbid)
                if not item.get("type"):
                    item["type"] = idvar[0]
                if not item.get("icon"):
                    item["icon"] = idvar[1]
                break

        # general properties
        if "genre" in item and isinstance(item['genre'], list):
            item["genre"] = " / ".join(item['genre'])
        if "studio" in item and isinstance(item['studio'], list):
            item["studio"] = " / ".join(item['studio'])
        if "writer" in item and isinstance(item['writer'], list):
            item["writer"] = " / ".join(item['writer'])
        if 'director' in item and isinstance(item['director'], list):
            item["director"] = " / ".join(item['director'])
        if 'artist' in item and not isinstance(item['artist'], list):
            item["artist"] = [item['artist']]
        if 'artist' not in item:
            item["artist"] = []
        if item['type'] == "album" and 'album' not in item and 'label' in item:
            item['album'] = item['label']
        if "duration" not in item and "runtime" in item:
            if (item["runtime"] / 60) > 300:
                item["duration"] = item["runtime"] / 60
            else:
                item["duration"] = item["runtime"]
        if "plot" not in item and "comment" in item:
            item["plot"] = item["comment"]
        if "tvshowtitle" not in item and "showtitle" in item:
            item["tvshowtitle"] = item["showtitle"]
        if "premiered" not in item and "firstaired" in item:
            item["premiered"] = item["firstaired"]
        if "firstaired" in item and "aired" not in item:
            item["aired"] = item["firstaired"]
        if "imdbnumber" not in properties and "imdbnumber" in item:
            properties["imdbnumber"] = item["imdbnumber"]
        if "imdbnumber" not in properties and "uniqueid" in item:
            for value in item["uniqueid"].values():
                if value.startswith("tt"):
                    properties["imdbnumber"] = value

        properties["dbtype"] = item["type"]
        properties["DBTYPE"] = item["type"]
        properties["type"] = item["type"]
        properties["path"] = item.get("file")

        # cast
        list_cast = []
        list_castandrole = []
        item["cast_org"] = item.get("cast", [])
        if "cast" in item and isinstance(item["cast"], list):
            for castmember in item["cast"]:
                if isinstance(castmember, dict):
                    list_cast.append(castmember.get("name", ""))
                    list_castandrole.append((castmember["name"], castmember["role"]))
                else:
                    list_cast.append(castmember)
                    list_castandrole.append((castmember, ""))

        item["cast"] = list_cast
        item["castandrole"] = list_castandrole

        if "season" in item and "episode" in item:
            properties["episodeno"] = "s%se%s" % (item.get("season"), item.get("episode"))
        if "resume" in item:
            properties["resumetime"] = str(item['resume']['position'])
            properties["totaltime"] = str(item['resume']['total'])
            properties['StartOffset'] = str(item['resume']['position'])

        # streamdetails
        if "streamdetails" in item:
            streamdetails = item["streamdetails"]
            audiostreams = streamdetails.get('audio', [])
            videostreams = streamdetails.get('video', [])
            subtitles = streamdetails.get('subtitle', [])
            if len(videostreams) > 0:
                stream = videostreams[0]
                height = stream.get("height", "")
                width = stream.get("width", "")
                if height and width:
                    resolution = ""
                    if width <= 720 and height <= 480:
                        resolution = "480"
                    elif width <= 768 and height <= 576:
                        resolution = "576"
                    elif width <= 960 and height <= 544:
                        resolution = "540"
                    elif width <= 1280 and height <= 720:
                        resolution = "720"
                    elif width <= 1920 and height <= 1080:
                        resolution = "1080"
                    elif width * height >= 6000000:
                        resolution = "4K"
                    properties["VideoResolution"] = resolution
                if stream.get("codec", ""):
                    properties["VideoCodec"] = str(stream["codec"])
                if stream.get("aspect", ""):
                    properties["VideoAspect"] = str(round(stream["aspect"], 2))
                item["streamdetails"]["video"] = stream

            # grab details of first audio stream
            if len(audiostreams) > 0:
                stream = audiostreams[0]
                properties["AudioCodec"] = stream.get('codec', '')
                properties["AudioChannels"] = str(stream.get('channels', ''))
                properties["AudioLanguage"] = stream.get('language', '')
                item["streamdetails"]["audio"] = stream

            # grab details of first subtitle
            if len(subtitles) > 0:
                properties["SubtitleLanguage"] = subtitles[0].get('language', '')
                item["streamdetails"]["subtitle"] = subtitles[0]
        else:
            item["streamdetails"] = {}
            item["streamdetails"]["video"] = {'duration': item.get('duration', 0)}

        # additional music properties
        if 'album_description' in item:
            properties["Album_Description"] = item.get('album_description')

        # pvr properties
        if "channellogo" in item:
            properties["channellogo"] = item["channellogo"]
            properties["channelicon"] = item["channellogo"]
        if "episodename" in item:
            properties["episodename"] = item["episodename"]
        if "channel" in item:
            properties["channel"] = item["channel"]
            properties["channelname"] = item["channel"]
            item["label2"] = item["title"]

        # artwork
        art = item.get("art", {})
        if item["type"] in ["episode", "season"]:
            if not art.get("fanart") and art.get("season.fanart"):
                art["fanart"] = art["season.fanart"]
            if not art.get("poster") and art.get("season.poster"):
                art["poster"] = art["season.poster"]
            if not art.get("landscape") and art.get("season.landscape"):
                art["poster"] = art["season.landscape"]
            if not art.get("fanart") and art.get("tvshow.fanart"):
                art["fanart"] = art.get("tvshow.fanart")
            if not art.get("poster") and art.get("tvshow.poster"):
                art["poster"] = art.get("tvshow.poster")
            if not art.get("clearlogo") and art.get("tvshow.clearlogo"):
                art["clearlogo"] = art.get("tvshow.clearlogo")
            if not art.get("banner") and art.get("tvshow.banner"):
                art["banner"] = art.get("tvshow.banner")
            if not art.get("landscape") and art.get("tvshow.landscape"):
                art["landscape"] = art.get("tvshow.landscape")
        if not art.get("fanart") and item.get('fanart'):
            art["fanart"] = item.get('fanart')
        if not art.get("thumb") and item.get('thumbnail'):
            art["thumb"] = get_clean_image(item.get('thumbnail'))
        if not art.get("thumb") and art.get('poster'):
            art["thumb"] = get_clean_image(art.get('poster'))
        if not art.get("thumb") and item.get('icon'):
            art["thumb"] = get_clean_image(item.get('icon'))
        if not item.get("thumbnail") and art.get('thumb'):
            item["thumbnail"] = art["thumb"]

        # clean art
        for key, value in art.iteritems():
            if not isinstance(value, (str, unicode)):
                art[key] = ""
            elif value:
                art[key] = get_clean_image(value)
        item["art"] = art

        item["extraproperties"] = properties

        # return the result
        return item

    except Exception:
        utils.ERROR(notify=True)
        LOG.error('item that caused crash: %s', item)


def create_listitem(item, as_tuple=True, offscreen=True):
    """
    helper to create a kodi listitem from kodi compatible dict with mediainfo

    WARNING: paths, so item['file'] for items NOT synched to the Kodi DB
             shall NOT occur in the Kodi paths table!
             Kodi information screen does not work otherwise

    Code from script.module.metadatautils, kodidb.py
    """
    try:
        if v.KODIVERSION > 17:
            liz = xbmcgui.ListItem(
                label=item.get("label", ""),
                label2=item.get("label2", ""),
                path=item['file'],
                offscreen=offscreen)
        else:
            liz = xbmcgui.ListItem(
                label=item.get("label", ""),
                label2=item.get("label2", ""),
                path=item['file'])

        # only set isPlayable prop if really needed
        if item.get("isFolder", False):
            liz.setProperty('IsPlayable', 'false')
        elif "plugin://script.skin.helper" not in item['file']:
            liz.setProperty('IsPlayable', 'true')

        nodetype = "Video"
        if item["type"] in ["song", "album", "artist"]:
            nodetype = "Music"

        # extra properties
        for key, value in item["extraproperties"].iteritems():
            liz.setProperty(key, value)

        # video infolabels
        if nodetype == "Video":
            infolabels = {
                "title": item.get("title"),
                "size": item.get("size"),
                "genre": item.get("genre"),
                "year": item.get("year"),
                "top250": item.get("top250"),
                "tracknumber": item.get("tracknumber"),
                "rating": item.get("rating"),
                "playcount": item.get("playcount"),
                "overlay": item.get("overlay"),
                "cast": item.get("cast"),
                "castandrole": item.get("castandrole"),
                "director": item.get("director"),
                "mpaa": item.get("mpaa"),
                "plot": item.get("plot"),
                "plotoutline": item.get("plotoutline"),
                "originaltitle": item.get("originaltitle"),
                "sorttitle": item.get("sorttitle"),
                "duration": item.get("duration"),
                "studio": item.get("studio"),
                "tagline": item.get("tagline"),
                "writer": item.get("writer"),
                "tvshowtitle": item.get("tvshowtitle"),
                "premiered": item.get("premiered"),
                "status": item.get("status"),
                "code": item.get("imdbnumber"),
                "imdbnumber": item.get("imdbnumber"),
                "aired": item.get("aired"),
                "credits": item.get("credits"),
                "album": item.get("album"),
                "artist": item.get("artist"),
                "votes": item.get("votes"),
                "trailer": item.get("trailer"),
                # "progress": item.get('progresspercentage')
            }
            if item["type"] == "episode":
                infolabels["season"] = item["season"]
                infolabels["episode"] = item["episode"]

            # streamdetails
            if item.get("streamdetails"):
                liz.addStreamInfo("video", item["streamdetails"].get("video", {}))
                liz.addStreamInfo("audio", item["streamdetails"].get("audio", {}))
                liz.addStreamInfo("subtitle", item["streamdetails"].get("subtitle", {}))

            if "dateadded" in item:
                infolabels["dateadded"] = item["dateadded"]
            if "date" in item:
                infolabels["date"] = item["date"]

        # music infolabels
        else:
            infolabels = {
                "title": item.get("title"),
                "size": item.get("size"),
                "genre": item.get("genre"),
                "year": item.get("year"),
                "tracknumber": item.get("track"),
                "album": item.get("album"),
                "artist": " / ".join(item.get('artist')),
                "rating": str(item.get("rating", 0)),
                "lyrics": item.get("lyrics"),
                "playcount": item.get("playcount")
            }
            if "date" in item:
                infolabels["date"] = item["date"]
            if "duration" in item:
                infolabels["duration"] = item["duration"]
            if "lastplayed" in item:
                infolabels["lastplayed"] = item["lastplayed"]

        # setting the dbtype and dbid is supported from kodi krypton and up
        # PKC hack: ignore empty type
        if item["type"] not in ["recording", "channel", "favourite", ""]:
            infolabels["mediatype"] = item["type"]
            # setting the dbid on music items is not supported ?
            if nodetype == "Video" and "DBID" in item["extraproperties"]:
                infolabels["dbid"] = item["extraproperties"]["DBID"]

        if "lastplayed" in item:
            infolabels["lastplayed"] = item["lastplayed"]

        # assign the infolabels
        liz.setInfo(type=nodetype, infoLabels=infolabels)

        # artwork
        liz.setArt(item.get("art", {}))
        if "icon" in item:
            liz.setIconImage(item['icon'])
        if "thumbnail" in item:
            liz.setThumbnailImage(item['thumbnail'])

        # contextmenu
        if item["type"] in ["episode", "season"] and "season" in item and "tvshowid" in item:
            # add series and season level to widgets
            if "contextmenu" not in item:
                item["contextmenu"] = []
            item["contextmenu"] += [
                (xbmc.getLocalizedString(20364), "ActivateWindow(Video,videodb://tvshows/titles/%s/,return)"
                    % (item["tvshowid"])),
                (xbmc.getLocalizedString(20373), "ActivateWindow(Video,videodb://tvshows/titles/%s/%s/,return)"
                    % (item["tvshowid"], item["season"]))]
        if "contextmenu" in item:
            liz.addContextMenuItems(item["contextmenu"])

        if as_tuple:
            return (item["file"], liz, item.get("isFolder", False))
        else:
            return liz
    except Exception:
        utils.ERROR(notify=True)
        LOG.error('item that should have been turned into a listitem: %s', item)


def create_main_entry(item):
    '''helper to create a simple (directory) listitem'''
    return {
        'title': item[0],
        'label': item[0],
        'file': item[1],
        'icon': item[2],
        'art': {
            'thumb': 'special://home/addons/%s/icon.png' % v.ADDON_ID,
            'fanart': 'special://home/addons/%s/fanart.jpg' % v.ADDON_ID},
        'isFolder': True,
        'type': '',
        'IsPlayable': 'false'
    }

