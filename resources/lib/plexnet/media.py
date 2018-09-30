import plexobjects
import plexstream
import plexrequest
import util

METADATA_RELATED_TRAILER = 1
METADATA_RELATED_DELETED_SCENE = 2
METADATA_RELATED_INTERVIEW = 3
METADATA_RELATED_MUSIC_VIDEO = 4
METADATA_RELATED_BEHIND_THE_SCENES = 5
METADATA_RELATED_SCENE_OR_SAMPLE = 6
METADATA_RELATED_LIVE_MUSIC_VIDEO = 7
METADATA_RELATED_LYRIC_MUSIC_VIDEO = 8
METADATA_RELATED_CONCERT = 9
METADATA_RELATED_FEATURETTE = 10
METADATA_RELATED_SHORT = 11
METADATA_RELATED_OTHER = 12


class MediaItem(plexobjects.PlexObject):
    def getIdentifier(self):
        identifier = self.get('identifier') or None

        if identifier is None:
            identifier = self.container.identifier

        # HACK
        # PMS doesn't return an identifier for playlist items. If we haven't found
        # an identifier and the key looks like a library item, then we pretend like
        # the identifier was set.
        #
        if identifier is None:  # Modified from Roku code which had no check for None with iPhoto - is that right?
            if self.key.startswith('/library/metadata'):
                identifier = "com.plexapp.plugins.library"
            elif self.isIPhoto():
                identifier = "com.plexapp.plugins.iphoto"

        return identifier

    def getQualityType(self, server=None):
        if self.isOnlineItem():
            return util.QUALITY_ONLINE

        if not server:
            server = self.getServer()

        return util.QUALITY_LOCAL if server.isLocalConnection() else util.QUALITY_REMOTE

    def delete(self):
        if not self.ratingKey:
            return

        req = plexrequest.PlexRequest(self.server, '/library/metadata/{0}'.format(self.ratingKey), method='DELETE')
        req.getToStringWithTimeout(10)
        self.deleted = req.wasOK()
        return self.deleted

    def exists(self):
        if self.deleted:
            return False

        data = self.server.query('/library/metadata/{0}'.format(self.ratingKey))
        return data.attrib.get('size') != '0'
        # req = plexrequest.PlexRequest(self.server, '/library/metadata/{0}'.format(self.ratingKey), method='HEAD')
        # req.getToStringWithTimeout(10)
        # return not req.wasNotFound()

    def fixedDuration(self):
        duration = self.duration.asInt()
        if duration < 1000:
            duration *= 60000
        return duration


class Media(plexobjects.PlexObject):
    TYPE = 'Media'

    def __init__(self, data, initpath=None, server=None, video=None):
        plexobjects.PlexObject.__init__(self, data, initpath=initpath, server=server)
        self.video = video
        self.parts = [MediaPart(elem, initpath=self.initpath, server=self.server, media=self) for elem in data]

    def __repr__(self):
        title = self.video.title.replace(' ', '.')[0:20]
        return '<%s:%s>' % (self.__class__.__name__, title.encode('utf8'))


class MediaPart(plexobjects.PlexObject):
    TYPE = 'Part'

    def __init__(self, data, initpath=None, server=None, media=None):
        plexobjects.PlexObject.__init__(self, data, initpath=initpath, server=server)
        self.media = media
        self.streams = [MediaPartStream.parse(e, initpath=self.initpath, server=server, part=self) for e in data if e.tag == 'Stream']

    def __repr__(self):
        return '<%s:%s>' % (self.__class__.__name__, self.id)

    def selectedStream(self, stream_type):
        streams = filter(lambda x: stream_type == x.type, self.streams)
        selected = list(filter(lambda x: x.selected is True, streams))
        if len(selected) == 0:
            return None
        return selected[0]


class MediaPartStream(plexstream.PlexStream):
    TYPE = None
    STREAMTYPE = None

    def __init__(self, data, initpath=None, server=None, part=None):
        plexobjects.PlexObject.__init__(self, data, initpath, server)
        self.part = part

    @staticmethod
    def parse(data, initpath=None, server=None, part=None):
        STREAMCLS = {
            1: VideoStream,
            2: AudioStream,
            3: SubtitleStream
        }
        stype = int(data.attrib.get('streamType'))
        cls = STREAMCLS.get(stype, MediaPartStream)
        return cls(data, initpath=initpath, server=server, part=part)

    def __repr__(self):
        return '<%s:%s>' % (self.__class__.__name__, self.id)


class VideoStream(MediaPartStream):
    TYPE = 'videostream'
    STREAMTYPE = plexstream.PlexStream.TYPE_VIDEO


class AudioStream(MediaPartStream):
    TYPE = 'audiostream'
    STREAMTYPE = plexstream.PlexStream.TYPE_AUDIO


class SubtitleStream(MediaPartStream):
    TYPE = 'subtitlestream'
    STREAMTYPE = plexstream.PlexStream.TYPE_SUBTITLE


class TranscodeSession(plexobjects.PlexObject):
    TYPE = 'TranscodeSession'


class MediaTag(plexobjects.PlexObject):
    TYPE = None
    ID = 'None'

    def __repr__(self):
        tag = self.tag.replace(' ', '.')[0:20]
        return '<%s:%s:%s>' % (self.__class__.__name__, self.id, tag)

    def __eq__(self, other):
        if other.__class__ != self.__class__:
            return False

        return self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)


class Collection(MediaTag):
    TYPE = 'Collection'
    FILTER = 'collection'


class Country(MediaTag):
    TYPE = 'Country'
    FILTER = 'country'


class Director(MediaTag):
    TYPE = 'Director'
    FILTER = 'director'
    ID = '4'


class Genre(MediaTag):
    TYPE = 'Genre'
    FILTER = 'genre'
    ID = '1'


class Mood(MediaTag):
    TYPE = 'Mood'
    FILTER = 'mood'


class Producer(MediaTag):
    TYPE = 'Producer'
    FILTER = 'producer'


class Role(MediaTag):
    TYPE = 'Role'
    FILTER = 'actor'
    ID = '6'

    def sectionRoles(self):
        hubs = self.server.hubs(count=10, search_query=self.tag)
        for hub in hubs:
            if hub.type == 'actor':
                break
        else:
            return None

        roles = []

        for actor in hub.items:
            if actor.id == self.id:
                roles.append(actor)

        return roles or None


class Similar(MediaTag):
    TYPE = 'Similar'
    FILTER = 'similar'


class Writer(MediaTag):
    TYPE = 'Writer'
    FILTER = 'writer'
