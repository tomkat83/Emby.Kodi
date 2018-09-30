import locks
import http
import plexobjects
import plexpart
import plexrequest
import util


class PlexMedia(plexobjects.PlexObject):
    def __init__(self, data, initpath=None, server=None, container=None):
        self._data = data.attrib
        plexobjects.PlexObject.__init__(self, data, initpath, server)
        self.container_ = self.get('container')
        self.container = container
        self.indirectHeaders = None
        self.parts = []
        # If we weren't given any data, this is a synthetic media
        if data is not None:
            self.parts = [plexpart.PlexPart(elem, initpath=self.initpath, server=self.server, media=self) for elem in data]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def hasStreams(self):
        return len(self.parts) > 0 and self.parts[0].hasStreams()

    def isIndirect(self):
        return self.get('indirect') == '1'

    def isAccessible(self):
        for part in self.parts:
            if not part.isAccessible():
                return False

        return True

    def isAvailable(self):
        for part in self.parts:
            if not part.isAvailable():
                return False

        return True

    def resolveIndirect(self):
        if not self.isIndirect() or locks.LOCKS.isLocked("resolve_indirect"):
            return self

        part = self.parts[0]
        if part is None:
            util.DEBUG("Failed to resolve indirect media: missing valid part")
            return None

        postBody = None
        postUrl = part.postURL
        request = plexrequest.PlexRequest(self.getServer(), part.key, postUrl is not None and "POST" or "GET")

        if postUrl is not None:
            util.DEBUG("Fetching content for indirect media POST URL: {0}".format(postUrl))
            # Force setting the certificate to handle following https redirects
            postRequest = http.HttpRequest(postUrl, None, True)
            postResponse = postRequest.getToStringWithTimeout(30)
            if len(postResponse) > 0 and type(postRequest.event) == "roUrlEvent":
                util.DEBUG("Retrieved data from postURL, posting to resolve container")
                crlf = chr(13) + chr(10)
                postBody = ""
                for header in postRequest.event.getResponseHeadersArray():
                    for name in header:
                        postBody = postBody + name + ": " + header[name] + crlf
                postBody = postBody + crlf + postResponse
            else:
                util.DEBUG("Failed to resolve indirect media postUrl")
                self.Set("indirect", "-1")
                return self

            request.addParam("postURL", postUrl)

        response = request.doRequestWithTimeout(30, postBody)

        item = response.items[0]
        if item is None or item.mediaItems[0] is None:
            util.DEBUG("Failed to resolve indirect media: no media items")
            self.indirect = -1
            return self

        media = item.mediaItems[0]

        # Add indirect headers to the media item
        media.indirectHeaders = util.AttributeDict()
        for header in (item.container.httpHeaders or '').split("&"):
            arr = header.split("=")
            if len(arr) == 2:
                media.indirectHeaders[arr[0]] = arr[1]

        # Reset the fallback media id if applicable
        if self.id.asInt() < 0:
            media.id = self.id

        return media.resolveIndirect()

    def __str__(self):
        extra = []
        attrs = ("videoCodec", "audioCodec", "audioChannels", "protocol", "id")
        if self.get('container'):
            extra.append("container={0}".format(self.get('container')))

        for astr in attrs:
            if hasattr(self, astr):
                attr = getattr(self, astr)
                if attr and not attr.NA:
                    extra.append("{0}={1}".format(astr, attr))

        return self.versionString(log_safe=True) + " " + ' '.join(extra)

    def versionString(self, log_safe=False):
        details = []
        details.append(self.getVideoResolutionString())
        if self.bitrate.asInt() > 0:
            details.append(util.bitrateToString(self.bitrate.asInt() * 1000))

        detailString = ', '.join(details)
        return (log_safe and ' * ' or u" \u2022 ").join(filter(None, [self.title, detailString]))

    def __eq__(self, other):
        if not other:
            return False

        if self.__class__ != other.__class__:
            return False

        return self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return self.__str__()

    def getVideoResolution(self):
        if self.videoResolution:
            standardDefinitionHeight = 480
            if str(util.validInt(filter(unicode.isdigit, self.videoResolution))) != self.videoResolution:
                return self.height.asInt() > standardDefinitionHeight and self.height.asInt() or standardDefinitionHeight
            else:
                return self.videoResolution.asInt(standardDefinitionHeight)

        return self.height.asInt()

    def getVideoResolutionString(self):
        resNumber = util.validInt(filter(unicode.isdigit, self.videoResolution))
        if resNumber > 0 and str(resNumber) == self.videoResolution:
            return self.videoResolution + "p"

        return self.videoResolution.upper()

    def isSelected(self):
        import plexapp
        return self.selected.asBool() or self.id == plexapp.INTERFACE.getPreference("local_mediaId")

    # TODO(schuyler): getParts
