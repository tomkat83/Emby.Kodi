import plexobjects
import util


class PlexStream(plexobjects.PlexObject):
    # Constants
    TYPE_UNKNOWN = 0
    TYPE_VIDEO = 1
    TYPE_AUDIO = 2
    TYPE_SUBTITLE = 3
    TYPE_LYRICS = 4

    # We have limited font support, so make a very modest effort at using
    # English names for common unsupported languages.

    SAFE_LANGUAGE_NAMES = {
        'ara': "Arabic",
        'arm': "Armenian",
        'bel': "Belarusian",
        'ben': "Bengali",
        'bul': "Bulgarian",
        'chi': "Chinese",
        'cze': "Czech",
        'gre': "Greek",
        'heb': "Hebrew",
        'hin': "Hindi",
        'jpn': "Japanese",
        'kor': "Korean",
        'rus': "Russian",
        'srp': "Serbian",
        'tha': "Thai",
        'ukr': "Ukrainian",
        'yid': "Yiddish"
    }

    def reload(self):
        pass

    def getTitle(self, translate_func=util.dummyTranslate):
        title = self.getLanguageName(translate_func)
        streamType = self.streamType.asInt()

        if streamType == self.TYPE_VIDEO:
            title = self.getCodec() or translate_func("Unknown")
        elif streamType == self.TYPE_AUDIO:
            codec = self.getCodec()
            channels = self.getChannels(translate_func)

            if codec != "" and channels != "":
                title += u" ({0} {1})".format(codec, channels)
            elif codec != "" or channels != "":
                title += u" ({0}{1})".format(codec, channels)
        elif streamType == self.TYPE_SUBTITLE:
            extras = []

            codec = self.getCodec()
            if codec:
                extras.append(codec)

            if not self.key:
                extras.append(translate_func("Embedded"))

            if self.forced.asBool():
                extras.append(translate_func("Forced"))

            if len(extras) > 0:
                title += u" ({0})".format('/'.join(extras))
        elif streamType == self.TYPE_LYRICS:
            title = translate_func("Lyrics")
            if self.format:
                title += u" ({0})".format(self.format)

        return title

    def getCodec(self):
        codec = (self.codec or '').lower()

        if codec in ('dca', 'dca-ma', 'dts-hd', 'dts-es', 'dts-hra'):
            codec = "DTS"
        else:
            codec = codec.upper()

        return codec

    def getChannels(self, translate_func=util.dummyTranslate):
        channels = self.channels.asInt()

        if channels == 1:
            return translate_func("Mono")
        elif channels == 2:
            return translate_func("Stereo")
        elif channels > 0:
            return "{0}.1".format(channels - 1)
        else:
            return ""

    def getLanguageName(self, translate_func=util.dummyTranslate):
        code = self.languageCode

        if not code:
            return translate_func("Unknown")

        return self.SAFE_LANGUAGE_NAMES.get(code) or self.language or "Unknown"

    def getSubtitlePath(self):
        query = "?encoding=utf-8"

        if self.codec == "smi":
            query += "&format=srt"

        return self.key + query

    def getSubtitleServerPath(self):
        if not self.key:
            return None

        return self.getServer().buildUrl(self.getSubtitlePath(), True)

    def isSelected(self):
        return self.selected.asBool()

    def setSelected(self, selected):
        self.selected = plexobjects.PlexValue(selected and '1' or '0')

    def __str__(self):
        return self.getTitle()

    def __eq__(self, other):
        if not other:
            return False

        if self.__class__ != other.__class__:
            return False

        for attr in ("streamType", "language", "codec", "channels", "index"):
            if getattr(self, attr) != getattr(other, attr):
                return False


# Synthetic subtitle stream for 'none'

class NoneStream(PlexStream):
    def __init__(self, *args, **kwargs):
        PlexStream.__init__(self, None, *args, **kwargs)
        self.id = plexobjects.PlexValue("0")
        self.streamType = plexobjects.PlexValue(str(self.TYPE_SUBTITLE))

    def getTitle(self, translate_func=util.dummyTranslate):
        return translate_func("None")
