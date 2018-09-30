import plexobjects
import media
import plexmedia
import plexstream
import exceptions
import compat
import plexlibrary
import util


class PlexVideoItemList(plexobjects.PlexItemList):
    def __init__(self, data, initpath=None, server=None, container=None):
        self._data = data
        self._initpath = initpath
        self._server = server
        self._container = container
        self._items = None

    @property
    def items(self):
        if self._items is None:
            if self._data is not None:
                self._items = [plexobjects.buildItem(self._server, elem, self._initpath, container=self._container) for elem in self._data]
            else:
                self._items = []

        return self._items


class Video(media.MediaItem):
    TYPE = None

    def __init__(self, *args, **kwargs):
        self._settings = None
        media.MediaItem.__init__(self, *args, **kwargs)

    def __eq__(self, other):
        return other and self.ratingKey == other.ratingKey

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def settings(self):
        if not self._settings:
            import plexapp
            self._settings = plexapp.PlayerSettingsInterface()

        return self._settings

    @settings.setter
    def settings(self, value):
        self._settings = value

    def selectedAudioStream(self):
        if self.audioStreams:
            for stream in self.audioStreams:
                if stream.isSelected():
                    return stream
        return None

    def selectedSubtitleStream(self):
        if self.subtitleStreams:
            for stream in self.subtitleStreams:
                if stream.isSelected():
                    return stream
        return None

    def selectStream(self, stream, async=True):
        self.mediaChoice.part.setSelectedStream(stream.streamType.asInt(), stream.id, async)

    def isVideoItem(self):
        return True

    def _findStreams(self, streamtype):
        idx = 0
        streams = []
        for media_ in self.media():
            for part in media_.parts:
                for stream in part.streams:
                    if stream.streamType.asInt() == streamtype:
                        stream.typeIndex = idx
                        streams.append(stream)
                        idx += 1
        return streams

    def analyze(self):
        """ The primary purpose of media analysis is to gather information about that media
            item. All of the media you add to a Library has properties that are useful to
            know - whether it's a video file, a music track, or one of your photos.
        """
        self.server.query('/%s/analyze' % self.key)

    def markWatched(self):
        path = '/:/scrobble?key=%s&identifier=com.plexapp.plugins.library' % self.ratingKey
        self.server.query(path)
        self.reload()

    def markUnwatched(self):
        path = '/:/unscrobble?key=%s&identifier=com.plexapp.plugins.library' % self.ratingKey
        self.server.query(path)
        self.reload()

    # def play(self, client):
    #     client.playMedia(self)

    def refresh(self):
        self.server.query('%s/refresh' % self.key, method=self.server.session.put)

    def _getStreamURL(self, **params):
        if self.TYPE not in ('movie', 'episode', 'track'):
            raise exceptions.Unsupported('Fetching stream URL for %s is unsupported.' % self.TYPE)
        mvb = params.get('maxVideoBitrate')
        vr = params.get('videoResolution')

        # import plexapp

        params = {
            'path': self.key,
            'offset': params.get('offset', 0),
            'copyts': params.get('copyts', 1),
            'protocol': params.get('protocol', 'hls'),
            'mediaIndex': params.get('mediaIndex', 0),
            'directStream': '1',
            'directPlay': '0',
            'X-Plex-Platform': params.get('platform', 'Chrome'),
            # 'X-Plex-Platform': params.get('platform', plexapp.INTERFACE.getGlobal('platform')),
            'maxVideoBitrate': max(mvb, 64) if mvb else None,
            'videoResolution': '{0}x{1}'.format(*vr) if vr else None
        }

        final = {}

        for k, v in params.items():
            if v is not None:  # remove None values
                final[k] = v

        streamtype = 'audio' if self.TYPE in ('track', 'album') else 'video'
        server = self.getTranscodeServer(True, self.TYPE)

        return server.buildUrl('/{0}/:/transcode/universal/start.m3u8?{1}'.format(streamtype, compat.urlencode(final)), includeToken=True)
        # path = "/video/:/transcode/universal/" + command + "?session=" + AppSettings().GetGlobal("clientIdentifier")

    def resolutionString(self):
        res = self.media[0].videoResolution
        if not res:
            return ''

        if res.isdigit():
            return '{0}p'.format(self.media[0].videoResolution)
        else:
            return res.upper()

    def audioCodecString(self):
        codec = (self.media[0].audioCodec or '').lower()

        if codec in ('dca', 'dca-ma', 'dts-hd', 'dts-es', 'dts-hra'):
            codec = "DTS"
        else:
            codec = codec.upper()

        return codec

    def audioChannelsString(self, translate_func=util.dummyTranslate):
        channels = self.media[0].audioChannels.asInt()

        if channels == 1:
            return translate_func("Mono")
        elif channels == 2:
            return translate_func("Stereo")
        elif channels > 0:
            return "{0}.1".format(channels - 1)
        else:
            return ""

    def available(self):
        return self.media()[0].isAccessible()


class PlayableVideo(Video):
    TYPE = None

    def _setData(self, data):
        Video._setData(self, data)
        if self.isFullObject():
            self.extras = PlexVideoItemList(data.find('Extras'), initpath=self.initpath, server=self.server, container=self)

    def reload(self, *args, **kwargs):
        if not kwargs.get('_soft'):
            if self.get('viewCount'):
                del self.viewCount
            if self.get('viewOffset'):
                del self.viewOffset
        Video.reload(self, *args, **kwargs)
        return self

    def postPlay(self, **params):
        query = '/hubs/metadata/{0}/postplay'.format(self.ratingKey)
        data = self.server.query(query, params=params)
        container = plexobjects.PlexContainer(data, initpath=query, server=self.server, address=query)

        hubs = {}
        for elem in data:
            hub = plexlibrary.Hub(elem, server=self.server, container=container)
            hubs[hub.hubIdentifier] = hub
        return hubs


@plexobjects.registerLibType
class Movie(PlayableVideo):
    TYPE = 'movie'

    def _setData(self, data):
        PlayableVideo._setData(self, data)
        if self.isFullObject():
            self.collections = plexobjects.PlexItemList(data, media.Collection, media.Collection.TYPE, server=self.server)
            self.countries = plexobjects.PlexItemList(data, media.Country, media.Country.TYPE, server=self.server)
            self.directors = plexobjects.PlexItemList(data, media.Director, media.Director.TYPE, server=self.server)
            self.genres = plexobjects.PlexItemList(data, media.Genre, media.Genre.TYPE, server=self.server)
            self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)
            self.producers = plexobjects.PlexItemList(data, media.Producer, media.Producer.TYPE, server=self.server)
            self.roles = plexobjects.PlexItemList(data, media.Role, media.Role.TYPE, server=self.server, container=self.container)
            self.writers = plexobjects.PlexItemList(data, media.Writer, media.Writer.TYPE, server=self.server)
            self.related = plexobjects.PlexItemList(data.find('Related'), plexlibrary.Hub, plexlibrary.Hub.TYPE, server=self.server, container=self)
        else:
            if data.find(media.Media.TYPE) is not None:
                self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)

        self._videoStreams = None
        self._audioStreams = None
        self._subtitleStreams = None

        # data for active sessions
        self.sessionKey = plexobjects.PlexValue(data.attrib.get('sessionKey', ''), self)
        self.user = self._findUser(data)
        self.player = self._findPlayer(data)
        self.transcodeSession = self._findTranscodeSession(data)

    @property
    def maxHeight(self):
        height = 0
        for m in self.media:
            if m.height.asInt() > height:
                height = m.height.asInt()
        return height

    @property
    def videoStreams(self):
        if self._videoStreams is None:
            self._videoStreams = self._findStreams(plexstream.PlexStream.TYPE_VIDEO)
        return self._videoStreams

    @property
    def audioStreams(self):
        if self._audioStreams is None:
            self._audioStreams = self._findStreams(plexstream.PlexStream.TYPE_AUDIO)
        return self._audioStreams

    @property
    def subtitleStreams(self):
        if self._subtitleStreams is None:
            self._subtitleStreams = self._findStreams(plexstream.PlexStream.TYPE_SUBTITLE)
        return self._subtitleStreams

    @property
    def actors(self):
        return self.roles

    @property
    def isWatched(self):
        return self.get('viewCount').asInt() > 0

    def getStreamURL(self, **params):
        return self._getStreamURL(**params)


@plexobjects.registerLibType
class Show(Video):
    TYPE = 'show'

    def _setData(self, data):
        Video._setData(self, data)
        if self.isFullObject():
            self.genres = plexobjects.PlexItemList(data, media.Genre, media.Genre.TYPE, server=self.server)
            self.roles = plexobjects.PlexItemList(data, media.Role, media.Role.TYPE, server=self.server, container=self.container)
            self.related = plexobjects.PlexItemList(data.find('Related'), plexlibrary.Hub, plexlibrary.Hub.TYPE, server=self.server, container=self)
            self.extras = PlexVideoItemList(data.find('Extras'), initpath=self.initpath, server=self.server, container=self)

    @property
    def unViewedLeafCount(self):
        return self.leafCount.asInt() - self.viewedLeafCount.asInt()

    @property
    def isWatched(self):
        return self.viewedLeafCount == self.leafCount

    def seasons(self):
        path = self.key
        return plexobjects.listItems(self.server, path, Season.TYPE)

    def season(self, title):
        path = self.key
        return plexobjects.findItem(self.server, path, title)

    def episodes(self, watched=None):
        leavesKey = '/library/metadata/%s/allLeaves' % self.ratingKey
        return plexobjects.listItems(self.server, leavesKey, watched=watched)

    def episode(self, title):
        path = '/library/metadata/%s/allLeaves' % self.ratingKey
        return plexobjects.findItem(self.server, path, title)

    def all(self):
        return self.episodes()

    def watched(self):
        return self.episodes(watched=True)

    def unwatched(self):
        return self.episodes(watched=False)

    def refresh(self):
        self.server.query('/library/metadata/%s/refresh' % self.ratingKey)

    def sectionOnDeck(self):
        query = '/library/sections/{0}/onDeck'.format(self.getLibrarySectionId())
        return plexobjects.listItems(self.server, query)


@plexobjects.registerLibType
class Season(Video):
    TYPE = 'season'

    def _setData(self, data):
        Video._setData(self, data)
        if self.isFullObject():
            self.extras = PlexVideoItemList(data.find('Extras'), initpath=self.initpath, server=self.server, container=self)

    @property
    def defaultTitle(self):
        return self.parentTitle or self.title

    @property
    def unViewedLeafCount(self):
        return self.leafCount.asInt() - self.viewedLeafCount.asInt()

    @property
    def isWatched(self):
        return self.viewedLeafCount == self.leafCount

    def episodes(self, watched=None):
        path = self.key
        return plexobjects.listItems(self.server, path, watched=watched)

    def episode(self, title):
        path = self.key
        return plexobjects.findItem(self.server, path, title)

    def all(self):
        return self.episodes()

    def show(self):
        return plexobjects.listItems(self.server, self.parentKey)[0]

    def watched(self):
        return self.episodes(watched=True)

    def unwatched(self):
        return self.episodes(watched=False)


@plexobjects.registerLibType
class Episode(PlayableVideo):
    TYPE = 'episode'

    def init(self, data):
        self._show = None
        self._season = None

    def _setData(self, data):
        PlayableVideo._setData(self, data)
        if self.isFullObject():
            self.directors = plexobjects.PlexItemList(data, media.Director, media.Director.TYPE, server=self.server)
            self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)
            self.writers = plexobjects.PlexItemList(data, media.Writer, media.Writer.TYPE, server=self.server)
        else:
            if data.find(media.Media.TYPE) is not None:
                self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)

        self._videoStreams = None
        self._audioStreams = None
        self._subtitleStreams = None

        # data for active sessions
        self.sessionKey = plexobjects.PlexValue(data.attrib.get('sessionKey', ''), self)
        self.user = self._findUser(data)
        self.player = self._findPlayer(data)
        self.transcodeSession = self._findTranscodeSession(data)

    @property
    def defaultTitle(self):
        return self.grandparentTitle or self.parentTitle or self.title

    @property
    def defaultThumb(self):
        return self.grandparentThumb or self.parentThumb or self.thumb

    @property
    def videoStreams(self):
        if self._videoStreams is None:
            self._videoStreams = self._findStreams(plexstream.PlexStream.TYPE_VIDEO)
        return self._videoStreams

    @property
    def audioStreams(self):
        if self._audioStreams is None:
            self._audioStreams = self._findStreams(plexstream.PlexStream.TYPE_AUDIO)
        return self._audioStreams

    @property
    def subtitleStreams(self):
        if self._subtitleStreams is None:
            self._subtitleStreams = self._findStreams(plexstream.PlexStream.TYPE_SUBTITLE)
        return self._subtitleStreams

    @property
    def isWatched(self):
        return self.get('viewCount').asInt() > 0

    def getStreamURL(self, **params):
        return self._getStreamURL(**params)

    def season(self):
        if not self._season:
            self._season = plexobjects.listItems(self.server, self.parentKey)[0]
        return self._season

    def show(self):
        if not self._show:
            self._show = plexobjects.listItems(self.server, self.grandparentKey)[0]
        return self._show

    @property
    def genres(self):
        return self.show().genres

    @property
    def roles(self):
        return self.show().roles

    @property
    def related(self):
        self.show().reload(_soft=True, includeRelated=1, includeRelatedCount=10)
        return self.show().related


@plexobjects.registerLibType
class Clip(PlayableVideo):
    TYPE = 'clip'

    def _setData(self, data):
        PlayableVideo._setData(self, data)
        if self.isFullObject():
            self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)
        else:
            if data.find(media.Media.TYPE) is not None:
                self.media = plexobjects.PlexMediaItemList(data, plexmedia.PlexMedia, media.Media.TYPE, initpath=self.initpath, server=self.server, media=self)

    @property
    def isWatched(self):
        return self.get('viewCount').asInt() > 0

    def getStreamURL(self, **params):
        return self._getStreamURL(**params)
