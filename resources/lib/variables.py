# -*- coding: utf-8 -*-
import xbmc
from xbmcaddon import Addon

# Paths are in string, not unicode!


def tryDecode(string, encoding='utf-8'):
    """
    Will try to decode string (encoded) using encoding. This possibly
    fails with e.g. Android TV's Python, which does not accept arguments for
    string.encode()
    """
    if isinstance(string, unicode):
        # already decoded
        return string
    try:
        string = string.decode(encoding, "ignore")
    except TypeError:
        string = string.decode()
    return string


_ADDON = Addon()
ADDON_NAME = 'PlexKodiConnect'
ADDON_ID = 'plugin.video.plexkodiconnect'
ADDON_VERSION = _ADDON.getAddonInfo('version')

KODILANGUAGE = xbmc.getLanguage(xbmc.ISO_639_1)
KODIVERSION = int(xbmc.getInfoLabel("System.BuildVersion")[:2])
KODILONGVERSION = xbmc.getInfoLabel('System.BuildVersion')
KODI_PROFILE = xbmc.translatePath("special://profile")

if xbmc.getCondVisibility('system.platform.osx'):
    PLATFORM = "MacOSX"
elif xbmc.getCondVisibility('system.platform.atv2'):
    PLATFORM = "AppleTV2"
elif xbmc.getCondVisibility('system.platform.ios'):
    PLATFORM = "iOS"
elif xbmc.getCondVisibility('system.platform.windows'):
    PLATFORM = "Windows"
elif xbmc.getCondVisibility('system.platform.raspberrypi'):
    PLATFORM = "RaspberryPi"
elif xbmc.getCondVisibility('system.platform.linux'):
    PLATFORM = "Linux"
elif xbmc.getCondVisibility('system.platform.android'):
    PLATFORM = "Android"
else:
    PLATFORM = "Unknown"

DEVICENAME = tryDecode(_ADDON.getSetting('deviceName'))
DEVICENAME = DEVICENAME.replace(":", "")
DEVICENAME = DEVICENAME.replace("/", "-")
DEVICENAME = DEVICENAME.replace("\\", "-")
DEVICENAME = DEVICENAME.replace("<", "")
DEVICENAME = DEVICENAME.replace(">", "")
DEVICENAME = DEVICENAME.replace("*", "")
DEVICENAME = DEVICENAME.replace("?", "")
DEVICENAME = DEVICENAME.replace('|', "")
DEVICENAME = DEVICENAME.replace('(', "")
DEVICENAME = DEVICENAME.replace(')', "")
DEVICENAME = DEVICENAME.strip()

# Database paths
_DB_VIDEO_VERSION = {
    13: 78,   # Gotham
    14: 90,   # Helix
    15: 93,   # Isengard
    16: 99,   # Jarvis
    17: 107,  # Krypton
    18: 108   # Leia
}
DB_VIDEO_PATH = xbmc.translatePath(
    "special://database/MyVideos%s.db" % _DB_VIDEO_VERSION[KODIVERSION])

_DB_MUSIC_VERSION = {
    13: 46,   # Gotham
    14: 48,   # Helix
    15: 52,   # Isengard
    16: 56,   # Jarvis
    17: 60,   # Krypton
    18: 62    # Leia
}
DB_MUSIC_PATH = xbmc.translatePath(
    "special://database/MyMusic%s.db" % _DB_MUSIC_VERSION[KODIVERSION])

_DB_TEXTURE_VERSION = {
    13: 13,   # Gotham
    14: 13,   # Helix
    15: 13,   # Isengard
    16: 13,   # Jarvis
    17: 13,   # Krypton
    18: 13    # Leia
}
DB_TEXTURE_PATH = xbmc.translatePath(
    "special://database/Textures%s.db" % _DB_TEXTURE_VERSION[KODIVERSION])

DB_PLEX_PATH = xbmc.translatePath("special://database/plex.db")

EXTERNAL_SUBTITLE_TEMP_PATH = xbmc.translatePath(
    "special://profile/addon_data/%s/temp/" % ADDON_ID)


# Multiply Plex time by this factor to receive Kodi time
PLEX_TO_KODI_TIMEFACTOR = 1.0 / 1000.0


# All the Plex types as communicated in the PMS xml replies
PLEX_TYPE_VIDEO = 'video'
PLEX_TYPE_MOVIE = 'movie'
PLEX_TYPE_CLIP = 'clip'  # e.g. trailers

PLEX_TYPE_EPISODE = 'episode'
PLEX_TYPE_SEASON = 'season'
PLEX_TYPE_SHOW = 'show'

PLEX_TYPE_AUDIO = 'music'
PLEX_TYPE_SONG = 'track'
PLEX_TYPE_ALBUM = 'album'
PLEX_TYPE_ARTIST = 'artist'
PLEX_TYPE_MUSICVIDEO = 'musicvideo'

PLEX_TYPE_PHOTO = 'photo'


# All the Kodi types as e.g. used in the JSON API
KODI_TYPE_VIDEO = 'video'
KODI_TYPE_MOVIE = 'movie'
KODI_TYPE_SET = 'set'  # for movie sets of several movies
KODI_TYPE_CLIP = 'clip'  # e.g. trailers

KODI_TYPE_EPISODE = 'episode'
KODI_TYPE_SEASON = 'season'
KODI_TYPE_SHOW = 'tvshow'

KODI_TYPE_AUDIO = 'audio'
KODI_TYPE_SONG = 'song'
KODI_TYPE_ALBUM = 'album'
KODI_TYPE_ARTIST = 'artist'
KODI_TYPE_MUSICVIDEO = 'musicvideo'

KODI_TYPE_PHOTO = 'photo'


# Translation tables

KODI_VIDEOTYPES = (
    KODI_TYPE_VIDEO,
    KODI_TYPE_MOVIE,
    KODI_TYPE_SHOW,
    KODI_TYPE_SEASON,
    KODI_TYPE_EPISODE,
    KODI_TYPE_SET
)

KODI_AUDIOTYPES = (
    KODI_TYPE_SONG,
    KODI_TYPE_ALBUM,
    KODI_TYPE_ARTIST,
)

ITEMTYPE_FROM_PLEXTYPE = {
    PLEX_TYPE_MOVIE: 'Movies',
    PLEX_TYPE_SEASON: 'TVShows',
    KODI_TYPE_EPISODE: 'TVShows',
    PLEX_TYPE_SHOW: 'TVShows',
    PLEX_TYPE_ARTIST: 'Music',
    PLEX_TYPE_ALBUM: 'Music',
    PLEX_TYPE_SONG: 'Music',
}

ITEMTYPE_FROM_KODITYPE = {
    KODI_TYPE_MOVIE: 'Movies',
    KODI_TYPE_SEASON: 'TVShows',
    KODI_TYPE_EPISODE: 'TVShows',
    KODI_TYPE_SHOW: 'TVShows',
    KODI_TYPE_ARTIST: 'Music',
    KODI_TYPE_ALBUM: 'Music',
    KODI_TYPE_SONG: 'Music',
}

KODITYPE_FROM_PLEXTYPE = {
    PLEX_TYPE_MOVIE: KODI_TYPE_MOVIE,
    PLEX_TYPE_EPISODE: KODI_TYPE_EPISODE,
    PLEX_TYPE_SEASON: KODI_TYPE_SEASON,
    PLEX_TYPE_SHOW: KODI_TYPE_SHOW,
    PLEX_TYPE_SONG: KODI_TYPE_SONG,
    PLEX_TYPE_ARTIST: KODI_TYPE_ARTIST,
    PLEX_TYPE_ALBUM: KODI_TYPE_ALBUM,
    PLEX_TYPE_PHOTO: KODI_TYPE_PHOTO,
    'XXXXXX': 'musicvideo',
    'XXXXXXX': 'genre'
}

KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE = {
    PLEX_TYPE_VIDEO: KODI_TYPE_VIDEO,
    PLEX_TYPE_MOVIE: KODI_TYPE_VIDEO,
    PLEX_TYPE_EPISODE: KODI_TYPE_VIDEO,
    PLEX_TYPE_SEASON: KODI_TYPE_VIDEO,
    PLEX_TYPE_SHOW: KODI_TYPE_VIDEO,
    PLEX_TYPE_CLIP: KODI_TYPE_VIDEO,
    PLEX_TYPE_ARTIST: KODI_TYPE_AUDIO,
    PLEX_TYPE_ALBUM: KODI_TYPE_AUDIO,
    PLEX_TYPE_SONG: KODI_TYPE_AUDIO,
    PLEX_TYPE_AUDIO: KODI_TYPE_AUDIO,
    PLEX_TYPE_PHOTO: KODI_TYPE_PHOTO
}


REMAP_TYPE_FROM_PLEXTYPE = {
    PLEX_TYPE_MOVIE: 'movie',
    PLEX_TYPE_CLIP: 'clip',
    PLEX_TYPE_SHOW: 'tv',
    PLEX_TYPE_SEASON: 'tv',
    PLEX_TYPE_EPISODE: 'tv',
    PLEX_TYPE_ARTIST: 'music',
    PLEX_TYPE_ALBUM: 'music',
    PLEX_TYPE_SONG: 'music',
    PLEX_TYPE_PHOTO: 'photo'
}


REMAP_TYPE_FROM_PLEXTYPE = {
    'movie': 'movie',
    'show': 'tv',
    'season': 'tv',
    'episode': 'tv',
    'artist': 'music',
    'album': 'music',
    'song': 'music',
    'track': 'music',
    'clip': 'clip',
    'photo': 'photo'
}


PLEX_TYPE_FROM_WEBSOCKET = {
    1: PLEX_TYPE_MOVIE,
    2: PLEX_TYPE_SHOW,
    3: PLEX_TYPE_SEASON,
    4: PLEX_TYPE_EPISODE,
    8: PLEX_TYPE_ARTIST,
    9: PLEX_TYPE_ALBUM,
    10: PLEX_TYPE_SONG,
    12: PLEX_TYPE_CLIP
}


# extensions from:
# http://kodi.wiki/view/Features_and_supported_codecs#Format_support (RAW image
# formats, BMP, JPEG, GIF, PNG, TIFF, MNG, ICO, PCX and Targa/TGA)
KODI_SUPPORTED_IMAGES = (
    '.bmp',
    '.jpg',
    '.jpeg',
    '.gif',
    '.png',
    '.tiff',
    '.mng',
    '.ico',
    '.pcx',
    '.tga'
)


# Translation table from Alexa websocket commands to Plex Companion
ALEXA_TO_COMPANION = {
    'queryKey': 'key',
    'queryOffset': 'offset',
    'queryMachineIdentifier': 'machineIdentifier',
    'queryProtocol': 'protocol',
    'queryAddress': 'address',
    'queryPort': 'port',
    'queryContainerKey': 'containerKey',
    'queryToken': 'token',
}

# Kodi sort methods for xbmcplugin.addSortMethod()
SORT_METHODS_DIRECTORY = (
    'SORT_METHOD_UNSORTED',  # sorted as returned from Plex
    'SORT_METHOD_LABEL',
)

SORT_METHODS_PHOTOS = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_LABEL',
    'SORT_METHOD_DATE',
    'SORT_METHOD_DATEADDED',
)

SORT_METHODS_CLIPS = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_DURATION',
)

SORT_METHODS_MOVIES = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_DATEADDED',
    'SORT_METHOD_GENRE',
    'SORT_METHOD_VIDEO_RATING',
    'SORT_METHOD_VIDEO_USER_RATING',
    'SORT_METHOD_MPAA_RATING',
    'SORT_METHOD_DURATION',
    'SORT_METHOD_COUNTRY',
    'SORT_METHOD_STUDIO',
)

SORT_METHOD_TVSHOWS = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_DATEADDED',
    'SORT_METHOD_VIDEO_RATING',
    'SORT_METHOD_VIDEO_USER_RATING',
    'SORT_METHOD_MPAA_RATING',
    'SORT_METHOD_COUNTRY',
    'SORT_METHOD_GENRE',
)

SORT_METHODS_EPISODES = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_EPISODE',
    'SORT_METHOD_DATEADDED',
    'SORT_METHOD_VIDEO_RATING',
    'SORT_METHOD_VIDEO_USER_RATING',
    'SORT_METHOD_MPAA_RATING',
    'SORT_METHOD_DURATION',
    'SORT_METHOD_FILE',
    'SORT_METHOD_FULLPATH',
)

SORT_METHODS_SONGS = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_TRACKNUM',
    'SORT_METHOD_DURATION',
    'SORT_METHOD_ARTIST',
    'SORT_METHOD_ALBUM',
    'SORT_METHOD_SONG_RATING',
    'SORT_METHOD_SONG_USER_RATING'
)

SORT_METHODS_ARTISTS = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_TRACKNUM',
    'SORT_METHOD_DURATION',
    'SORT_METHOD_ARTIST',
    'SORT_METHOD_ALBUM',
)

SORT_METHODS_ALBUMS = (
    'SORT_METHOD_UNSORTED',
    'SORT_METHOD_TITLE',
    'SORT_METHOD_TRACKNUM',
    'SORT_METHOD_DURATION',
    'SORT_METHOD_ARTIST',
    'SORT_METHOD_ALBUM',
)
