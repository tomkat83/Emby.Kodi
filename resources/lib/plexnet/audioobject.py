import http
import mediadecisionengine
import util


class AudioObjectClass(object):
    def __init__(self, item):
        self.containerFormats = {
            'aac': "es.aac-adts"
        }

        self.item = item
        self.choice = mediadecisionengine.MediaDecisionEngine().chooseMedia(item)
        if self.choice:
            self.media = self.choice.media
        self.lyrics = None  # createLyrics(item, self.media)

    def build(self, directPlay=None):
        directPlay = directPlay or self.choice.isDirectPlayable

        obj = util.AttributeDict()

        # TODO(schuyler): Do we want/need to add anything generic here? Title? Duration?

        if directPlay:
            obj = self.buildDirectPlay(obj)
        else:
            obj = self.buildTranscode(obj)

        self.metadata = obj

        util.LOG("Constructed audio item for playback: {0}".format(obj))

        return self.metadata

    def buildTranscode(self, obj):
        transcodeServer = self.item.getTranscodeServer(True, "audio")
        if not transcodeServer:
            return None

        obj.streamFormat = "mp3"
        obj.isTranscoded = True
        obj.transcodeServer = transcodeServer

        builder = http.HttpRequest(transcodeServer.buildUrl("/music/:/transcode/universal/start.m3u8", True))
        builder.addParam("protocol", "http")
        builder.addParam("path", self.item.getAbsolutePath("key"))
        builder.addParam("session", self.item.getGlobal("clientIdentifier"))
        builder.addParam("directPlay", "0")
        builder.addParam("directStream", "0")

        obj.url = builder.getUrl()

        return obj

    def buildDirectPlay(self, obj):
        if self.choice.part:
            obj.url = self.item.getServer().buildUrl(self.choice.part.getAbsolutePath("key"), True)

            # Set and override the stream format if applicable
            obj.streamFormat = self.choice.media.container or 'mp3'
            if self.containerFormats.get(obj.streamFormat):
                obj.streamFormat = self.containerFormats[obj.streamFormat]

            # If we're direct playing a FLAC, bitrate can be required, and supposedly
            # this is the only way to do it. plexinc/roku-client#48
            #
            bitrate = self.choice.media.getInt("bitrate")
            if bitrate > 0:
                obj.streams = [{'url': obj.url, 'bitrate': bitrate}]

            return obj

        # We may as well fallback to transcoding if we could not direct play
        return self.buildTranscode(obj)

    def getLyrics(self):
        return self.lyrics

    def hasLyrics(self):
        return False
        # return self.lyrics.isAvailable()
