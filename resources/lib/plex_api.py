#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Taken from iBaa, https://github.com/iBaa/PlexConnect
Point of time: December 22, 2015


Collection of "connector functions" to Plex Media Server/MyPlex


PlexGDM:
loosely based on hippojay's plexGDM:
https://github.com/hippojay/script.plexbmc.helper... /resources/lib/plexgdm.py


Plex Media Server communication:
source (somewhat): https://github.com/hippojay/plugin.video.plexbmc
later converted from httplib to urllib2


Transcoder support:
PlexAPI_getTranscodePath() based on getTranscodeURL from pyplex/plexAPI
https://github.com/megawubs/pyplex/blob/master/plexAPI/info.py


MyPlex - Basic Authentication:
http://www.voidspace.org.uk/python/articles/urllib2.shtml
http://www.voidspace.org.uk/python/articles/authentication.shtml
http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
http://stackoverflow.com/questions/111945/is-there-any-way-to-do-http-put-in-python
(and others...)
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from re import sub
from urllib import urlencode, unquote, quote
from urlparse import parse_qsl
from xbmcgui import ListItem

from .downloadutils import DownloadUtils as DU
from . import clientinfo
from . import utils
from . import path_ops
from . import plex_functions as PF
from . import plexdb_functions as plexdb
from . import kodidb_functions as kodidb
from . import variables as v
from . import state

###############################################################################
LOG = getLogger('PLEX.plex_api')

###############################################################################


def _unicode_or_none(value):
    """
    Tries to decode value to unicode. Returns None if this fails
    """
    try:
        return value.decode('utf-8')
    except TypeError:
        # e.g. Android TV's Python
        return value.decode()
    except AttributeError:
        pass


class API(object):
    """
    API(item)

    Processes a Plex media server's XML response

    item: xml.etree.ElementTree element
    """
    def __init__(self, item):
        self.item = item
        # which media part in the XML response shall we look at?
        self.part = 0
        self.mediastream = None
        self.server = utils.window('pms_server')

    def set_part_number(self, number=None):
        """
        Sets the part number to work with (used to deal with Movie with several
        parts).
        """
        self.part = number or 0

    def plex_type(self):
        """
        Returns the type of media, e.g. 'movie' or 'clip' for trailers as
        Unicode or None.
        """
        return _unicode_or_none(self.item.get('type'))

    def playlist_type(self):
        """
        Returns the playlist type ('video', 'audio') or None
        """
        return self.item.get('playlistType')

    def updated_at(self):
        """
        Returns the last time this item was updated as unicode, e.g.
        '1524739868', or None
        """
        return self.item.get('updatedAt')

    def checksum(self):
        """
        Returns a string, not int.
        WATCH OUT - time in Plex, not Kodi ;-)
        """
        # Include a letter to prohibit saving as an int!
        return "K%s%s" % (self.plex_id(), self.item.get('updatedAt', ''))

    def plex_id(self):
        """
        Returns the Plex ratingKey such as '246922' as Unicode or None
        """
        return _unicode_or_none(self.item.get('ratingKey'))

    def path(self, force_first_media=True, force_addon=False,
             direct_paths=None):
        """
        Returns a "fully qualified path": add-on paths or direct paths
        depending on the current settings. Will NOT valide the playurl
        Returns unicode or None if something went wrong.

        Pass direct_path=True if you're calling from another Plex python
        instance - because otherwise direct paths will evaluate to False!
        """
        direct_paths = direct_paths or state.DIRECT_PATHS
        filename = self.file_path(force_first_media=force_first_media)
        if (not direct_paths or force_addon or
                self.plex_type() == v.PLEX_TYPE_CLIP):
            if filename and '/' in filename:
                filename = filename.rsplit('/', 1)
            elif filename:
                filename = filename.rsplit('\\', 1)
            try:
                filename = filename[1]
            except (TypeError, IndexError):
                filename = None
            # Set plugin path and media flags using real filename
            if self.plex_type() == v.PLEX_TYPE_EPISODE:
                # need to include the plex show id in the path
                path = ('plugin://plugin.video.plexkodiconnect.tvshows/%s/'
                        % self.grandparent_id())
            else:
                path = 'plugin://%s/' % v.ADDON_TYPE[self.plex_type()]
            path = ('%s?plex_id=%s&plex_type=%s&mode=play&filename=%s'
                    % (path, self.plex_id(), self.plex_type(), filename))
        else:
            # Direct paths is set the Kodi way
            path = self.validate_playurl(filename,
                                         self.plex_type(),
                                         omit_check=True)
        return path

    def path_and_plex_id(self):
        """
        Returns the Plex key such as '/library/metadata/246922' or None
        """
        return self.item.get('key')

    def plex_media_streams(self):
        """
        Returns the media streams directly from the PMS xml.
        Mind self.mediastream to be set before and self.part!
        """
        return self.item[self.mediastream][self.part]

    def file_name(self, force_first_media=False):
        """
        Returns only the filename, e.g. 'movie.mkv' as unicode or None if not
        found
        """
        ans = self.file_path(force_first_media=force_first_media)
        if ans is None:
            return
        if "\\" in ans:
            # Local path
            filename = ans.rsplit("\\", 1)[1]
        else:
            try:
                # Network share
                filename = ans.rsplit("/", 1)[1]
            except IndexError:
                # E.g. certain Plex channels
                filename = None
        return filename

    def file_path(self, force_first_media=False):
        """
        Returns the direct path to this item, e.g. '\\NAS\movies\movie.mkv'
        or None

        force_first_media=True:
            will always use 1st media stream, e.g. when several different
            files are present for the same PMS item
        """
        if self.mediastream is None and force_first_media is False:
            self.mediastream_number()
        try:
            if force_first_media is False:
                ans = self.item[self.mediastream][self.part].attrib['file']
            else:
                ans = self.item[0][self.part].attrib['file']
        except (TypeError, AttributeError, IndexError, KeyError):
            ans = None
        if ans is not None:
            try:
                ans = utils.try_decode(unquote(ans))
            except UnicodeDecodeError:
                # Sometimes, Plex seems to have encoded in latin1
                ans = unquote(ans).decode('latin1')
        return ans

    def get_picture_path(self):
        """
        Returns the item's picture path (transcode, if necessary) as string.
        Will always use addon paths, never direct paths
        """
        extension = self.item[0][0].attrib['key'][self.item[0][0].attrib['key'].rfind('.'):].lower()
        if (utils.window('plex_force_transcode_pix') == 'true' or
                extension not in v.KODI_SUPPORTED_IMAGES):
            # Let Plex transcode
            # max width/height supported by plex image transcoder is 1920x1080
            path = self.server + PF.transcode_image_path(
                self.item[0][0].get('key'),
                utils.window('pms_token'),
                "%s%s" % (self.server, self.item[0][0].get('key')),
                1920,
                1080)
        else:
            path = self.attach_plex_token_to_url(
                '%s%s' % (utils.window('pms_server'),
                          self.item[0][0].attrib['key']))
        # Attach Plex id to url to let it be picked up by our playqueue agent
        # later
        return utils.try_encode('%s&plex_id=%s' % (path, self.plex_id()))

    def tv_show_path(self):
        """
        Returns the direct path to the TV show, e.g. '\\NAS\tv\series'
        or None
        """
        res = None
        for child in self.item:
            if child.tag == 'Location':
                res = child.get('path')
        return res

    def season_number(self):
        """
        Returns the 'index' of an PMS XML reply. Depicts e.g. season number.
        """
        return self.item.get('index')

    def date_created(self):
        """
        Returns the date when this library item was created.

        If not found, returns 2000-01-01 10:00:00
        """
        res = self.item.get('addedAt')
        if res is not None:
            res = utils.unix_date_to_kodi(res)
        else:
            res = '2000-01-01 10:00:00'
        return res

    def viewcount(self):
        """
        Returns the play count for the item as an int or the int 0 if not found
        """
        try:
            return int(self.item.attrib['viewCount'])
        except (KeyError, ValueError):
            return 0

    def userdata(self):
        """
        Returns a dict with None if a value is missing
        {
            'Favorite': favorite,                  # False, because n/a in Plex
            'PlayCount': playcount,
            'Played': played,                      # True/False
            'LastPlayedDate': lastPlayedDate,
            'Resume': resume,                      # Resume time in seconds
            'Runtime': runtime,
            'Rating': rating
        }
        """
        item = self.item.attrib
        # Default - attributes not found with Plex
        favorite = False
        try:
            playcount = int(item['viewCount'])
        except (KeyError, ValueError):
            playcount = None
        played = True if playcount else False

        try:
            last_played = utils.unix_date_to_kodi(int(item['lastViewedAt']))
        except (KeyError, ValueError):
            last_played = None

        if state.INDICATE_MEDIA_VERSIONS is True:
            userrating = 0
            for _ in self.item.findall('./Media'):
                userrating += 1
            # Don't show a value of '1'
            userrating = 0 if userrating == 1 else userrating
        else:
            try:
                userrating = int(float(item['userRating']))
            except (KeyError, ValueError):
                userrating = 0

        try:
            rating = float(item['audienceRating'])
        except (KeyError, ValueError):
            try:
                rating = float(item['rating'])
            except (KeyError, ValueError):
                rating = 0.0

        resume, runtime = self.resume_runtime()
        return {
            'Favorite': favorite,
            'PlayCount': playcount,
            'Played': played,
            'LastPlayedDate': last_played,
            'Resume': resume,
            'Runtime': runtime,
            'Rating': rating,
            'UserRating': userrating
        }

    def collection_list(self):
        """
        Returns a list of tuples of the collection id and tags or an empty list
            [(<collection id 1>, <collection name 1>), ...]
        """
        collections = []
        for child in self.item:
            if child.tag == 'Collection':
                collections.append((child.get('id'), child.get('tag')))
        return collections

    def people(self):
        """
        Returns a dict of lists of people found.
        {
            'Director': list,
            'Writer': list,
            'Cast': list of tuples (<actor>, <role>), <role> might be ''
            'Producer': list
        }
        """
        director = []
        writer = []
        cast = []
        producer = []
        for child in self.item:
            if child.tag == 'Director':
                director.append(child.attrib['tag'])
            elif child.tag == 'Writer':
                writer.append(child.attrib['tag'])
            elif child.tag == 'Role':
                cast.append((child.attrib['tag'], child.get('role', '')))
            elif child.tag == 'Producer':
                producer.append(child.attrib['tag'])
        return {
            'Director': director,
            'Writer': writer,
            'Cast': cast,
            'Producer': producer
        }

    def people_list(self):
        """
        Returns a dict with lists of tuples:
        {
            'actor': [..., (<name>, <artwork url>, <role>, <cast order>), ...],
            'director': [..., (<name>, ), ...],
            'writer': [..., (<name>, ), ...]
        }
        Everything in unicode, except <cast order> which is an int.
        Only <art-url> and <role> may be None if not found.

        Kodi does not yet support a Producer. People may appear several times
        per category and overall!
        """
        people = {
            'actor': [],
            'director': [],
            'writer': []
        }
        cast_order = 0
        for child in self.item:
            if child.tag == 'Role':
                people['actor'].append((child.attrib['tag'],
                                        child.get('thumb'),
                                        child.get('role'),
                                        cast_order))
                cast_order += 1
            elif child.tag == 'Writer':
                people['writer'].append((child.attrib['tag'], ))
            elif child.tag == 'Director':
                people['director'].append((child.attrib['tag'], ))
        return people

    def genre_list(self):
        """
        Returns a list of genres found. (Not a string)
        """
        genre = []
        for child in self.item:
            if child.tag == 'Genre':
                genre.append(child.attrib['tag'])
        return genre

    def guid_html_escaped(self):
        """
        Returns the 'guid' attribute, e.g.
            'com.plexapp.agents.thetvdb://76648/2/4?lang=en'
        as an HTML-escaped string or None
        """
        answ = self.item.get('guid')
        if answ is not None:
            answ = utils.escape_html(answ)
        return answ

    def provider(self, providername=None):
        """
        providername:  e.g. 'imdb', 'tvdb'

        Return IMDB, e.g. "tt0903624". Returns None if not found
        """
        try:
            item = self.item.attrib['guid']
        except KeyError:
            return None

        if providername == 'imdb':
            regex = utils.REGEX_IMDB
        elif providername == 'tvdb':
            # originally e.g. com.plexapp.agents.thetvdb://276564?lang=en
            regex = utils.REGEX_TVDB
        else:
            return None

        provider = regex.findall(item)
        try:
            provider = provider[0]
        except IndexError:
            provider = None
        return provider

    def title(self):
        """
        Returns the title of the element as unicode or 'Missing Title Name'
        """
        return utils.try_decode(self.item.get('title', 'Missing Title Name'))

    def titles(self):
        """
        Returns an item's name/title or "Missing Title Name".
        Output is the tuple
            title, sorttitle

        sorttitle = title, if no sorttitle is found
        """
        title = self.item.get('title', 'Missing Title Name')
        sorttitle = self.item.get('titleSort', title)
        return title, sorttitle

    def plot(self):
        """
        Returns the plot or None.
        """
        return self.item.get('summary')

    def tagline(self):
        """
        Returns a shorter tagline or None
        """
        return self.item.get('tagline')

    def audience_rating(self):
        """
        Returns the audience rating, 'rating' itself or 0.0
        """
        res = self.item.get('audienceRating')
        if res is None:
            res = self.item.get('rating')
        try:
            res = float(res)
        except (ValueError, TypeError):
            res = 0.0
        return res

    def year(self):
        """
        Returns the production(?) year ("year") or None
        """
        return self.item.get('year')

    def resume_point(self):
        """
        Returns the resume point of time in seconds as int. 0 if not found
        """
        try:
            resume = float(self.item.attrib['viewOffset'])
        except (KeyError, ValueError):
            resume = 0.0
        return resume * v.PLEX_TO_KODI_TIMEFACTOR

    def runtime(self):
        """
        Returns the total duration of the element as int. 0 if not found
        """
        try:
            runtime = float(self.item.attrib['duration'])
        except (KeyError, ValueError):
            runtime = 0.0
        return int(runtime * v.PLEX_TO_KODI_TIMEFACTOR)

    def resume_runtime(self):
        """
        Resume point of time and runtime/totaltime in rounded to seconds.
        Time from Plex server is measured in milliseconds.
        Kodi: seconds

        Output is the tuple:
            resume, runtime         as ints. 0 if not found
        """
        try:
            runtime = float(self.item.attrib['duration'])
        except (KeyError, ValueError):
            runtime = 0.0
        try:
            resume = float(self.item.attrib['viewOffset'])
        except (KeyError, ValueError):
            resume = 0.0
        runtime = runtime * v.PLEX_TO_KODI_TIMEFACTOR
        resume = resume * v.PLEX_TO_KODI_TIMEFACTOR
        return resume, runtime

    def content_rating(self):
        """
        Get the content rating or None
        """
        mpaa = self.item.get('contentRating')
        if mpaa is None:
            return
        # Convert more complex cases
        if mpaa in ("NR", "UR"):
            # Kodi seems to not like NR, but will accept Rated Not Rated
            mpaa = "Rated Not Rated"
        elif mpaa.startswith('gb/'):
            mpaa = mpaa.replace('gb/', 'UK:', 1)
        return mpaa

    def country_list(self):
        """
        Returns a list of all countries found in item.
        """
        country = []
        for child in self.item:
            if child.tag == 'Country':
                country.append(child.attrib['tag'])
        return country

    def premiere_date(self):
        """
        Returns the "originallyAvailableAt" or None
        """
        return self.item.get('originallyAvailableAt')

    def music_studio(self):
        """
        Returns the 'studio' or None
        """
        return self.item.get('studio')

    def music_studio_list(self):
        """
        Returns a list with a single entry for the studio, or an empty list
        """
        studio = []
        try:
            studio.append(self.replace_studio(self.item.attrib['studio']))
        except KeyError:
            pass
        return studio

    @staticmethod
    def replace_studio(studio_name):
        """
        Convert studio for Kodi to properly detect them
        """
        studios = {
            'abc (us)': "ABC",
            'fox (us)': "FOX",
            'mtv (us)': "MTV",
            'showcase (ca)': "Showcase",
            'wgn america': "WGN"
        }
        return studios.get(studio_name.lower(), studio_name)

    @staticmethod
    def list_to_string(listobject):
        """
        Smart-joins the listobject into a single string using a " / " separator
        If the list is empty, smart_join returns an empty string.
        """
        string = " / ".join(listobject)
        return string

    def parent_plex_id(self):
        """
        Returns the 'parentRatingKey' as a string or None
        """
        return self.item.get('parentRatingKey')

    def grandparent_id(self):
        """
        Returns the ratingKey for the corresponding grandparent, e.g. a TV show
        for episodes, or None
        """
        return self.item.get('grandparentRatingKey')

    def grandparent_title(self):
        """
        Returns the title for the corresponding grandparent, e.g. a TV show
        name for episodes, or None
        """
        return self.item.get('grandparentTitle')

    def episode_data(self):
        """
        Call on a single episode.

        Output: for the corresponding the TV show and season:
            [
                TV show key,        Plex: 'grandparentRatingKey'
                TV show title,      Plex: 'grandparentTitle'
                TV show season,     Plex: 'parentIndex'
                Episode number,     Plex: 'index'
            ]
        """
        return (self.item.get('grandparentRatingKey'),
                self.item.get('grandparentTitle'),
                self.item.get('parentIndex'),
                self.item.get('index'))

    @staticmethod
    def attach_plex_token_to_url(url):
        """
        Returns an extended URL with the Plex token included as 'X-Plex-Token='

        url may or may not already contain a '?'
        """
        if utils.window('pms_token') == '':
            return url
        if '?' not in url:
            url = "%s?X-Plex-Token=%s" % (url, utils.window('pms_token'))
        else:
            url = "%s&X-Plex-Token=%s" % (url, utils.window('pms_token'))
        return url

    def item_id(self):
        """
        Returns current playQueueItemID or if unsuccessful the playListItemID
        as Unicode.
        If not found, None is returned
        """
        return _unicode_or_none(self.item.get('playQueueItemID') or
                                self.item.get('playListItemID'))

    def _data_from_part_or_media(self, key):
        """
        Retrieves XML data 'key' first from the active part. If unsuccessful,
        tries to retrieve the data from the Media response part.

        If all fails, None is returned.
        """
        answ = self.item[0][self.part].get(key)
        if answ is None:
            answ = self.item[0].get(key)
        return answ

    def video_codec(self):
        """
        Returns the video codec and resolution for the child and part selected.
        If any data is not found on a part-level, the Media-level data is
        returned.
        If that also fails (e.g. for old trailers, None is returned)

        Output:
            {
                'videocodec': xxx,       e.g. 'h264'
                'resolution': xxx,       e.g. '720' or '1080'
                'height': xxx,           e.g. '816'
                'width': xxx,            e.g. '1920'
                'aspectratio': xxx,      e.g. '1.78'
                'bitrate': xxx,          e.g. '10642'
                'container': xxx         e.g. 'mkv',
                'bitDepth': xxx          e.g. '8', '10'
            }
        """
        answ = {
            'videocodec': self._data_from_part_or_media('videoCodec'),
            'resolution': self._data_from_part_or_media('videoResolution'),
            'height': self._data_from_part_or_media('height'),
            'width': self._data_from_part_or_media('width'),
            'aspectratio': self._data_from_part_or_media('aspectratio'),
            'bitrate': self._data_from_part_or_media('bitrate'),
            'container': self._data_from_part_or_media('container'),
        }
        try:
            answ['bitDepth'] = self.item[0][self.part][self.mediastream].get(
                'bitDepth')
        except (TypeError, AttributeError, KeyError, IndexError):
            answ['bitDepth'] = None
        return answ

    def extras(self):
        """
        Returns a list of XML etree elements for each extra, e.g. a trailer.
        """
        answ = []
        for extras in self.item.iterfind('Extras'):
            for extra in extras:
                answ.append(extra)
        return answ

    def trailers(self):
        """
        Returns the URL for a single trailer, an addon path for extras
        (route_to_extras) if several trailers are present. Or None
        """
        url = None
        number = 0
        for extras in self.item.iterfind('Extras'):
            for extra in extras:
                try:
                    typus = int(extra.attrib['extraType'])
                except (KeyError, TypeError):
                    typus = None
                if typus != 1:
                    continue
                number += 1
                url = extra.get('ratingKey')
        if number > 1:
            # Several trailers present. Hence let the user choose
            url = ('plugin://%s?mode=route_to_extras&plex_id=%s'
                   % (v.ADDON_ID, self.plex_id()))
        elif url:
            url = ('plugin://%s.movies/?plex_id=%s&plex_type=%s&mode=play'
                   % (v.ADDON_ID, url, v.PLEX_TYPE_CLIP))
        return url

    def mediastreams(self):
        """
        Returns the media streams for metadata purposes

        Output: each track contains a dictionaries
        {
            'video': videotrack-list,       'codec', 'height', 'width',
                                            'aspect', 'video3DFormat'
            'audio': audiotrack-list,       'codec', 'channels',
                                            'language'
            'subtitle': list of subtitle languages (or "Unknown")
        }
        """
        videotracks = []
        audiotracks = []
        subtitlelanguages = []
        try:
            # Sometimes, aspectratio is on the "toplevel"
            aspect = self.item[0].get('aspectRatio')
        except IndexError:
            # There is no stream info at all, returning empty
            return {
                'video': videotracks,
                'audio': audiotracks,
                'subtitle': subtitlelanguages
            }
        # Loop over parts
        for child in self.item[0]:
            container = child.get('container')
            # Loop over Streams
            for grandchild in child:
                stream = grandchild.attrib
                media_type = int(stream.get('streamType', 999))
                track = {}
                if media_type == 1:  # Video streams
                    if 'codec' in stream:
                        track['codec'] = stream['codec'].lower()
                        if "msmpeg4" in track['codec']:
                            track['codec'] = "divx"
                        elif "mpeg4" in track['codec']:
                            # if "simple profile" in profile or profile == "":
                            #    track['codec'] = "xvid"
                            pass
                        elif "h264" in track['codec']:
                            if container in ("mp4", "mov", "m4v"):
                                track['codec'] = "avc1"
                    track['height'] = stream.get('height')
                    track['width'] = stream.get('width')
                    # track['Video3DFormat'] = item.get('Video3DFormat')
                    track['aspect'] = stream.get('aspectRatio', aspect)
                    track['duration'] = self.resume_runtime()[1]
                    track['video3DFormat'] = None
                    videotracks.append(track)
                elif media_type == 2:  # Audio streams
                    if 'codec' in stream:
                        track['codec'] = stream['codec'].lower()
                        if ("dca" in track['codec'] and
                                "ma" in stream.get('profile', '').lower()):
                            track['codec'] = "dtshd_ma"
                    track['channels'] = stream.get('channels')
                    # 'unknown' if we cannot get language
                    track['language'] = stream.get(
                        'languageCode', utils.lang(39310)).lower()
                    audiotracks.append(track)
                elif media_type == 3:  # Subtitle streams
                    # 'unknown' if we cannot get language
                    subtitlelanguages.append(
                        stream.get('languageCode', utils.lang(39310)).lower())
        return {
            'video': videotracks,
            'audio': audiotracks,
            'subtitle': subtitlelanguages
        }

    def one_artwork(self, art_kind):
        artwork = self.item.get(art_kind)
        if artwork and not artwork.startswith('http'):
            if '/composite/' in artwork:
                try:
                    # e.g. Plex collections where artwork already contains
                    # width and height. Need to upscale for better resolution
                    artwork, args = artwork.split('?')
                    args = dict(parse_qsl(args))
                    width = int(args.get('width', 400))
                    height = int(args.get('height', 400))
                    # Adjust to 4k resolution 3,840x2,160
                    scaling = 3840.0 / float(max(width, height))
                    width = int(scaling * width)
                    height = int(scaling * height)
                except ValueError:
                    # e.g. playlists
                    width = 3840
                    height = 3840
                artwork = '%s?width=%s&height=%s' % (artwork, width, height)
            artwork = ('%s/photo/:/transcode?width=3840&height=3840&'
                       'minSize=1&upscale=0&url=%s'
                       % (self.server, quote(artwork)))
            artwork = self.attach_plex_token_to_url(artwork)
        return artwork

    def artwork(self, kodi_id=None, kodi_type=None, full_artwork=False):
        """
        Gets the URLs to the Plex artwork. Dict keys will be missing if there
        is no corresponding artwork.
        Pass kodi_id and kodi_type to grab the artwork saved in the Kodi DB
        (thus potentially more artwork, e.g. clearart, discart)

        Output ('max' version)
        {
            'thumb'
            'poster'
            'banner'
            'clearart'
            'clearlogo'
            'fanart'
        }
        'landscape' and 'icon' might be implemented later
        Passing full_artwork=True returns ALL the artwork for the item, so not
        just 'thumb' for episodes, but also season and show artwork
        """
        artworks = {}
        if self.plex_type() == v.PLEX_TYPE_EPISODE:
            # Artwork lookup for episodes is broken for addon paths
            # Episodes is a bit special, only get the thumb, because all
            # the other artwork will be saved under season and show
            # EXCEPT if you're constructing a listitem
            if not full_artwork:
                art = self.one_artwork('thumb')
                if art:
                    artworks['thumb'] = art
                return artworks
            for kodi_artwork, plex_artwork in \
                    v.KODI_TO_PLEX_ARTWORK_EPISODE.iteritems():
                art = self.one_artwork(plex_artwork)
                if art:
                    artworks[kodi_artwork] = art
            if not full_artwork:
                return artworks
            with plexdb.Get_Plex_DB() as plex_db:
                try:
                    season_id = plex_db.getItem_byId(self.plex_id())[3]
                except TypeError:
                    return artworks
            # Grab artwork from the season
            with kodidb.GetKodiDB('video') as kodi_db:
                season_art = kodi_db.get_art(season_id, v.KODI_TYPE_SEASON)
            for kodi_art in season_art:
                artworks['season.%s' % kodi_art] = season_art[kodi_art]
            # Get the show id
            with plexdb.Get_Plex_DB() as plex_db:
                try:
                    show_id = plex_db.getItem_byKodiId(season_id,
                                                       v.KODI_TYPE_SEASON)[1]
                except TypeError:
                    return artworks
            # Grab more artwork from the show
            with kodidb.GetKodiDB('video') as kodi_db:
                show_art = kodi_db.get_art(show_id, v.KODI_TYPE_SHOW)
            for kodi_art in show_art:
                artworks['tvshow.%s' % kodi_art] = show_art[kodi_art]
            return artworks

        if kodi_id:
            # in Kodi database, potentially with additional e.g. clearart
            if self.plex_type() in v.PLEX_VIDEOTYPES:
                with kodidb.GetKodiDB('video') as kodi_db:
                    return kodi_db.get_art(kodi_id, kodi_type)
            else:
                with kodidb.GetKodiDB('music') as kodi_db:
                    return kodi_db.get_art(kodi_id, kodi_type)

        # Grab artwork from Plex
        # if self.plex_type() == v.PLEX_TYPE_EPISODE:

        for kodi_artwork, plex_artwork in v.KODI_TO_PLEX_ARTWORK.iteritems():
            art = self.one_artwork(plex_artwork)
            if art:
                artworks[kodi_artwork] = art
        if self.plex_type() in (v.PLEX_TYPE_SONG, v.PLEX_TYPE_ALBUM):
            # Get parent item artwork if the main item is missing artwork
            if 'fanart' not in artworks:
                art = self.one_artwork('parentArt')
                if art:
                    artworks['fanart1'] = art
            if 'poster' not in artworks:
                art = self.one_artwork('parentThumb')
                if art:
                    artworks['poster'] = art
        if self.plex_type() in (v.PLEX_TYPE_SONG,
                                v.PLEX_TYPE_ALBUM,
                                v.PLEX_TYPE_ARTIST):
            # need to set poster also as thumb
            art = self.one_artwork('thumb')
            if art:
                artworks['thumb'] = art
        return artworks

    def fanart_artwork(self, artworks):
        """
        Downloads additional fanart from third party sources (well, link to
        fanart only).
        """
        external_id = self.retrieve_external_item_id()
        if external_id is not None:
            artworks = self.lookup_fanart_tv(external_id[0], artworks)
        return artworks

    def retrieve_external_item_id(self, collection=False):
        """
        Returns the set
            media_id [unicode]:     the item's IMDB id for movies or tvdb id for
                                    TV shows
            poster [unicode]:       path to the item's poster artwork
            background [unicode]:   path to the item's background artwork

        The last two might be None if not found. Generally None is returned
        if unsuccessful.

        If not found in item's Plex metadata, check themovidedb.org.
        """
        item = self.item.attrib
        media_type = item.get('type')
        media_id = None
        # Return the saved Plex id's, if applicable
        # Always seek collection's ids since not provided by PMS
        if collection is False:
            if media_type == v.PLEX_TYPE_MOVIE:
                media_id = self.provider('imdb')
            elif media_type == v.PLEX_TYPE_SHOW:
                media_id = self.provider('tvdb')
            if media_id is not None:
                return media_id, None, None
            LOG.info('Plex did not provide ID for IMDB or TVDB. Start '
                     'lookup process')
        else:
            LOG.info('Start movie set/collection lookup on themoviedb with %s',
                     item.get('title', ''))

        api_key = utils.settings('themoviedbAPIKey')
        if media_type == v.PLEX_TYPE_SHOW:
            media_type = 'tv'
        title = item.get('title', '')
        # if the title has the year in remove it as tmdb cannot deal with it...
        # replace e.g. 'The Americans (2015)' with 'The Americans'
        title = sub(r'\s*\(\d{4}\)$', '', title, count=1)
        url = 'https://api.themoviedb.org/3/search/%s' % media_type
        parameters = {
            'api_key': api_key,
            'language': v.KODILANGUAGE,
            'query': utils.try_encode(title)
        }
        data = DU().downloadUrl(url,
                                authenticate=False,
                                parameters=parameters,
                                timeout=7)
        try:
            data.get('test')
        except AttributeError:
            LOG.warning('Could not download data from FanartTV')
            return
        if not data.get('results'):
            LOG.info('No match found on themoviedb for type: %s, title: %s',
                     media_type, title)
            return

        year = item.get('year')
        match_found = None
        # find year match
        if year:
            for entry in data['results']:
                if year in entry.get('first_air_date', ''):
                    match_found = entry
                    break
                elif year in entry.get('release_date', ''):
                    match_found = entry
                    break
        # find exact match based on title, if we haven't found a year match
        if match_found is None:
            LOG.info('No themoviedb match found using year %s', year)
            replacements = (
                ' ',
                '-',
                '&',
                ',',
                ':',
                ';'
            )
            for entry in data['results']:
                name = entry.get('name', entry.get('title', ''))
                original_name = entry.get('original_name', '')
                title_alt = title.lower()
                name_alt = name.lower()
                org_name_alt = original_name.lower()
                for replace_string in replacements:
                    title_alt = title_alt.replace(replace_string, '')
                    name_alt = name_alt.replace(replace_string, '')
                    org_name_alt = org_name_alt.replace(replace_string, '')
                if name == title or original_name == title:
                    # match found for exact title name
                    match_found = entry
                    break
                elif (name.split(' (')[0] == title or title_alt == name_alt
                      or title_alt == org_name_alt):
                    # match found with substituting some stuff
                    match_found = entry
                    break

        # if a match was not found, we accept the closest match from TMDB
        if match_found is None and data.get('results'):
            LOG.info('Using very first match from themoviedb')
            match_found = entry = data.get('results')[0]

        if match_found is None:
            LOG.info('Still no themoviedb match for type: %s, title: %s, '
                     'year: %s', media_type, title, year)
            LOG.debug('themoviedb answer was %s', data['results'])
            return

        LOG.info('Found themoviedb match for %s: %s',
                 item.get('title'), match_found)

        tmdb_id = str(entry.get('id', ''))
        if tmdb_id == '':
            LOG.error('No themoviedb ID found, aborting')
            return

        if media_type == 'multi' and entry.get('media_type'):
            media_type = entry.get('media_type')
        name = entry.get('name', entry.get('title'))
        # lookup external tmdb_id and perform artwork lookup on fanart.tv
        parameters = {'api_key': api_key}
        if media_type == 'movie':
            url = 'https://api.themoviedb.org/3/movie/%s' % tmdb_id
            parameters['append_to_response'] = 'videos'
        elif media_type == 'tv':
            url = 'https://api.themoviedb.org/3/tv/%s' % tmdb_id
            parameters['append_to_response'] = 'external_ids,videos'
        media_id, poster, background = None, None, None
        for language in [v.KODILANGUAGE, 'en']:
            parameters['language'] = language
            data = DU().downloadUrl(url,
                                    authenticate=False,
                                    parameters=parameters,
                                    timeout=7)
            try:
                data.get('test')
            except AttributeError:
                LOG.warning('Could not download %s with parameters %s',
                            url, parameters)
                continue
            if collection is False:
                if data.get('imdb_id'):
                    media_id = str(data.get('imdb_id'))
                    break
                if (data.get('external_ids') and
                        data['external_ids'].get('tvdb_id')):
                    media_id = str(data['external_ids']['tvdb_id'])
                    break
            else:
                if not data.get('belongs_to_collection'):
                    continue
                media_id = data.get('belongs_to_collection').get('id')
                if not media_id:
                    continue
                media_id = str(media_id)
                LOG.debug('Retrieved collections tmdb id %s for %s',
                          media_id, title)
                url = 'https://api.themoviedb.org/3/collection/%s' % media_id
                data = DU().downloadUrl(url,
                                        authenticate=False,
                                        parameters=parameters,
                                        timeout=7)
                try:
                    data.get('poster_path')
                except AttributeError:
                    LOG.debug('Could not find TheMovieDB poster paths for %s'
                              ' in the language %s', title, language)
                    continue
                if not poster and data.get('poster_path'):
                    poster = ('https://image.tmdb.org/t/p/original%s' %
                              data.get('poster_path'))
                if not background and data.get('backdrop_path'):
                    background = ('https://image.tmdb.org/t/p/original%s' %
                                  data.get('backdrop_path'))
        return media_id, poster, background

    def lookup_fanart_tv(self, media_id, artworks):
        """
        perform artwork lookup on fanart.tv

        media_id: IMDB id for movies, tvdb id for TV shows
        """
        api_key = utils.settings('FanArtTVAPIKey')
        typus = self.plex_type()
        if typus == v.PLEX_TYPE_SHOW:
            typus = 'tv'

        if typus == v.PLEX_TYPE_MOVIE:
            url = 'http://webservice.fanart.tv/v3/movies/%s?api_key=%s' \
                % (media_id, api_key)
        elif typus == 'tv':
            url = 'http://webservice.fanart.tv/v3/tv/%s?api_key=%s' \
                % (media_id, api_key)
        else:
            # Not supported artwork
            return artworks
        data = DU().downloadUrl(url, authenticate=False, timeout=15)
        try:
            data.get('test')
        except AttributeError:
            LOG.error('Could not download data from FanartTV')
            return artworks

        fanart_tv_types = list(v.FANART_TV_TO_KODI_TYPE)

        if typus == v.PLEX_TYPE_ARTIST:
            fanart_tv_types.append(("thumb", "folder"))
        else:
            fanart_tv_types.append(("thumb", "thumb"))

        prefixes = (
            "hd" + typus,
            "hd",
            typus,
            "",
        )
        for fanart_tv_type, kodi_type in fanart_tv_types:
            # Skip the ones we already have
            if kodi_type in artworks:
                continue
            for prefix in prefixes:
                fanarttvimage = prefix + fanart_tv_type
                if fanarttvimage not in data:
                    continue
                # select image in preferred language
                for entry in data[fanarttvimage]:
                    if entry.get("lang") == v.KODILANGUAGE:
                        artworks[kodi_type] = \
                            entry.get("url", "").replace(' ', '%20')
                        break
                # just grab the first english OR undefinded one as fallback
                # (so we're actually grabbing the more popular one)
                if kodi_type not in artworks:
                    for entry in data[fanarttvimage]:
                        if entry.get("lang") in ("en", "00"):
                            artworks[kodi_type] = \
                                entry.get("url", "").replace(' ', '%20')
                            break

        # grab extrafanarts in list
        fanartcount = 1 if 'fanart' in artworks else ''
        for prefix in prefixes:
            fanarttvimage = prefix + 'background'
            if fanarttvimage not in data:
                continue
            for entry in data[fanarttvimage]:
                if entry.get("url") is None:
                    continue
                artworks['fanart%s' % fanartcount] = \
                    entry['url'].replace(' ', '%20')
                try:
                    fanartcount += 1
                except TypeError:
                    fanartcount = 1
                if fanartcount >= v.MAX_BACKGROUND_COUNT:
                    break
        return artworks

    def library_section_id(self):
        """
        Returns the id of the Plex library section (for e.g. a movies section)
        or None
        """
        return self.item.get('librarySectionID')

    def collections_match(self):
        """
        Downloads one additional xml from the PMS in order to return a list of
        tuples [(collection_id, plex_id), ...] for all collections of the
        current item's Plex library sectin
        Pass in the collection id of e.g. the movie's metadata
        """
        xml = PF.collections(self.library_section_id())
        if xml is None:
            return []
        return [(i.get('index'), i.get('ratingKey')) for i in xml]

    def set_artwork(self):
        """
        Gets the URLs to the Plex artwork, or empty string if not found.
        Only call on movies
        """
        artworks = {}
        # Plex does not get much artwork - go ahead and get the rest from
        # fanart tv only for movie or tv show
        external_id = self.retrieve_external_item_id(collection=True)
        if external_id is not None:
            external_id, poster, background = external_id
            if poster is not None:
                artworks['poster'] = poster
            if background is not None:
                artworks['fanart'] = background
            artworks = self.lookup_fanart_tv(external_id, artworks)
        else:
            LOG.info('Did not find a set/collection ID on TheMovieDB using %s.'
                     ' Artwork will be missing.', self.titles()[0])
        return artworks

    def should_stream(self):
        """
        Returns True if the item's 'optimizedForStreaming' is set, False other-
        wise
        """
        return self.item[0].get('optimizedForStreaming') == '1'

    def mediastream_number(self):
        """
        Returns the Media stream as an int (mostly 0). Will let the user choose
        if several media streams are present for a PMS item (if settings are
        set accordingly)
        """
        # How many streams do we have?
        count = 0
        for entry in self.item.iterfind('./Media'):
            count += 1
        if (count > 1 and (
                (self.plex_type() != v.PLEX_TYPE_CLIP and
                 utils.settings('bestQuality') == 'false')
            or
                (self.plex_type() == v.PLEX_TYPE_CLIP and
                 utils.settings('bestTrailer') == 'false'))):
            # Several streams/files available.
            dialoglist = []
            for entry in self.item.iterfind('./Media'):
                # Get additional info (filename / languages)
                if 'file' in entry[0].attrib:
                    option = utils.try_decode(entry[0].attrib['file'])
                    option = path_ops.path.basename(option)
                else:
                    option = self.title() or ''
                # Languages of audio streams
                languages = []
                for stream in entry[0]:
                    if (stream.attrib['streamType'] == '1' and
                            'language' in stream.attrib):
                        language = utils.try_decode(stream.attrib['language'])
                        languages.append(language)
                languages = ', '.join(languages)
                if languages:
                    if option:
                        option = '%s (%s): ' % (option, languages)
                    else:
                        option = '%s: ' % languages
                else:
                    option = '%s ' % option
                if 'videoResolution' in entry.attrib:
                    res = utils.try_decode(entry.attrib['videoResolution'])
                    option = '%s%sp ' % (option, res)
                if 'videoCodec' in entry.attrib:
                    codec = utils.try_decode(entry.attrib['videoCodec'])
                    option = '%s%s' % (option, codec)
                option = option.strip() + ' - '
                if 'audioProfile' in entry.attrib:
                    profile = utils.try_decode(entry.attrib['audioProfile'])
                    option = '%s%s ' % (option, profile)
                if 'audioCodec' in entry.attrib:
                    codec = utils.try_decode(entry.attrib['audioCodec'])
                    option = '%s%s ' % (option, codec)
                option = utils.try_encode(option.strip())
                dialoglist.append(option)
            media = utils.dialog('select', 'Select stream', dialoglist)
        else:
            media = 0
        self.mediastream = media
        return media

    def transcode_video_path(self, action, quality=None):
        """

        To be called on a VIDEO level of PMS xml response!

        Transcode Video support; returns the URL to get a media started

        Input:
            action      'DirectStream' or 'Transcode'

            quality:    {
                            'videoResolution': e.g. '1024x768',
                            'videoQuality': e.g. '60',
                            'maxVideoBitrate': e.g. '2000' (in kbits)
                        }
                        (one or several of these options)
        Output:
            final URL to pull in PMS transcoder

        TODO: mediaIndex
        """
        if self.mediastream is None:
            self.mediastream_number()
        if quality is None:
            quality = {}
        xargs = clientinfo.getXArgsDeviceInfo()
        # For DirectPlay, path/key of PART is needed
        # trailers are 'clip' with PMS xmls
        if action == "DirectStream":
            path = self.item[self.mediastream][self.part].attrib['key']
            url = self.server + path
            # e.g. Trailers already feature an '?'!
            if '?' in url:
                url += '&' + urlencode(xargs)
            else:
                url += '?' + urlencode(xargs)
            return url

        # For Transcoding
        headers = {
            'X-Plex-Platform': 'Android',
            'X-Plex-Platform-Version': '7.0',
            'X-Plex-Product': 'Plex for Android',
            'X-Plex-Version': '5.8.0.475'
        }
        # Path/key to VIDEO item of xml PMS response is needed, not part
        path = self.item.attrib['key']
        transcode_path = self.server + \
            '/video/:/transcode/universal/start.m3u8?'
        args = {
            'audioBoost': utils.settings('audioBoost'),
            'autoAdjustQuality': 0,
            'directPlay': 0,
            'directStream': 1,
            'protocol': 'hls',   # seen in the wild: 'dash', 'http', 'hls'
            'session': utils.window('plex_client_Id'),
            'fastSeek': 1,
            'path': path,
            'mediaIndex': self.mediastream,
            'partIndex': self.part,
            'hasMDE': 1,
            'location': 'lan',
            'subtitleSize': utils.settings('subtitleSize')
        }
        # Look like Android to let the PMS use the transcoding profile
        xargs.update(headers)
        LOG.debug("Setting transcode quality to: %s", quality)
        args.update(quality)
        url = transcode_path + urlencode(xargs) + '&' + urlencode(args)
        return url

    def cache_external_subs(self):
        """
        Downloads external subtitles temporarily to Kodi and returns a list
        of their paths
        """
        externalsubs = []
        try:
            mediastreams = self.item[0][self.part]
        except (TypeError, KeyError, IndexError):
            return
        kodiindex = 0
        fileindex = 0
        for stream in mediastreams:
            # Since plex returns all possible tracks together, have to pull
            # only external subtitles - only for these a 'key' exists
            if stream.get('streamType') != "3":
                # Not a subtitle
                continue
            # Only set for additional external subtitles NOT lying beside video
            key = stream.get('key')
            # Only set for dedicated subtitle files lying beside video
            # ext = stream.attrib.get('format')
            if key:
                # We do know the language - temporarily download
                if stream.get('languageCode') is not None:
                    path = self.download_external_subtitles(
                        "{server}%s" % key,
                        "subtitle%02d.%s.%s" % (fileindex,
                                                stream.attrib['languageCode'],
                                                stream.attrib['codec']))
                    fileindex += 1
                # We don't know the language - no need to download
                else:
                    path = self.attach_plex_token_to_url(
                        "%s%s" % (self.server, key))
                externalsubs.append(path)
                kodiindex += 1
        LOG.info('Found external subs: %s', externalsubs)
        return externalsubs

    @staticmethod
    def download_external_subtitles(url, filename):
        """
        One cannot pass the subtitle language for ListItems. Workaround; will
        download the subtitle at url to the Kodi PKC directory in a temp dir

        Returns the path to the downloaded subtitle or None
        """
        path = path_ops.path.join(v.EXTERNAL_SUBTITLE_TEMP_PATH, filename)
        response = DU().downloadUrl(url, return_response=True)
        try:
            response.status_code
        except AttributeError:
            LOG.error('Could not temporarily download subtitle %s', url)
            return
        else:
            LOG.debug('Writing temp subtitle to %s', path)
            with open(path_ops.encode_path(path), 'wb') as filer:
                filer.write(response.content)
            return path

    def kodi_premiere_date(self):
        """
        Takes Plex' originallyAvailableAt of the form "yyyy-mm-dd" and returns
        Kodi's "dd.mm.yyyy" or None
        """
        date = self.premiere_date()
        if date is None:
            return
        try:
            date = sub(r'(\d+)-(\d+)-(\d+)', r'\3.\2.\1', date)
        except:
            date = None
        return date

    def create_listitem(self, listitem=None, append_show_title=False,
                        append_sxxexx=False):
        """
        Return a xbmcgui.ListItem() for this Plex item
        """
        if self.plex_type() == v.PLEX_TYPE_PHOTO:
            listitem = self._create_photo_listitem(listitem)
            # Only set the bare minimum of artwork
            listitem.setArt({'icon': 'DefaultPicture.png',
                             'fanart': self.one_artwork('thumb')})
        elif self.plex_type() == v.PLEX_TYPE_SONG:
            listitem = self._create_audio_listitem(listitem)
            listitem.setArt(self.artwork())
        else:
            listitem = self._create_video_listitem(listitem,
                                                   append_show_title,
                                                   append_sxxexx)
            self.add_video_streams(listitem)
            listitem.setArt(self.artwork(full_artwork=True))
        return listitem

    def _create_photo_listitem(self, listitem=None):
        """
        Use for photo items only
        """
        title, _ = self.titles()
        if listitem is None:
            listitem = ListItem(title)
        else:
            listitem.setLabel(title)
        metadata = {
            'date': self.kodi_premiere_date(),
            'size': long(self.item[0][0].get('size', 0)),
            'exif:width': self.item[0].get('width', ''),
            'exif:height': self.item[0].get('height', ''),
        }
        listitem.setInfo(type='image', infoLabels=metadata)
        listitem.setProperty('plot', self.plot())
        listitem.setProperty('plexid', self.plex_id())
        return listitem

    def _create_video_listitem(self,
                               listitem=None,
                               append_show_title=False,
                               append_sxxexx=False):
        """
        Use for video items only
        Call on a child level of PMS xml response (e.g. in a for loop)

        listitem        : existing xbmcgui.ListItem to work with
                          otherwise, a new one is created
        append_show_title : True to append TV show title to episode title
        append_sxxexx    : True to append SxxExx to episode title

        Returns XBMC listitem for this PMS library item
        """
        title, sorttitle = self.titles()
        typus = self.plex_type()

        if listitem is None:
            listitem = ListItem(title)
        else:
            listitem.setLabel(title)
        # Necessary; Kodi won't start video otherwise!
        listitem.setProperty('IsPlayable', 'true')
        # Video items, e.g. movies and episodes or clips
        people = self.people()
        userdata = self.userdata()
        metadata = {
            'genre': self.genre_list(),
            'country': self.country_list(),
            'year': self.year(),
            'rating': self.audience_rating(),
            'playcount': userdata['PlayCount'],
            'cast': people['Cast'],
            'director': people['Director'],
            'plot': self.plot(),
            'sorttitle': sorttitle,
            'duration': userdata['Runtime'],
            'studio': self.music_studio_list(),
            'tagline': self.tagline(),
            'writer': people.get('Writer'),
            'premiered': self.premiere_date(),
            'dateadded': self.date_created(),
            'lastplayed': userdata['LastPlayedDate'],
            'mpaa': self.content_rating(),
            'aired': self.premiere_date(),
        }
        # Do NOT set resumetime - otherwise Kodi always resumes at that time
        # even if the user chose to start element from the beginning
        # listitem.setProperty('resumetime', str(userdata['Resume']))
        listitem.setProperty('totaltime', str(userdata['Runtime']))

        if typus == v.PLEX_TYPE_EPISODE:
            metadata['mediatype'] = 'episode'
            _, show, season, episode = self.episode_data()
            season = -1 if season is None else int(season)
            episode = -1 if episode is None else int(episode)
            metadata['episode'] = episode
            metadata['sortepisode'] = episode
            metadata['season'] = season
            metadata['sortseason'] = season
            metadata['tvshowtitle'] = show
            if season and episode:
                if append_sxxexx is True:
                    title = "S%.2dE%.2d - %s" % (season, episode, title)
            if append_show_title is True:
                title = "%s - %s " % (show, title)
            if append_show_title or append_sxxexx:
                listitem.setLabel(title)
        elif typus == v.PLEX_TYPE_MOVIE:
            metadata['mediatype'] = 'movie'
        else:
            # E.g. clips, trailers, ...
            pass

        plex_id = self.plex_id()
        listitem.setProperty('plexid', plex_id)
        with plexdb.Get_Plex_DB() as plex_db:
            kodi_id = plex_db.getItem_byId(plex_id)
            if kodi_id:
                kodi_id = kodi_id[0]
                metadata['dbid'] = kodi_id
        metadata['title'] = title
        # Expensive operation
        listitem.setInfo('video', infoLabels=metadata)
        try:
            # Add context menu entry for information screen
            listitem.addContextMenuItems([(utils.lang(30032),
                                           'XBMC.Action(Info)',)])
        except TypeError:
            # Kodi fuck-up
            pass
        return listitem

    def track_number(self):
        """
        Returns the song's track number as an int or None if not found
        """
        try:
            return int(self.item.get('index'))
        except TypeError:
            pass

    def disc_number(self):
        """
        Returns the song's disc number as an int or None if not found
        """
        try:
            return int(self.item.get('parentIndex'))
        except TypeError:
            pass

    def _create_audio_listitem(self, listitem=None):
        """
        Use for songs only
        Call on a child level of PMS xml response (e.g. in a for loop)

        listitem        : existing xbmcgui.ListItem to work with
                          otherwise, a new one is created

        Returns XBMC listitem for this PMS library item
        """
        if listitem is None:
            listitem = ListItem(self.title())
        else:
            listitem.setLabel(self.title())
        listitem.setProperty('IsPlayable', 'true')
        userdata = self.userdata()
        metadata = {
            'mediatype': 'song',
            'tracknumber': self.track_number(),
            'discnumber': self.track_number(),
            'duration': userdata['Runtime'],
            'year': self.year(),
            # Kodi does not support list of str
            'genre': ','.join(self.genre_list()) or None,
            'album': self.item.get('parentTitle'),
            'artist': self.item.get('originalTitle') or self.grandparent_title(),
            'title': self.title(),
            'rating': self.audience_rating(),
            'playcount': userdata['PlayCount'],
            'lastplayed': userdata['LastPlayedDate'],
            # lyrics  string (On a dark desert highway...)
            # userrating  integer - range is 1..10
            # comment string (This is a great song)
            # listeners   integer (25614)
            # musicbrainztrackid  string (cd1de9af-0b71-4503-9f96-9f5efe27923c)
            # musicbrainzartistid string (d87e52c5-bb8d-4da8-b941-9f4928627dc8)
            # musicbrainzalbumid  string (24944755-2f68-3778-974e-f572a9e30108)
            # musicbrainzalbumartistid string (d87e52c5-bb8d-4da8-b941-9f4928627dc8)
        }
        plex_id = self.plex_id()
        listitem.setProperty('plexid', plex_id)
        if v.KODIVERSION >= 18:
            with plexdb.Get_Plex_DB() as plex_db:
                kodi_id = plex_db.getItem_byId(plex_id)
                if kodi_id:
                    kodi_id = kodi_id[0]
                    metadata['dbid'] = kodi_id
        listitem.setInfo('music', infoLabels=metadata)
        return listitem

    def add_video_streams(self, listitem):
        """
        Add media stream information to xbmcgui.ListItem
        """
        for key, value in self.mediastreams().iteritems():
            if value:
                listitem.addStreamInfo(key, value)

    def validate_playurl(self, path, typus, force_check=False, folder=False,
                         omit_check=False):
        """
        Returns a valid path for Kodi, e.g. with '\' substituted to '\\' in
        Unicode. Returns None if this is not possible

            path       : Unicode
            typus      : Plex type from PMS xml
            force_check : Will always try to check validity of path
                         Will also skip confirmation dialog if path not found
            folder     : Set to True if path is a folder
            omit_check  : Will entirely omit validity check if True
        """
        if path is None:
            return
        typus = v.REMAP_TYPE_FROM_PLEXTYPE[typus]
        if state.REMAP_PATH is True:
            path = path.replace(getattr(state, 'remapSMB%sOrg' % typus),
                                getattr(state, 'remapSMB%sNew' % typus),
                                1)
            # There might be backslashes left over:
            path = path.replace('\\', '/')
        elif state.REPLACE_SMB_PATH is True:
            if path.startswith('\\\\'):
                path = 'smb:' + path.replace('\\', '/')
        if ((state.PATH_VERIFIED and force_check is False) or
                omit_check is True):
            return path

        # exist() needs a / or \ at the end to work for directories
        if folder is False:
            # files
            check = path_ops.exists(path)
        else:
            # directories
            if "\\" in path:
                if not path.endswith('\\'):
                    # Add the missing backslash
                    check = path_ops.exists(path + "\\")
                else:
                    check = path_ops.exists(path)
            else:
                if not path.endswith('/'):
                    check = path_ops.exists(path + "/")
                else:
                    check = path_ops.exists(path)
        if not check:
            if force_check is False:
                # Validate the path is correct with user intervention
                if self.ask_to_validate(path):
                    state.STOP_SYNC = True
                    path = None
                state.PATH_VERIFIED = True
            else:
                path = None
        elif force_check is False:
            # Only set the flag if we were not force-checking the path
            state.PATH_VERIFIED = True
        return path

    @staticmethod
    def ask_to_validate(url):
        """
        Displays a YESNO dialog box:
            Kodi can't locate file: <url>. Please verify the path.
            You may need to verify your network credentials in the
            add-on settings or use different Plex paths. Stop syncing?

        Returns True if sync should stop, else False
        """
        LOG.warn('Cannot access file: %s', url)
        # Kodi cannot locate the file #s. Please verify your PKC settings. Stop
        # syncing?
        resp = utils.dialog('yesno',
                            heading='{plex}',
                            line1=utils.lang(39031) % url)
        return resp

    @staticmethod
    def _set_listitem_artprop(listitem, arttype, path):
        if arttype in (
                'thumb', 'fanart_image', 'small_poster', 'tiny_poster',
                'medium_landscape', 'medium_poster', 'small_fanartimage',
                'medium_fanartimage', 'fanart_noindicators'):
            listitem.setProperty(arttype, path)
        else:
            listitem.setArt({arttype: path})
