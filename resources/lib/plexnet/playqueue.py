import re
import urllib
import time

import plexapp
import plexrequest
import callback
import plexobjects
import util
import signalsmixin


class AudioUsage(object):
    def __init__(self, skipsPerHour, playQueueId):
        self.HOUR = 3600
        self.skipsPerHour = skipsPerHour
        self.playQueueId = playQueueId
        self.skips = []

    def allowSkip(self):
        if self.skipsPerHour < 0:
            return True
        self.updateSkips()
        return len(self.skips) < self.skipsPerHour

    def updateSkips(self, reset=False):
        if reset or len(self.skips) == 0:
            if reset:
                self.skips = []
            return

        # Remove old skips if applicable
        epoch = util.now()
        if self.skips[0] + self.HOUR < epoch:
            newSkips = []
            for skip in self.skips:
                if skip + self.HOUR > epoch:
                    newSkips.append(skip)
            self.skips = newSkips
            self.log("updated skips")

    def registerSkip(self):
        self.skips.append(util.now())
        self.updateSkips()
        self.log("registered skip")

    def allowSkipMessage(self):
        if self.skipsPerHour < 0 or self.allowSkip():
            return None
        return "You can skip {0} songs an hour per mix.".format(self.skipsPerHour)

    def log(self, prefix):
        util.DEBUG_LOG("AudioUsage {0}: total skips={1}, allowed skips={2}".format(prefix, len(self.skips), self.skipsPerHour))


class UsageFactory(object):
    def __init__(self, play_queue):
        self.playQueue = play_queue
        self.type = play_queue.type
        self.usage = play_queue.usage

    @classmethod
    def createUsage(cls, playQueue):
        obj = cls(playQueue)

        if obj.type:
            if obj.type == "audio":
                return obj.createAudioUsage()

        util.DEBUG_LOG("Don't know how to usage for " + str(obj.type))
        return None

    def createAudioUsage(self):
        skips = self.playQueue.container.stationSkipsPerHour.asInt(-1)
        if skips == -1:
            return None

        # Create new usage if invalid, or if we start a new PQ, otherwise
        # we'll return the existing usage for the PQ.
        if not self.usage or self.usage.playQueueId != self.playQueue.id:
            self.usage = AudioUsage(skips, self.playQueue.id)

        return self.usage


class PlayOptions(util.AttributeDict):
    def __init__(self, *args, **kwargs):
        util.AttributeDict.__init__(self, *args, **kwargs)
        # At the moment, this is really just a glorified struct. But the
        # expected fields include key, shuffle, extraPrefixCount,
        # and unwatched. We may give this more definition over time.

        # These aren't widely used yet, but half inspired by a PMS discussion...
        self.CONTEXT_AUTO = 0
        self.CONTEXT_SELF = 1
        self.CONTEXT_PARENT = 2
        self.CONTEXT_CONTAINER = 3

        self.context = self.CONTEXT_AUTO


def createLocalPlayQueue(item, children, contentType, options):
    pass


class PlayQueueFactory(object):
    def getContentType(self, item):
        if item.isMusicOrDirectoryItem():
            return "audio"
        elif item.isVideoOrDirectoryItem():
            return "video"
        elif item.isPhotoOrDirectoryItem():
            return "photo"

        return None

    def canCreateRemotePlayQueue(self):
        if self.item.getServer().isSecondary():
            reason = "Server is secondary"
        elif not (self.item.isLibraryItem() or self.item.isGracenoteCollection() or self.item.isLibraryPQ):
            reason = "Item is not a library item or gracenote collection"
        else:
            return True

        util.DEBUG_LOG("Requires local play queue: " + reason)
        return False

    def itemRequiresRemotePlayQueue(self):
        # TODO(rob): handle entire section? (if we create PQ's of sections)
        # return item instanceof PlexSection || item.type == PlexObject.Type.artist;
        return self.item.type == "artist"


def createPlayQueueForItem(item, children=None, options=None, args=None):
    obj = PlayQueueFactory()

    contentType = obj.getContentType(item)
    if not contentType:
        # TODO(schuyler): We may need to try harder, but I'm not sure yet. For
        # example, what if we're shuffling an entire library?
        #
        # No reason to crash here. We can safely return None and move on.
        # We'll stop if we're in dev mode to catch and debug.
        #
        util.DEBUG_LOG("Don't know how to create play queue for item " + repr(item))
        return None

    obj.item = item

    options = PlayOptions(options or {})

    if obj.canCreateRemotePlayQueue():
        return createRemotePlayQueue(item, contentType, options, args)
    else:
        if obj.itemRequiresRemotePlayQueue():
            util.DEBUG_LOG("Can't create remote PQs and item does not support local PQs")
            return None
        else:
            return createLocalPlayQueue(item, children, contentType, options)


class PlayQueue(signalsmixin.SignalsMixin):
    TYPE = 'playqueue'

    isRemote = True

    def __init__(self, server, contentType, options=None):
        signalsmixin.SignalsMixin.__init__(self)
        self.id = None
        self.selectedId = None
        self.version = -1
        self.isShuffled = False
        self.isRepeat = False
        self.isRepeatOne = False
        self.isLocalPlayQueue = False
        self.isMixed = None
        self.totalSize = 0
        self.windowSize = 0
        self.forcedWindow = False
        self.container = None

        # Forced limitations
        self.allowShuffle = False
        self.allowSeek = True
        self.allowRepeat = False
        self.allowSkipPrev = False
        self.allowSkipNext = False
        self.allowAddToQueue = False

        self.refreshOnTimeline = False

        self.server = server
        self.type = contentType
        self._items = []
        self.options = options or util.AttributeDict()

        self.usage = None

        self.refreshTimer = None

        self.canceled = False
        self.responded = False
        self.initialized = False

        self.composite = plexobjects.PlexValue('', parent=self)

        # Add a few default options for specific PQ types
        if self.type == "audio":
            self.options.includeRelated = True
        elif self.type == "photo":
            self.setRepeat(True)

    def get(self, name):
        return getattr(self, name, plexobjects.PlexValue('', parent=self))

    @property
    def defaultArt(self):
        return self.current().defaultArt

    def waitForInitialization(self):
        start = time.time()
        timeout = util.TIMEOUT
        util.DEBUG_LOG('Waiting for playQueue to initialize...')
        while not self.canceled and not self.initialized:
            if not self.responded and time.time() - start > timeout:
                util.DEBUG_LOG('PlayQueue timed out wating for initialization')
                return self.initialized
            time.sleep(0.1)

        if self.initialized:
            util.DEBUG_LOG('PlayQueue initialized in {0:.2f} secs: {1}'.format(time.time() - start, self))
        else:
            util.DEBUG_LOG('PlayQueue failed to initialize')

        return self.initialized

    def onRefreshTimer(self):
        self.refreshTimer = None
        self.refresh(True, False)

    def refresh(self, force=True, delay=False, wait=False):
        # Ignore refreshing local PQs
        if self.isLocal():
            return

        if wait:
            self.responded = False
            self.initialized = False
        # We refresh our play queue if the caller insists or if we only have a
        # portion of our play queue loaded. In particular, this means that we don't
        # refresh the play queue if we're asked to refresh because a new track is
        # being played but we have the entire album loaded already.

        if force or self.isWindowed():
            if delay:
                # We occasionally want to refresh the PQ in response to moving to a
                # new item and starting playback, but if we refresh immediately:
                # we probably end up refreshing before PMS realizes we've moved on.
                # There's no great solution, but delaying our refresh by just a few
                # seconds makes us much more likely to get an accurate window (and
                # accurate selected IDs) from PMS.

                if not self.refreshTimer:
                    self.refreshTimer = plexapp.createTimer(5000, self.onRefreshTimer)
                    plexapp.APP.addTimer(self.refreshTimer)
            else:
                request = plexrequest.PlexRequest(self.server, "/playQueues/" + str(self.id))
                self.addRequestOptions(request)
                context = request.createRequestContext("refresh", callback.Callable(self.onResponse))
                plexapp.APP.startRequest(request, context)

        if wait:
            return self.waitForInitialization()

    def shuffle(self, shuffle=True):
        self.setShuffle(shuffle)

    def setShuffle(self, shuffle=None):
        if shuffle is None:
            shuffle = not self.isShuffled

        if self.isShuffled == shuffle:
            return

        if shuffle:
            command = "/shuffle"
        else:
            command = "/unshuffle"

        # Don't change self.isShuffled, it'll be set in OnResponse if all goes well

        request = plexrequest.PlexRequest(self.server, "/playQueues/" + str(self.id) + command, "PUT")
        self.addRequestOptions(request)
        context = request.createRequestContext("shuffle", callback.Callable(self.onResponse))
        plexapp.APP.startRequest(request, context)

    def setRepeat(self, repeat, one=False):
        if self.isRepeat == repeat and self.isRepeatOne == one:
            return

        self.options.repeat = repeat
        self.isRepeat = repeat
        self.isRepeatOne = one

    def moveItemUp(self, item):
        for index in range(1, len(self._items)):
            if self._items[index].get("playQueueItemID") == item.get("playQueueItemID"):
                if index > 1:
                    after = self._items[index - 2]
                else:
                    after = None

                self.swapItem(index, -1)
                self.moveItem(item, after)
                return True

        return False

    def moveItemDown(self, item):
        for index in range(len(self._items) - 1):
            if self._items[index].get("playQueueItemID") == item.get("playQueueItemID"):
                after = self._items[index + 1]
                self.swapItem(index)
                self.moveItem(item, after)
                return True

        return False

    def moveItem(self, item, after):
        if after:
            query = "?after=" + after.get("playQueueItemID", "-1")
        else:
            query = ""

        request = plexrequest.PlexRequest(self.server, "/playQueues/" + str(self.id) + "/items/" + item.get("playQueueItemID", "-1") + "/move" + query, "PUT")
        self.addRequestOptions(request)
        context = request.createRequestContext("move", callback.Callable(self.onResponse))
        plexapp.APP.startRequest(request, context)

    def swapItem(self, index, delta=1):
        before = self._items[index]
        after = self._items[index + delta]

        self._items[index] = after
        self._items[index + delta] = before

    def removeItem(self, item):
        request = plexrequest.PlexRequest(self.server, "/playQueues/" + str(self.id) + "/items/" + item.get("playQueueItemID", "-1"), "DELETE")
        self.addRequestOptions(request)
        context = request.createRequestContext("delete", callback.Callable(self.onResponse))
        plexapp.APP.startRequest(request, context)

    def addItem(self, item, addNext=False, excludeSeedItem=False):
        request = plexrequest.PlexRequest(self.server, "/playQueues/" + str(self.id), "PUT")
        request.addParam("uri", item.getItemUri())
        request.addParam("next", addNext and "1" or "0")
        request.addParam("excludeSeedItem", excludeSeedItem and "1" or "0")
        self.addRequestOptions(request)
        context = request.createRequestContext("add", callback.Callable(self.onResponse))
        plexapp.APP.startRequest(request, context)

    def onResponse(self, request, response, context):
        # Close any loading modal regardless of response status
        # Application().closeLoadingModal()
        util.DEBUG_LOG('playQueue: Received response')
        self.responded = True
        if response.parseResponse():
            util.DEBUG_LOG('playQueue: {0} items'.format(len(response.items)))
            self.container = response.container
            # Handle an empty PQ if we have specified an pqEmptyCallable
            if self.options and self.options.pqEmptyCallable:
                callable = self.options.pqEmptyCallable
                del self.options["pqEmptyCallable"]
                if len(response.items) == 0:
                    callable.call()
                    return

            self.id = response.container.playQueueID.asInt()
            self.isShuffled = response.container.playQueueShuffled.asBool()
            self.totalSize = response.container.playQueueTotalCount.asInt()
            self.windowSize = len(response.items)
            self.version = response.container.playQueueVersion.asInt()

            itemsChanged = False
            if len(response.items) == len(self._items):
                for i in range(len(self._items)):
                    if self._items[i] != response.items[i]:
                        itemsChanged = True
                        break
            else:
                itemsChanged = True

            if itemsChanged:
                self._items = response.items

            # Process any forced limitations
            self.allowSeek = response.container.allowSeek.asBool()
            self.allowShuffle = (
                self.totalSize > 1 and response.container.allowShuffle.asBool() and not response.container.playQueueLastAddedItemID
            )
            self.allowRepeat = response.container.allowRepeat.asBool()
            self.allowSkipPrev = self.totalSize > 1 and response.container.allowSkipPrevious != "0"
            self.allowSkipNext = self.totalSize > 1 and response.container.allowSkipNext != "0"

            # Figure out the selected track index and offset. PMS tries to make some
            # of this easy, but it might not realize that we've advanced to a new
            # track, so we can't blindly trust it. On the other hand, it's possible
            # that PMS completely changed the PQ item IDs (e.g. upon shuffling), so
            # we might need to use its values. We iterate through the items and try
            # to find the item that we believe is selected, only settling for what
            # PMS says if we fail.

            playQueueOffset = None
            selectedId = None
            pmsSelectedId = response.container.playQueueSelectedItemID.asInt()
            self.deriveIsMixed()

            # lastItem = None  # Not used
            for index in range(len(self._items)):
                item = self._items[index]

                if not playQueueOffset and item.playQueueItemID.asInt() == pmsSelectedId:
                    playQueueOffset = response.container.playQueueSelectedItemOffset.asInt() - index + 1

                    # Update the index of everything we've already past, and handle
                    # wrapping indexes (repeat).
                    for i in range(index):
                        pqIndex = playQueueOffset + i
                        if pqIndex < 1:
                            pqIndex = pqIndex + self.totalSize

                        self._items[i].playQueueIndex = plexobjects.PlexValue(str(pqIndex), parent=self._items[i])

                if playQueueOffset:
                    pqIndex = playQueueOffset + index
                    if pqIndex > self.totalSize:
                        pqIndex = pqIndex - self.totalSize

                    item.playQueueIndex = plexobjects.PlexValue(str(pqIndex), parent=item)

                # If we found the item that we believe is selected: we should
                # continue to treat it as selected.
                # TODO(schuyler): Should we be checking the metadata ID (rating key)
                # instead? I don't think it matters in practice, but it may be
                # more correct.

                if not selectedId and item.playQueueItemID.asInt() == self.selectedId:
                    selectedId = self.selectedId

            if not selectedId:
                self.selectedId = pmsSelectedId

            # TODO(schuyler): Set repeat as soon as PMS starts returning it

            # Fix up the container for all our items
            response.container.address = "/playQueues/" + str(self.id)

            # Create usage limitations
            self.usage = UsageFactory.createUsage(self)

            self.initialized = True
            self.trigger("change")

            if itemsChanged:
                self.trigger("items.changed")

    def isWindowed(self):
        return (not self.isLocal() and (self.totalSize > self.windowSize or self.forcedWindow))

    def hasNext(self):
        if self.isRepeatOne:
            return True

        if not self.allowSkipNext and -1 < self.items().index(self.current()) < (len(self.items()) - 1):  # TODO: Was 'or' - did change cause issues?
            return self.isRepeat and not self.isWindowed()

        return True

    def hasPrev(self):
        # return self.allowSkipPrev or self.items().index(self.current()) > 0
        return self.items().index(self.current()) > 0

    def next(self):
        if not self.hasNext():
            return None

        if self.isRepeatOne:
            return self.current()

        pos = self.items().index(self.current()) + 1
        if pos >= len(self.items()):
            if not self.isRepeat or self.isWindowed():
                return None
            pos = 0

        item = self.items()[pos]
        self.selectedId = item.playQueueItemID.asInt()
        return item

    def prev(self):
        if not self.hasPrev():
            return None
        if self.isRepeatOne:
            return self.current()
        pos = self.items().index(self.current()) - 1
        item = self.items()[pos]
        self.selectedId = item.playQueueItemID.asInt()
        return item

    def setCurrent(self, pos):
        if pos < 0 or pos >= len(self.items()):
            return False

        item = self.items()[pos]
        self.selectedId = item.playQueueItemID.asInt()
        return item

    def setCurrentItem(self, item):
        self.selectedId = item.playQueueItemID.asInt()

    def __eq__(self, other):
        if not other:
            return False
        if self.__class__ != other.__class__:
            return False
        return self.id == other.id and self.type == other.type

    def __ne__(self, other):
        return not self.__eq__(other)

    def addRequestOptions(self, request):
        boolOpts = ["repeat", "includeRelated"]
        for opt in boolOpts:
            if self.options.get(opt):
                request.addParam(opt, "1")

        intOpts = ["extrasPrefixCount"]
        for opt in intOpts:
            if self.options.get(opt):
                request.addParam(opt, str(self.options.get(opt)))

        includeChapters = self.options.get('includeChapters') is not None and self.options.includeChapters or 1
        request.addParam("includeChapters", str(includeChapters))

    def __repr__(self):
        return (
            str(self.__class__.__name__) + " " +
            str(self.type) + " windowSize=" +
            str(self.windowSize) + " totalSize=" +
            str(self.totalSize) + " selectedId=" +
            str(self.selectedId) + " shuffled=" +
            str(self.isShuffled) + " repeat=" +
            str(self.isRepeat) + " mixed=" +
            str(self.isMixed) + " allowShuffle=" +
            str(self.allowShuffle) + " version=" +
            str(self.version) + " id=" + str(self.id)
        )

    def isLocal(self):
        return self.isLocalPlayQueue

    def deriveIsMixed(self):
        if self.isMixed is None:
            self.isMixed = False

        lastItem = None
        for item in self._items:
            if not self.isMixed:
                if not item.get("parentKey"):
                    self.isMixed = True
                else:
                    self.isMixed = lastItem and item.get("parentKey") != lastItem.get("parentKey")

                lastItem = item

    def items(self):
        return self._items

    def current(self):
        for item in self.items():
            if item.playQueueItemID.asInt() == self.selectedId:
                return item

        return None

    def prevItem(self):
        last = None
        for item in self.items():
            if item.playQueueItemID.asInt() == self.selectedId:
                return last
            last = item

        return None


def createRemotePlayQueue(item, contentType, options, args):
    util.DEBUG_LOG('Creating remote playQueue request...')
    obj = PlayQueue(item.getServer(), contentType, options)

    # The item's URI is made up of the library section UUID, a descriptor of
    # the item type (item or directory), and the item's path, URL-encoded.

    uri = "library://" + item.getLibrarySectionUuid() + "/"
    itemType = item.isDirectory() and "directory" or "item"
    path = None

    if not options.key:
        # if item.onDeck and len(item.onDeck) > 0:
        #     options.key = item.onDeck[0].getAbsolutePath("key")
        # el
        if not item.isDirectory():
            options.key = item.get("key")

    # If we're asked to play unwatched, ignore the option unless we are unwatched.
    options.unwatched = options.unwatched and item.isUnwatched()

    # TODO(schuyler): Until we build postplay, we're not allowed to queue containers for episodes.
    if item.type == "episode":
        options.context = options.CONTEXT_SELF
    elif item.type == "movie":
        if not options.extrasPrefixCount and not options.resume:
            options.extrasPrefixCount = plexapp.INTERFACE.getPreference("cinema_trailers", 0)

    # How exactly to construct the item URI depends on the metadata type, though
    # whenever possible we simply use /library/metadata/:id.

    if item.isLibraryItem() and not item.isLibraryPQ:
        path = "/library/metadata/" + item.ratingKey
    else:
        path = item.getAbsolutePath("key")

    if options.context == options.CONTEXT_SELF:
        # If the context is specifically for just this item,: just use the
        # item's key and get out.
        pass
    elif item.type == "playlist":
        path = None
        uri = item.get("ratingKey")
        options.isPlaylist = True
    elif item.type == "track":
        # TODO(rob): Is there ever a time the container address is wrong? If we
        # expect to play a single track,: use options.CONTEXT_SELF.
        path = item.container.address or "/library/metadata/" + item.get("parentRatingKey", "")
        itemType = "directory"
    elif item.isPhotoOrDirectoryItem():
        if item.type == "photoalbum" or item.parentKey:
            path = item.getParentPath(item.type == "photoalbum" and "key" or "parentKey")
            itemType = "item"
        elif item.isDirectory():
            path = item.getAbsolutePath("key")
        else:
            path = item.container.address
            itemType = "directory"
            options.key = item.getAbsolutePath("key")

    elif item.type == "episode":
        path = "/library/metadata/" + item.get("grandparentRatingKey", "")
        itemType = "directory"
        options.key = item.getAbsolutePath("key")
    # elif item.type == "show":
    #     path = "/library/metadata/" + item.get("ratingKey", "")

    if path:
        if args:
            path += util.joinArgs(args)

        util.DEBUG_LOG("playQueue path: " + str(path))

        if "/search" not in path:
            # Convert a few params to the PQ spec
            convert = {
                'type': "sourceType",
                'unwatchedLeaves': "unwatched"
            }

            for key in convert:
                regex = re.compile("(?i)([?&])" + key + "=")
                path = regex.sub("\1" + convert[key] + "=", path)

        util.DEBUG_LOG("playQueue path: " + str(path))
        uri = uri + itemType + "/" + urllib.quote_plus(path)

    util.DEBUG_LOG("playQueue uri: " + str(uri))

    # Create the PQ request
    request = plexrequest.PlexRequest(obj.server, "/playQueues")

    request.addParam(not options.isPlaylist and "uri" or "playlistID", uri)
    request.addParam("type", contentType)
    # request.addParam('X-Plex-Client-Identifier', plexapp.INTERFACE.getGlobal('clientIdentifier'))

    # Add options we pass once during PQ creation
    if options.shuffle:
        request.addParam("shuffle", "1")
        options.key = None
    else:
        request.addParam("shuffle", "0")

    if options.key:
        request.addParam("key", options.key)

    # Add options we pass every time querying PQs
    obj.addRequestOptions(request)

    util.DEBUG_LOG('Initial playQueue request started...')
    context = request.createRequestContext("create", callback.Callable(obj.onResponse))
    plexapp.APP.startRequest(request, context, body='')

    return obj


def createPlayQueueForId(id, server=None, contentType=None):
    obj = PlayQueue(server, contentType)
    obj.id = id

    request = plexrequest.PlexRequest(server, "/playQueues/" + str(id))
    request.addParam("own", "1")
    obj.addRequestOptions(request)
    context = request.createRequestContext("own", callback.Callable(obj.onResponse))
    plexapp.APP.startRequest(request, context)

    return obj


class AudioPlayer():
    pass


class VideoPlayer():
    pass


class PhotoPlayer():
    pass


def addItemToPlayQueue(item, addNext=False):
    # See if we have an active play queue for this self.dia type or if we need to
    # create one.

    if item.isMusicOrDirectoryItem():
        player = AudioPlayer()
    elif item.isVideoOrDirectoryItem():
        player = VideoPlayer()
    elif item.isPhotoOrDirectoryItem():
        player = PhotoPlayer()
    else:
        player = None

    if not player:
        util.ERROR_LOG("Don't know how to add item to play queue: " + str(item))
        return None
    elif not player.allowAddToQueue():
        util.DEBUG_LOG("Not allowed to add to this player")
        return None

    if player.playQueue:
        playQueue = player.playQueue
        playQueue.addItem(item, addNext)
    else:
        options = PlayOptions()
        options.context = options.CONTEXT_SELF
        playQueue = createPlayQueueForItem(item, None, options)
        if playQueue:
            player.setPlayQueue(playQueue, False)

    return playQueue
