import plexobjects
import plexstream
import plexrequest
import util


class PlexPart(plexobjects.PlexObject):
    def reload(self):
        self.initpath = self.key

    def __init__(self, data, initpath=None, server=None, media=None):
        plexobjects.PlexObject.__init__(self, data, initpath, server)
        self.container_ = self.container
        self.container = media
        self.streams = []

        # If we weren't given any data, this is a synthetic part
        if data is not None:
            self.streams = [plexstream.PlexStream(e, initpath=self.initpath, server=self.server) for e in data if e.tag == 'Stream']
            if self.indexes:
                indexKeys = self.indexes('').split(",")
                self.indexes = util.AttributeDict()
                for indexKey in indexKeys:
                    self.indexes[indexKey] = True

    def getAddress(self):
        address = self.key

        if address != "":
            # TODO(schuyler): Do we need to add a token? Or will it be taken care of via header else:where?
            address = self.container.getAbsolutePath(address)

        return address

    def isAccessible(self):
        # If we haven't fetched accessibility info, assume it's accessible.
        return self.accessible.asBool() if self.accessible else True

    def isAvailable(self):
        # If we haven't fetched availability info, assume it's available
        return not self.exists or self.exists.asBool()

    def getStreamsOfType(self, streamType):
        streams = []

        foundSelected = False

        for stream in self.streams:
            if stream.streamType.asInt() == streamType:
                streams.append(stream)

                if stream.isSelected():
                    foundSelected = True

        # If this is subtitles, add the none option
        if streamType == plexstream.PlexStream.TYPE_SUBTITLE:
            none = plexstream.NoneStream()
            streams.insert(0, none)
            none.setSelected(not foundSelected)

        return streams

    # def getSelectedStreamStringOfType(self, streamType):
    #     default = None
    #     availableStreams = 0
    #     for stream in self.streams:
    #         if stream.streamType.asInt() == streamType:
    #             availableStreams = availableStreams + 1
    #             if stream.isSelected() or (default is None and streamType != stream.TYPE_SUBTITLE):
    #                 default = stream

    #     if default is not None:
    #         availableStreams = availableStreams - 1
    #         title = default.getTitle()
    #         suffix = "More"
    #     else:
    #         title = "None"
    #         suffix = "Available"

    #     if availableStreams > 0 and streamType != stream.TYPE_VIDEO:
    #         # Indicate available streams to choose from, excluding video
    #         # streams until the server supports multiple videos streams.

    #         return u"{0} : {1} {2}".format(title, availableStreams, suffix)
    #     else:
    #         return title

    def getSelectedStreamOfType(self, streamType):
        # Video streams, in particular, may not be selected. Pretend like the
        # first one was selected.

        default = None

        for stream in self.streams:
            if stream.streamType.asInt() == streamType:
                if stream.isSelected():
                    return stream
                elif default is None and streamType != stream.TYPE_SUBTITLE:
                    default = stream

        return default

    def setSelectedStream(self, streamType, streamId, async):
        if streamType == plexstream.PlexStream.TYPE_AUDIO:
            typeString = "audio"
        elif streamType == plexstream.PlexStream.TYPE_SUBTITLE:
            typeString = "subtitle"
        elif streamType == plexstream.PlexStream.TYPE_VIDEO:
            typeString = "video"
        else:
            return None

        path = "/library/parts/{0}?{1}StreamID={2}".format(self.id(''), typeString, streamId)

        if self.getServer().supportsFeature("allPartsStreamSelection"):
            path = path + "&allParts=1"

        request = plexrequest.PlexRequest(self.getServer(), path, "PUT")

        if async:
            context = request.createRequestContext("ignored")
            import plexapp
            plexapp.APP.startRequest(request, context, "")
        else:
            request.postToStringWithTimeout()

        matching = plexstream.NoneStream()

        # Update any affected streams
        for stream in self.streams:
            if stream.streamType.asInt() == streamType:
                if stream.id == streamId:
                    stream.setSelected(True)
                    matching = stream
                elif stream.isSelected():
                    stream.setSelected(False)

        return matching

    def isIndexed(self):
        return bool(self.indexes)

    def getIndexUrl(self, indexKey):
        path = self.getIndexPath(indexKey)
        if path is not None:
            return self.container.server.buildUrl(path + "?interval=10000", True)
        else:
            return None

    def getIndexPath(self, indexKey, interval=None):
        if self.indexes is not None and indexKey in self.indexes:
            return "/library/parts/{0}/indexes/{1}".format(self.id, indexKey)
        else:
            return None

    def hasStreams(self):
        return bool(self.streams)

    def __str__(self):
        return "Part {0} {1}".format(self.id("NaN"), self.key)

    def __eq__(self, other):
        if other is None:
            return False

        if self.__class__ != other.__class__:
            return False

        return self.id == other.id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return self.__str__()

    # TODO(schuyler): getStreams, getIndexThumbUrl
