# Most of this is ported from Roku code and much of it is currently unused
# TODO: Perhaps remove unnecessary code
import time

import util
import urllib
import urlparse
import plexapp
import plexrequest
import callback
import http


class ServerTimeline(util.AttributeDict):
    def reset(self):
        self.expires = time.time() + 15

    def isExpired(self):
        return time.time() > self.get('expires', 0)


class TimelineData(util.AttributeDict):
    def __init__(self, timelineType, *args, **kwargs):
        util.AttributeDict.__init__(self, *args, **kwargs)
        self.type = timelineType
        self.state = "stopped"
        self.item = None
        self.choice = None
        self.playQueue = None

        self.controllable = util.AttributeDict()
        self.controllableStr = None

        self.attrs = util.AttributeDict()

        # Set default controllable for all content. Other controllable aspects
        # will be set based on the players content.
        #
        self.setControllable("playPause", True)
        self.setControllable("stop", True)

    def setControllable(self, name, isControllable):
        if isControllable:
            self.controllable[name] = ""
        else:
            if name in self.controllable:
                del self.controllable[name]

        self.controllableStr = None

    def updateControllableStr(self):
        if not self.controllableStr:
            self.controllableStr = ""
            prependComma = False

            for name in self.controllable:
                if prependComma:
                    self.controllableStr += ','
                else:
                    prependComma = True
                self.controllableStr += name

    def toXmlAttributes(self, elem):
        self.updateControllableStr()
        elem.attrib["type"] = self.type
        elem.attrib["start"] = self.state
        elem.attrib["controllable"] = self.controllableStr

        if self.item:
            if self.item.duration:
                elem.attrib['duration'] = self.item.duration
            if self.item.ratingKey:
                elem.attrib['ratingKey'] = self.item.ratingKey
            if self.item.key:
                elem.attrib['key'] = self.item.key
            if self.item.container.address:
                elem.attrib['containerKey'] = self.item.container.address

            # Send the audio, video and subtitle choice if it's available
            if self.choice:
                for stream in ("audioStream", "videoStream", "subtitleStream"):
                    if self.choice.get(stream) and self.choice[stream].id:
                        elem.attrib[stream + "ID"] = self.choice[stream].id

            server = self.item.getServer()
            if server:
                elem.attrib["machineIdentifier"] = server.uuid

                if server.activeConnection:
                    parts = urlparse.uslparse(server.activeConnection.address)
                    elem.attrib["protocol"] = parts.scheme
                    elem.attrib["address"] = parts.netloc.split(':', 1)[0]
                    if ':' in parts.netloc:
                        elem.attrib["port"] = parts.netloc.split(':', 1)[-1]
                    elif parts.scheme == 'https':
                        elem.attrib["port"] = '443'
                    else:
                        elem.attrib["port"] = '80'

        if self.playQueue:
            elem.attrib["playQueueID"] = str(self.playQueue.id)
            elem.attrib["playQueueItemID"] = str(self.playQueue.selectedId)
            elem.attrib["playQueueVersion"] = str(self.playQueue.version)

        for key, val in self.attrs.items():
            elem.attrib[key] = val


class NowPlayingManager(object):
    def __init__(self):

        # Constants
        self.NAVIGATION = "navigation"
        self.FULLSCREEN_VIDEO = "fullScreenVideo"
        self.FULLSCREEN_MUSIC = "fullScreenMusic"
        self.FULLSCREEN_PHOTO = "fullScreenPhoto"
        self.TIMELINE_TYPES = ["video", "music", "photo"]

        # Members
        self.serverTimelines = util.AttributeDict()
        self.subscribers = util.AttributeDict()
        self.pollReplies = util.AttributeDict()
        self.timelines = util.AttributeDict()
        self.location = self.NAVIGATION

        self.textFieldName = None
        self.textFieldContent = None
        self.textFieldSecure = None

        # Initialization
        for timelineType in self.TIMELINE_TYPES:
            self.timelines[timelineType] = TimelineData(timelineType)

    def updatePlaybackState(self, timelineType, playerObject, state, time, playQueue=None, duration=0):
        timeline = self.timelines[timelineType]
        timeline.state = state
        timeline.item = playerObject.item
        timeline.choice = playerObject.choice
        timeline.playQueue = playQueue
        timeline.attrs["time"] = str(time)
        timeline.duration = duration

        # self.sendTimelineToAll()

        self.sendTimelineToServer(timelineType, timeline, time)

    def sendTimelineToServer(self, timelineType, timeline, time):
        if not hasattr(timeline.item, 'getServer') or not timeline.item.getServer():
            return

        serverTimeline = self.getServerTimeline(timelineType)

        # Only send timeline if it's the first, item changes, playstate changes or timer pops
        itemsEqual = timeline.item and serverTimeline.item and timeline.item.ratingKey == serverTimeline.item.ratingKey
        if itemsEqual and timeline.state == serverTimeline.state and not serverTimeline.isExpired():
            return

        serverTimeline.reset()
        serverTimeline.item = timeline.item
        serverTimeline.state = timeline.state

        # Ignore sending timelines for multi part media with no duration
        obj = timeline.choice
        if obj and obj.part and obj.part.duration.asInt() == 0 and obj.media.parts and len(obj.media.parts) > 1:
            util.WARN_LOG("Timeline not supported: the current part doesn't have a valid duration")
            return

        # It's possible with timers and in player seeking for the time to be greater than the
        # duration, which causes a 400, so in that case we'll set the time to the duration.
        duration = timeline.item.duration.asInt() or timeline.duration
        if time > duration:
            time = duration

        params = util.AttributeDict()
        params["time"] = time
        params["duration"] = duration
        params["state"] = timeline.state
        params["guid"] = timeline.item.guid
        params["ratingKey"] = timeline.item.ratingKey
        params["url"] = timeline.item.url
        params["key"] = timeline.item.key
        params["containerKey"] = timeline.item.container.address
        if timeline.playQueue:
            params["playQueueItemID"] = timeline.playQueue.selectedId

        path = "/:/timeline"
        for paramKey in params:
            if params[paramKey]:
                path = http.addUrlParam(path, paramKey + "=" + urllib.quote(str(params[paramKey])))

        request = plexrequest.PlexRequest(timeline.item.getServer(), path)
        context = request.createRequestContext("timelineUpdate", callback.Callable(self.onTimelineResponse))
        context.playQueue = timeline.playQueue
        plexapp.APP.startRequest(request, context)

    def getServerTimeline(self, timelineType):
        if not self.serverTimelines.get(timelineType):
            serverTL = ServerTimeline()
            serverTL.reset()

            self.serverTimelines[timelineType] = serverTL

        return self.serverTimelines[timelineType]

    def nowPlayingSetControllable(self, timelineType, name, isControllable):
        self.timelines[timelineType].setControllable(name, isControllable)

    def onTimelineResponse(self, request, response, context):
        if not context.playQueue or not context.playQueue.refreshOnTimeline:
            return
        context.playQueue.refreshOnTimeline = False
        context.playQueue.refresh(False)
