import plexstream
import util


class MediaChoice(object):
    SUBTITLES_DEFAULT = 0
    SUBTITLES_BURN = 1
    SUBTITLES_SOFT_DP = 2
    SUBTITLES_SOFT_ANY = 3

    def __init__(self, media=None, partIndex=0):
        self.media = media
        self.part = None
        self.forceTranscode = False
        self.isDirectPlayable = False
        self.videoStream = None
        self.audioStream = None
        self.subtitleStream = None
        self.isSelected = False
        self.subtitleDecision = self.SUBTITLES_DEFAULT

        self.sorts = util.AttributeDict()

        if media:
            self.indirectHeaders = media.indirectHeaders
            self.part = media.parts[partIndex]
            if self.part:
                # We generally just rely on PMS to have told us selected streams, so
                # initialize our streams accordingly.

                self.videoStream = self.part.getSelectedStreamOfType(plexstream.PlexStream.TYPE_VIDEO)
                self.audioStream = self.part.getSelectedStreamOfType(plexstream.PlexStream.TYPE_AUDIO)
                self.subtitleStream = self.part.getSelectedStreamOfType(plexstream.PlexStream.TYPE_SUBTITLE)
            else:
                util.WARN_LOG("Media does not contain a valid part")

            util.LOG("Choice media: {0} part:{1}".format(media, partIndex))
            for streamType in ("videoStream", "audioStream", "subtitleStream"):
                attr = getattr(self, streamType)
                if attr:
                    util.LOG("Choice {0}: {1}".format(streamType, repr(attr)))
        else:
            util.WARN_LOG("Could not create media choice for invalid media")

    def __str__(self):
        return "direct playable={0} version={1}".format(self.isDirectPlayable, self.media)

    def __repr__(self):
        return self.__str__()
