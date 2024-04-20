#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Code from script.module.metadatautils, kodidb.py

Loads of different functions called in SEPARATE Python instances through
e.g. plugin://... calls. Hence be careful to only rely on window variables.
"""
from logging import getLogger

import xbmc
import xbmcgui
import xbmcvfs

from . import json_rpc as js, utils, variables as v

LOG = getLogger('PLEX.widget')

# To easily use threadpool, we can only pass one argument
PLEX_TYPE = None
SECTION_ID = None
APPEND_SHOW_TITLE = None
APPEND_SXXEXX = None
SYNCHED = True
# Need to chain the PMS keys
KEY = None

# use getVideoInfoTag to set some list item properties
USE_TAGS = v.KODIVERSION >= 20
# properties that should be set by tag methods
TAG_PROPERTIES = ("resumetime", "totaltime")

def get_clean_image(image):
    '''
    helper to strip all kodi tags/formatting of an image path/url
    Pass in either unicode or str; returns unicode
    '''
    if not image:
        return ''
    if 'music@' in image:
        # fix for embedded images
        thumbcache = xbmc.getCacheThumbName(image)
        thumbcache = thumbcache.replace('.tbn', '.jpg')
        thumbcache = 'special://thumbnails/%s/%s' % (thumbcache[0], thumbcache)
        if not xbmcvfs.exists(thumbcache):
            xbmcvfs.copy(image, thumbcache)
        image = thumbcache
    if image and 'image://' in image:
        image = image.replace('image://', '')
        image = utils.unquote(image)
        if image.endswith('/'):
            image = image[:-1]
        return image
    else:
        return image


def generate_item(api):
    """
    Meant to be consumed by metadatautils.kodidb.prepare_listitem(), and then
    subsequently by metadatautils.kodidb.create_listitem()

    Do NOT set resumetime - otherwise Kodi always resumes at that time
    even if the user chose to start element from the beginning
        listitem.setProperty('resumetime', str(userdata['Resume']))

    The key 'file' needs to be set later with the item's path
    """
    try:
        if api.tag in ('Directory', 'Playlist', 'Hub'):
            return _generate_folder(api)
        else:
            return _generate_content(api)
    except Exception:
        # Usefull to catch everything here since we're using threadpool
        LOG.error('xml that caused the crash: "%s": %s',
                  api.tag, api.attrib)
        utils.ERROR(notify=True)


def _generate_folder(api):
    '''Generates "folder"/"directory" items that user can further navigate'''
    typus = ''
    if api.plex_type == v.PLEX_TYPE_GENRE:
        # Unfortunately, 'genre' is not yet supported by Kodi
        # typus = v.KODI_TYPE_GENRE
        pass
    elif api.plex_type == v.PLEX_TYPE_SHOW:
        typus = v.KODI_TYPE_SHOW
    elif api.plex_type == v.PLEX_TYPE_SEASON:
        typus = v.KODI_TYPE_SEASON
    elif api.plex_type == v.PLEX_TYPE_ARTIST:
        typus = v.KODI_TYPE_ARTIST
    elif api.plex_type == v.PLEX_TYPE_ALBUM:
        typus = v.KODI_TYPE_ALBUM
    elif api.fast_key and '?collection=' in api.fast_key:
        typus = v.KODI_TYPE_SET
    if typus and typus != v.KODI_TYPE_SET:
        content = _generate_content(api)
        content['type'] = typus
        content['file'] = api.directory_path(section_id=SECTION_ID,
                                             plex_type=PLEX_TYPE,
                                             old_key=KEY)
        content['isFolder'] = True
        content['IsPlayable'] = 'false'
        return content
    else:
        art = api.artwork()
        title = api.title() if api.plex_type != v.PLEX_TYPE_TAG else api.tag_label()
        return {
            'title': title,
            'label': title,
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
            'type': typus,
            'IsPlayable': 'false',
        }


def _generate_content(api):
    plex_type = api.plex_type
    if api.kodi_id:
        # Item is synched to the Kodi db - let's use that info
        # (will thus e.g. include additional artwork or metadata)
        item = js.item_details(api.kodi_id, api.kodi_type)

    # In rare cases, Kodi's JSON reply does not provide 'title' plus potentially
    # other fields - let's use the PMS answer to be safe
    # See https://github.com/croneter/PlexKodiConnect/issues/1129
    if not api.kodi_id or 'title' not in item:
        if api.plex_type == v.PLEX_TYPE_PHOTO:
            item = {
                'title': api.title(),
                'label': api.title(),
                'type': api.kodi_type,
                'dateadded': api.date_created(),  # e.g '2019-01-03 19:40:59'
                'lastplayed': api.lastplayed(),  # e.g. '2019-01-04 16:05:03'
                'playcount': api.viewcount(),
            }
            item.update(api.picture_codec())
        else:
            cast = [{
                'name': x[0],
                'thumbnail': x[1],
                'role': x[2],
                'order': x[3],
            } for x in api.people()['actor']]
            item = {
                'cast': cast,
                'country': api.countries(),
                'dateadded': api.date_created(),  # e.g '2019-01-03 19:40:59'
                'director': api.directors(),  # list of [str]
                'duration': api.runtime(),
                'episode': api.index(),
                'genre': api.genres(),
                # 'imdbnumber': '',  # e.g.'341663'
                'label': api.title(),  # e.g. '1x05. Category 55 Emergency Doomsday Crisis'
                'lastplayed': api.lastplayed(),  # e.g. '2019-01-04 16:05:03'
                'mpaa': api.content_rating(),  # e.g. 'TV-MA'
                'originaltitle': '',  # e.g. 'Titans (2018)'
                'playcount': api.viewcount(),  # [int]
                'plot': api.plot(),  # [str]
                'plotoutline': api.tagline(),
                'premiered': api.premiere_date(),  # '2018-10-12'
                'rating': api.rating(),  # [float]
                'ratingtype': api.ratingtype(),  # [str] image location
                'season': api.season_number(),
                'sorttitle': api.sorttitle(),  # 'Titans (2018)'
                'studio': api.studios(),
                'tag': api.labels(),  # List of tags this item belongs to
                'tagline': api.tagline(),
                'thumbnail': '',  # e.g. 'image://https%3a%2f%2fassets.tv'
                'title': api.title(),  # 'Titans (2018)'
                'type': api.kodi_type,
                'trailer': api.trailer(),
                'tvshowtitle': api.show_title(),
                'uniqueid': {
                    'imdbnumber': api.guids.get('imdb') or '',
                    'tvdb_id': api.guids.get('tvdb') or '',
                    'tmdb_id': api.guids.get('tmdb') or ''
                },
                'votes': '0',  # [str]!
                'writer': api.writers(),  # list of [str]
                'year': api.year(),  # [int]
            }
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
                    'total': api.runtime()
                }
            if plex_type in (v.PLEX_TYPE_EPISODE, v.PLEX_TYPE_SEASON, v.PLEX_TYPE_SHOW):
                leaves = api.leave_count()
                if leaves:
                    item['extraproperties'] = leaves
        # Add all the artwork we can
        item['art'] = api.artwork(full_artwork=True)

    item['icon'] = v.ICON_FROM_PLEXTYPE[plex_type]
    # Some customization
    if plex_type == v.PLEX_TYPE_EPISODE:
        # Prefix to the episode's title/label
        if api.season_number() is not None and api.index() is not None:
            if APPEND_SXXEXX is True:
                item['title'] = "S%.2dE%.2d - %s" % (api.season_number(), api.index(), item['title'])
        if APPEND_SHOW_TITLE is True:
            item['title'] = "%s - %s " % (api.show_title(), item['title'])
        item['label'] = item['title']

    # Determine the path for this item
    key = api.path_and_plex_id()
    if key.startswith('/system/services') or key.startswith('http'):
        params = {
            'mode': 'plex_node',
            'key': key,
            'offset': api.resume_point_plex()
        }
        url = utils.extend_url('plugin://%s' % v.ADDON_ID, params)
    elif plex_type == v.PLEX_TYPE_PHOTO:
        url = api.get_picture_path()
    else:
        url = api.fullpath(force_first_media=True)[0]
    if not api.kodi_id and plex_type == v.PLEX_TYPE_EPISODE:
        # Hack - Item is not synched to the Kodi database
        # We CANNOT use paths that show up in the Kodi paths table!
        url = url.replace('plugin.video.plexkodiconnect.tvshows',
                          'plugin.video.plexkodiconnect')
    item['file'] = url
    return item


def prepare_listitem(item, listing_key = None):
    """helper to convert kodi output from json api to compatible format for
    listitems"""
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
            if (item["runtime"] // 60) > 300:
                item["duration"] = item["runtime"] // 60
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

        if listing_key is not None:
            properties["LISTINGKEY"] = listing_key

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
        # if "starttime" in item:
        #     # convert utc time to local time
        #     item["starttime"] = utils.localdate_from_utc_string(item["starttime"])
        #     item["endtime"] = utils.localdate_from_utc_string(item["endtime"])
        #     # set localized versions of the time and date as additional props
        #     startdate, starttime = utils.localized_date_time(item['starttime'])
        #     enddate, endtime = utils.localized_date_time(item['endtime'])
        #     properties["StartTime"] = starttime
        #     properties["StartDate"] = startdate
        #     properties["EndTime"] = endtime
        #     properties["EndDate"] = enddate
        #     properties["Date"] = "%s %s-%s" % (startdate, starttime, endtime)
        #     properties["StartDateTime"] = "%s %s" % (startdate, starttime)
        #     properties["EndDateTime"] = "%s %s" % (enddate, endtime)
        #     # set date to startdate
        #     item["date"] = arrow.get(item["starttime"]).format("DD.MM.YYYY")
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
        for key, value in art.items():
            if not isinstance(value, str):
                art[key] = ""
            elif value:
                art[key] = get_clean_image(value)
        item["art"] = art

        item["extraproperties"] = properties

        if "file" not in item or not item['file']:
            LOG.warn('No filepath for item: %s', item)
            item["file"] = ""

        return item

    except Exception as exc:
        LOG.error('item: %s', item)
        LOG.exception('Exception encountered: %s', exc)


def create_listitem(item, as_tuple=True, offscreen=True,
                    listitem=xbmcgui.ListItem):
    """helper to create a kodi listitem from kodi compatible dict with mediainfo"""
    try:
        # PKCListItem does not implement getVideoInfoTag
        use_tags_for_item = USE_TAGS and listitem == xbmcgui.ListItem

        liz = listitem(
            label=item.get("label", ""),
            label2=item.get("label2", ""),
            path=item['file'],
            offscreen=offscreen)

        # only set isPlayable prop if really needed
        if item.get("isFolder", False):
            liz.setProperty('IsPlayable', 'false')
        elif "plugin://script.skin.helper" not in item['file']:
            liz.setProperty('IsPlayable', 'true')

        nodetype = "Video"
        if item["type"] in ["song", "album", "artist"]:
            nodetype = "Music"
        elif item['type'] == 'photo':
            nodetype = 'Pictures'

        # extra properties
        for key, value in item["extraproperties"].items():
            # some Video properties should be set via tags on newer kodi versions
            if nodetype != "Video" or not use_tags_for_item or key not in TAG_PROPERTIES:
                liz.setProperty(key, value)

        # video infolabels
        if nodetype == "Video":
            infolabels = {
                "title": item.get("title"),
                "path": item.get("file"),
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
                "tag": item.get("tag"),
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
                "trailer": item.get("trailer")
            }
            if item["type"] == "episode":
                infolabels["season"] = item["season"]
                infolabels["episode"] = item["episode"]

            # streamdetails
            if item.get("streamdetails"):
                if use_tags_for_item:
                    tags = liz.getVideoInfoTag()
                    tags.addVideoStream(_create_VideoStreamDetail(item["streamdetails"].get("video", {})))
                    tags.addAudioStream(_create_AudioStreamDetail(item["streamdetails"].get("audio", {})))
                    tags.addSubtitleStream(_create_SubtitleStreamDetail(item["streamdetails"].get("subtitle", {})))

                else:
                    liz.addStreamInfo("video", item["streamdetails"].get("video", {}))
                    liz.addStreamInfo("audio", item["streamdetails"].get("audio", {}))
                    liz.addStreamInfo("subtitle", item["streamdetails"].get("subtitle", {}))

            if "dateadded" in item:
                infolabels["dateadded"] = item["dateadded"]
            if "date" in item:
                infolabels["date"] = item["date"]

            if use_tags_for_item and "resumetime" in item["extraproperties"] and "totaltime" in item["extraproperties"]:
                tags = liz.getVideoInfoTag()
                tags.setResumePoint(float(item["extraproperties"].get("resumetime")), float(item["extraproperties"].get("totaltime")));

        # music infolabels
        elif nodetype == 'Music':
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

        else:
            # Pictures
            infolabels = {
                "title": item.get("title"),
                'picturepath': item['file']
            }

        # setting the dbtype and dbid is supported from kodi krypton and up
        if item["type"] not in ["recording", "channel", "favourite", "genre", "categorie"]:
            infolabels["mediatype"] = item["type"]
            # setting the dbid on music items is not supported ?
            if nodetype == "Video" and "DBID" in item["extraproperties"]:
                infolabels["dbid"] = item["extraproperties"]["DBID"]

        if "lastplayed" in item:
            infolabels["lastplayed"] = item["lastplayed"]

        # assign the infolabels
        if use_tags_for_item and nodetype == "Video":
            # filter out None valued properties
            infolabels = {k: v for k, v in infolabels.items() if v is not None}

            tags = liz.getVideoInfoTag() # type: xbmc.InfoTagVideo

            if "dbid" in infolabels:
                tags.setDbId(int(infolabels["dbid"]))
            if "year" in infolabels:
                tags.setYear(int(infolabels["year"]))
            if "episode" in infolabels:
                tags.setEpisode(int(infolabels["episode"]))
            if "season" in infolabels:
                tags.setSeason(int(infolabels["season"]))
            if "top250" in infolabels:
                tags.setTop250(int(infolabels["top250"]))
            if "tracknumber" in infolabels:
                tags.setTrackNumber(int(infolabels["tracknumber"]))
            if "rating" in infolabels:
                tags.setRating(float(infolabels["rating"]))
            if "playcount" in infolabels:
                tags.setPlaycount(int(infolabels["playcount"]))
            if "cast" in infolabels:
                actors = []

                for actor_name in infolabels["cast"]:
                    actors.append(xbmc.Actor(actor_name))

                tags.setCast(actors)
            if "castandrole" in infolabels:
                actors = []

                for actor in infolabels["castandrole"]:
                    actors.append(xbmc.Actor(actor[0], actor[1]))

                tags.setCast(actors)
            if "artist" in infolabels:
                tags.setArtists(infolabels["artist"])
            if "genre" in infolabels:
                tags.setGenres(infolabels["genre"].split(" / "))
            if "country" in infolabels:
                tags.setCountries(infolabels["country"])
            if "director" in infolabels:
                tags.setDirectors(infolabels["director"].split(" / "))
            if "mpaa" in infolabels:
                tags.setMpaa(str(infolabels["mpaa"]))
            if "plot" in infolabels:
                tags.setPlot(str(infolabels["plot"]))
            if "plotoutline" in infolabels:
                tags.setPlotOutline(str(infolabels["plotoutline"]))
            if "title" in infolabels:
                tags.setTitle(str(infolabels["title"]))
            if "originaltitle" in infolabels:
                tags.setOriginalTitle(str(infolabels["originaltitle"]))
            if "sorttitle" in infolabels:
                tags.setSortTitle(str(infolabels["sorttitle"]))
            if "duration" in infolabels:
                tags.setDuration(int(infolabels["duration"]))
            if "studio" in infolabels:
                tags.setStudios(infolabels["studio"].split(" / "))
            if "tagline" in infolabels:
                tags.setTagLine(str(infolabels["tagline"]))
            if "writer" in infolabels:
                tags.setWriters(infolabels["writer"].split(" / "))
            if "tvshowtitle" in infolabels:
                tags.setTvShowTitle(str(infolabels["tvshowtitle"]))
            if "premiered" in infolabels:
                tags.setPremiered(str(infolabels["premiered"]))
            if "status" in infolabels:
                tags.setTvShowStatus(str(infolabels["status"]))
            if "set" in infolabels:
                tags.setSet(str(infolabels["set"]))
            if "setoverview" in infolabels:
                tags.setSetOverview(str(infolabels["setoverview"]))
            if "tag" in infolabels:
                tags.setTags(infolabels["tag"])
            if "imdbnumber" in infolabels:
                tags.setIMDBNumber(str(infolabels["imdbnumber"]))
            if "code" in infolabels:
                tags.setProductionCode(str(infolabels["code"]))
            if "aired" in infolabels:
                tags.setFirstAired(str(infolabels["aired"]))
            if "lastplayed" in infolabels:
                tags.setLastPlayed(str(infolabels["lastplayed"]))
            if "album" in infolabels:
                tags.setAlbum(str(infolabels["album"]))
            if "votes" in infolabels:
                tags.setVotes(int(infolabels["votes"]))
            if "trailer" in infolabels:
                tags.setTrailer(str(infolabels["trailer"]))
            if "path" in infolabels:
                tags.setPath(str(infolabels["path"]))
            if "filenameandpath" in infolabels:
                tags.setFilenameAndPath(str(infolabels["filenameandpath"]))
            if "dateadded" in infolabels:
                tags.setDateAdded(str(infolabels["dateadded"]))
            if "mediatype" in infolabels:
                tags.setMediaType(str(infolabels["mediatype"]))

        else:
            liz.setInfo(type=nodetype, infoLabels=infolabels)

        # artwork
        liz.setArt(item.get("art", {}))
        if "icon" in item:
            liz.setArt({"icon": item['icon']})
        if "thumbnail" in item:
            liz.setArt({"thumb": item['thumbnail']})

        # contextmenu
        if item["type"] in ["episode", "season"] and "season" in item and "tvshowid" in item:
            # add series and season level to widgets
            if "contextmenu" not in item:
                item["contextmenu"] = []
            item["contextmenu"] += [
                (xbmc.getLocalizedString(20364), "ActivateWindow(Videos,videodb://tvshows/titles/%s/,return)"
                    % (item["tvshowid"])),
                (xbmc.getLocalizedString(20373), "ActivateWindow(Videos,videodb://tvshows/titles/%s/%s/,return)"
                    % (item["tvshowid"], item["season"]))]
        if "contextmenu" in item:
            liz.addContextMenuItems(item["contextmenu"])

        if as_tuple:
            return item["file"], liz, item.get("isFolder", False)
        else:
            return liz
    except Exception as exc:
        LOG.error('item: %s', item)
        LOG.exception('Exception encountered: %s', exc)


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


def _create_VideoStreamDetail(stream):
    '''Creates a VideoStreamDetail object from a video stream'''
    stream_detail = xbmc.VideoStreamDetail()

    if "codec" in stream:
        stream_detail.setCodec(str(stream["codec"]))
    if "aspect" in stream:
        stream_detail.setAspect(round(stream["aspect"], 2))
    if "width" in stream:
        stream_detail.setWidth(int(stream["width"]))
    if "height" in stream:
        stream_detail.setHeight(int(stream["height"]))
    if "duration" in stream:
        stream_detail.setDuration(int(stream["duration"]))
    if "stereomode" in stream:
        stream_detail.setStereoMode(str(stream["stereomode"]))
    if "language" in stream:
        stream_detail.setLanguage(str(stream["language"]))
    if "hdrtype" in stream:
        stream_detail.setHDRType(str(stream["hdrtype"]))

    return stream_detail


def _create_AudioStreamDetail(stream):
    '''Creates a AudioStreamDetail object from an audio stream'''
    stream_detail = xbmc.AudioStreamDetail()

    if "channels" in stream:
        stream_detail.setChannels(int(stream["channels"]))
    if "codec" in stream:
        stream_detail.setCodec(str(stream["codec"]))
    if "language" in stream:
        stream_detail.setLanguage(str(stream["language"]))

    return stream_detail


def _create_SubtitleStreamDetail(stream):
    '''Creates a SubtitleStreamDetail object from a subtitle stream'''
    stream_detail = xbmc.SubtitleStreamDetail()

    if "language" in stream:
        stream_detail.setLanguage(str(stream["language"]))

    return stream_detail
