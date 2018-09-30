# -*- coding: utf-8 -*-
import http
import time
import util
import exceptions
import compat
import verlib
import re
import json
from xml.etree import ElementTree

import signalsmixin
import plexobjects
import plexresource
import plexlibrary
import plexapp
# from plexapi.client import Client
# from plexapi.playqueue import PlayQueue


TOTAL_QUERIES = 0
DEFAULT_BASEURI = 'http://localhost:32400'


class PlexServer(plexresource.PlexResource, signalsmixin.SignalsMixin):
    TYPE = 'PLEXSERVER'

    def __init__(self, data=None):
        signalsmixin.SignalsMixin.__init__(self)
        plexresource.PlexResource.__init__(self, data)
        self.accessToken = None
        self.multiuser = False
        self.isSupported = None
        self.hasFallback = False
        self.supportsAudioTranscoding = False
        self.supportsVideoTranscoding = False
        self.supportsPhotoTranscoding = False
        self.supportsVideoRemuxOnly = False
        self.supportsScrobble = True
        self.allowsMediaDeletion = False
        self.allowChannelAccess = False
        self.activeConnection = None
        self.serverClass = None

        self.pendingReachabilityRequests = 0
        self.pendingSecureRequests = 0

        self.features = {}
        self.librariesByUuid = {}

        self.server = self
        self.session = http.Session()

        self.owner = None
        self.owned = False
        self.synced = False
        self.sameNetwork = False
        self.uuid = None
        self.name = None
        self.platform = None
        self.versionNorm = None
        self.rawVersion = None
        self.transcodeSupport = False

        if data is None:
            return

        self.owner = data.attrib.get('sourceTitle')
        self.owned = data.attrib.get('owned') == '1'
        self.synced = data.attrib.get('synced') == '1'
        self.sameNetwork = data.attrib.get('publicAddressMatches') == '1'
        self.uuid = data.attrib.get('clientIdentifier')
        self.name = data.attrib.get('name')
        self.platform = data.attrib.get('platform')
        self.rawVersion = data.attrib.get('productVersion')
        self.versionNorm = util.normalizedVersion(self.rawVersion)
        self.transcodeSupport = data.attrib.get('transcodeSupport') == '1'

    def __eq__(self, other):
        if not other:
            return False
        if self.__class__ != other.__class__:

            return False
        return self.uuid == other.uuid and self.owner == other.owner

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return "<PlexServer {0} owned: {1} uuid: {2} version: {3}>".format(repr(self.name), self.owned, self.uuid, self.versionNorm)

    def __repr__(self):
        return self.__str__()

    def close(self):
        self.session.cancel()

    def get(self, attr, default=None):
        return default

    @property
    def isSecure(self):
        if self.activeConnection:
            return self.activeConnection.isSecure

    def getObject(self, key):
        data = self.query(key)
        return plexobjects.buildItem(self, data[0], key, container=self)

    def hubs(self, section=None, count=None, search_query=None):
        hubs = []

        params = {}
        if search_query:
            q = '/hubs/search'
            params['query'] = search_query.lower()
            if section:
                params['sectionId'] = section

            if count is not None:
                params['limit'] = count
        else:
            q = '/hubs'
            if section:
                if section == 'playlists':
                    audio = plexlibrary.AudioPlaylistHub(False, server=self.server)
                    video = plexlibrary.VideoPlaylistHub(False, server=self.server)
                    if audio.items:
                        hubs.append(audio)
                    if video.items:
                        hubs.append(video)
                    return hubs
                else:
                    q = '/hubs/sections/%s' % section

            if count is not None:
                params['count'] = count

        data = self.query(q, params=params)
        container = plexobjects.PlexContainer(data, initpath=q, server=self, address=q)

        for elem in data:
            hubs.append(plexlibrary.Hub(elem, server=self, container=container))
        return hubs

    def playlists(self, start=0, size=10, hub=None):
        try:
            return plexobjects.listItems(self, '/playlists/all')
        except exceptions.BadRequest:
            return None

    @property
    def library(self):
        if self.platform == 'cloudsync':
            return plexlibrary.Library(None, server=self)
        else:
            return plexlibrary.Library(self.query('/library/'), server=self)

    def buildUrl(self, path, includeToken=False):
        if self.activeConnection:
            return self.activeConnection.buildUrl(self, path, includeToken)
        else:
            util.WARN_LOG("Server connection is None, returning an empty url")
            return ""

    def query(self, path, method=None, **kwargs):
        method = method or self.session.get
        url = self.buildUrl(path, includeToken=True)
        util.LOG('{0} {1}'.format(method.__name__.upper(), re.sub('X-Plex-Token=[^&]+', 'X-Plex-Token=****', url)))
        try:
            response = method(url, **kwargs)
            if response.status_code not in (200, 201):
                codename = http.status_codes.get(response.status_code, ['Unknown'])[0]
                raise exceptions.BadRequest('({0}) {1}'.format(response.status_code, codename))
            data = response.text.encode('utf8')
        except http.requests.ConnectionError:
            util.ERROR()
            return None

        return ElementTree.fromstring(data) if data else None

    def getImageTranscodeURL(self, path, width, height, **extraOpts):
        if not path:
            return ''

        params = ("&width=%s&height=%s" % (width, height)) + ''.join(["&%s=%s" % (key, extraOpts[key]) for key in extraOpts])

        if "://" in path:
            imageUrl = self.convertUrlToLoopBack(path)
        else:
            imageUrl = "http://127.0.0.1:" + self.getLocalServerPort() + path

        path = "/photo/:/transcode?url=" + compat.quote_plus(imageUrl) + params

        # Try to use a better server to transcode for synced servers
        if self.synced:
            import plexservermanager
            selectedServer = plexservermanager.MANAGER.getTranscodeServer("photo")
            if selectedServer:
                return selectedServer.buildUrl(path, True)

        if self.activeConnection:
            return self.activeConnection.simpleBuildUrl(self, path)
        else:
            util.WARN_LOG("Server connection is None, returning an empty url")
            return ""

    def isReachable(self, onlySupported=True):
        if onlySupported and not self.isSupported:
            return False

        return self.activeConnection and self.activeConnection.state == plexresource.ResourceConnection.STATE_REACHABLE

    def isLocalConnection(self):
        return self.activeConnection and (self.sameNetwork or self.activeConnection.isLocal)

    def isRequestToServer(self, url):
        if not self.activeConnection:
            return False

        if ':' in self.activeConnection.address[8:]:
            schemeAndHost = self.activeConnection.address.rsplit(':', 1)[0]
        else:
            schemeAndHost = self.activeConnection.address

        return url.startswith(schemeAndHost)

    def getToken(self):
        # It's dangerous to use for each here, because it may reset the index
        # on self.connections when something else was in the middle of an iteration.

        for i in range(len(self.connections)):
            conn = self.connections[i]
            if conn.token:
                return conn.token

        return None

    def getLocalServerPort(self):
        # TODO(schuyler): The correct thing to do here is to iterate over local
        # connections and pull out the port. For now, we're always returning 32400.

        return '32400'

    def collectDataFromRoot(self, data):
        # Make sure we're processing data for our server, and not some other
        # server that happened to be at the same IP.
        if self.uuid != data.attrib.get('machineIdentifier'):
            util.LOG("Got a reachability response, but from a different server")
            return False

        self.serverClass = data.attrib.get('serverClass')
        self.supportsAudioTranscoding = data.attrib.get('transcoderAudio') == '1'
        self.supportsVideoTranscoding = data.attrib.get('transcoderVideo') == '1' or data.attrib.get('transcoderVideoQualities')
        self.supportsVideoRemuxOnly = data.attrib.get('transcoderVideoRemuxOnly') == '1'
        self.supportsPhotoTranscoding = data.attrib.get('transcoderPhoto') == '1' or (
            not data.attrib.get('transcoderPhoto') and not self.synced and not self.isSecondary()
        )
        self.allowChannelAccess = data.attrib.get('allowChannelAccess') == '1' or (
            not data.attrib.get('allowChannelAccess') and self.owned and not self.synced and not self.isSecondary()
        )
        self.supportsScrobble = not self.isSecondary() or self.synced
        self.allowsMediaDeletion = not self.synced and self.owned and data.attrib.get('allowMediaDeletion') == '1'
        self.multiuser = data.attrib.get('multiuser') == '1'
        self.name = data.attrib.get('friendlyName') or self.name
        self.platform = data.attrib.get('platform')

        # TODO(schuyler): Process transcoder qualities

        self.rawVersion = data.attrib.get('version')
        if self.rawVersion:
            self.versionNorm = util.normalizedVersion(self.rawVersion)

        features = {
            'mkvTranscode': '0.9.11.11',
            'themeTranscode': '0.9.14.0',
            'allPartsStreamSelection': '0.9.12.5',
            'claimServer': '0.9.14.2',
            'streamingBrain': '1.2.0'
        }

        for f, v in features.items():
            if util.normalizedVersion(v) <= self.versionNorm:
                self.features[f] = True

        appMinVer = plexapp.INTERFACE.getGlobal('minServerVersionArr', '0.0.0.0')
        self.isSupported = self.isSecondary() or util.normalizedVersion(appMinVer) <= self.versionNorm

        util.DEBUG_LOG("Server information updated from reachability check: {0}".format(self))

        return True

    def updateReachability(self, force=True, allowFallback=False):
        if not force and self.activeConnection and self.activeConnection.state != plexresource.ResourceConnection.STATE_UNKNOWN:
            return

        util.LOG('Updating reachability for {0}: conns={1}, allowFallback={2}'.format(repr(self.name), len(self.connections), allowFallback))

        epoch = time.time()
        retrySeconds = 60
        minSeconds = 10
        for i in range(len(self.connections)):
            conn = self.connections[i]
            diff = epoch - (conn.lastTestedAt or 0)
            if conn.hasPendingRequest:
                util.DEBUG_LOG("Skip reachability test for {0} (has pending request)".format(conn))
            elif diff < minSeconds or (not self.isSecondary() and self.isReachable() and diff < retrySeconds):
                util.DEBUG_LOG("Skip reachability test for {0} (checked {1} secs ago)".format(conn, diff))
            elif conn.testReachability(self, allowFallback):
                self.pendingReachabilityRequests += 1
                if conn.isSecure:
                    self.pendingSecureRequests += 1

                if self.pendingReachabilityRequests == 1:
                    self.trigger("started:reachability")

        if self.pendingReachabilityRequests <= 0:
            self.trigger("completed:reachability")

    def cancelReachability(self):
        for i in range(len(self.connections)):
            conn = self.connections[i]
            conn.cancelReachability()

    def onReachabilityResult(self, connection):
        connection.lastTestedAt = time.time()
        connection.hasPendingRequest = None
        self.pendingReachabilityRequests -= 1
        if connection.isSecure:
            self.pendingSecureRequests -= 1

        util.DEBUG_LOG("Reachability result for {0}: {1} is {2}".format(repr(self.name), connection.address, connection.state))

        # Noneate active connection if the state is unreachable
        if self.activeConnection and self.activeConnection.state != plexresource.ResourceConnection.STATE_REACHABLE:
            self.activeConnection = None

        # Pick a best connection. If we already had an active connection and
        # it's still reachable, stick with it. (replace with local if
        # available)
        best = self.activeConnection
        for i in range(len(self.connections) - 1, -1, -1):
            conn = self.connections[i]

            if not best or conn.getScore() > best.getScore():
                best = conn

        if best and best.state == best.STATE_REACHABLE:
            if best.isSecure or self.pendingSecureRequests <= 0:
                self.activeConnection = best
            else:
                util.DEBUG_LOG("Found a good connection for {0}, but holding out for better".format(repr(self.name)))

        if self.pendingReachabilityRequests <= 0:
            # Retest the server with fallback enabled. hasFallback will only
            # be True if there are available insecure connections and fallback
            # is allowed.

            if self.hasFallback:
                self.updateReachability(False, True)
            else:
                self.trigger("completed:reachability")

        util.LOG("Active connection for {0} is {1}".format(repr(self.name), self.activeConnection))

        import plexservermanager
        plexservermanager.MANAGER.updateReachabilityResult(self, bool(self.activeConnection))

    def markAsRefreshing(self):
        for i in range(len(self.connections)):
            conn = self.connections[i]
            conn.refreshed = False

    def markUpdateFinished(self, source):
        # Any connections for the given source which haven't been refreshed should
        # be removed. Since removing from a list is hard, we'll make a new list.
        toKeep = []
        hasSecureConn = False

        for i in range(len(self.connections)):
            conn = self.connections[i]
            if not conn.refreshed:
                conn.sources = conn.sources & (~source)

                # If we lost our plex.tv connection, don't remember the token.
                if source == conn.SOURCE_MYPLEX:
                    conn.token = None

            if conn.sources:
                if conn.address[:5] == "https":
                    hasSecureConn = True
                toKeep.append(conn)
            else:
                util.DEBUG_LOG("Removed connection for {0} after updating connections for {1}".format(repr(self.name), source))
                if conn == self.activeConnection:
                    util.DEBUG_LOG("Active connection lost")
                    self.activeConnection = None

        # Update fallback flag if our connections have changed
        if len(toKeep) != len(self.connections):
            for conn in toKeep:
                conn.isFallback = hasSecureConn and conn.address[:5] != "https"

        self.connections = toKeep

        return len(self.connections) > 0

    def merge(self, other):
        # Wherever this other server came from, assume its information is better
        # except for manual connections.

        if other.sourceType != plexresource.ResourceConnection.SOURCE_MANUAL:
            self.name = other.name
            self.versionNorm = other.versionNorm
            self.sameNetwork = other.sameNetwork

        # Merge connections
        for otherConn in other.connections:
            merged = False
            for i in range(len(self.connections)):
                myConn = self.connections[i]
                if myConn == otherConn:
                    myConn.merge(otherConn)
                    merged = True
                    break

            if not merged:
                self.connections.append(otherConn)

        # If the other server has a token, then it came from plex.tv, which
        # means that its ownership information is better than ours. But if
        # it was discovered, then it may incorrectly claim to be owned, so
        # we stick with whatever we already had.

        if other.getToken():
            self.owned = other.owned
            self.owner = other.owner

    def supportsFeature(self, feature):
        return feature in self.features

    def getVersion(self):
        if not self.versionNorm:
            return ''

        return str(self.versionNorm)

    def convertUrlToLoopBack(self, url):
        # If the URL starts with our server URL, replace it with 127.0.0.1:32400.
        if self.isRequestToServer(url):
            url = 'http://127.0.0.1:32400/' + url.split('://', 1)[-1].split('/', 1)[-1]
        return url

    def resetLastTest(self):
        for i in range(len(self.connections)):
            conn = self.connections[i]
            conn.lastTestedAt = None

    def isSecondary(self):
        return self.serverClass == "secondary"

    def getLibrarySectionByUuid(self, uuid=None):
        if not uuid:
            return None
        return self.librariesByUuid[uuid]

    def setLibrarySectionByUuid(self, uuid, library):
        self.librariesByUuid[uuid] = library

    def hasInsecureConnections(self):
        if plexapp.INTERFACE.getPreference('allow_insecure') == 'always':
            return False

        # True if we have any insecure connections we have disallowed
        for i in range(len(self.connections)):
            conn = self.connections[i]
            if not conn.isSecure and conn.state == conn.STATE_INSECURE:
                return True

        return False

    def hasSecureConnections(self):
        for i in range(len(self.connections)):
            conn = self.connections[i]
            if conn.isSecure:
                return True

        return False

    def getLibrarySectionPrefs(self, uuid):
        # TODO: Make sure I did this right - ruuk
        librarySection = self.getLibrarySectionByUuid(uuid)

        if librarySection and librarySection.key:
            # Query and store the prefs only when asked for. We could just return the
            # items, but it'll be more useful to store the pref ids in an associative
            # array for ease of selecting the pref we need.

            if not librarySection.sectionPrefs:
                path = "/library/sections/{0}/prefs".format(librarySection.key)
                data = self.query(path)
                if data:
                    librarySection.sectionPrefs = {}
                    for elem in data:
                        item = plexobjects.buildItem(self, elem, path)
                        if item.id:
                            librarySection.sectionPrefs[item.id] = item

            return librarySection.sectionPrefs

        return None

    def swizzleUrl(self, url, includeToken=False):
        m = re.Search("^\w+:\/\/.+?(\/.+)", url)
        newUrl = m and m.group(1) or None
        return self.buildUrl(newUrl or url, includeToken)

    def hasHubs(self):
        return self.platform != 'cloudsync'

    @property
    def address(self):
        return self.activeConnection.address

    @classmethod
    def deSerialize(cls, jstring):
        try:
            serverObj = json.loads(jstring)
        except:
            util.ERROR()
            util.ERROR_LOG("Failed to deserialize PlexServer JSON")
            return

        import plexconnection

        server = createPlexServerForName(serverObj['uuid'], serverObj['name'])
        server.owned = bool(serverObj.get('owned'))
        server.sameNetwork = serverObj.get('sameNetwork')

        hasSecureConn = False
        for i in range(len(serverObj.get('connections', []))):
            conn = serverObj['connections'][i]
            if conn['address'][:5] == "https":
                hasSecureConn = True
                break

        for i in range(len(serverObj.get('connections', []))):
            conn = serverObj['connections'][i]
            isFallback = hasSecureConn and conn['address'][:5] != "https"
            sources = plexconnection.PlexConnection.SOURCE_BY_VAL[conn['sources']]
            connection = plexconnection.PlexConnection(sources, conn['address'], conn['isLocal'], conn['token'], isFallback)

            # Keep the secure connection on top
            if connection.isSecure:
                server.connections.insert(0, connection)
            else:
                server.connections.append(connection)

            if conn.get('active'):
                server.activeConnection = connection

        return server

    def serialize(self, full=False):
        serverObj = {
            'name': self.name,
            'uuid': self.uuid,
            'owned': self.owned,
            'connections': []
        }

        if full:
            for conn in self.connections:
                serverObj['connections'].append({
                    'sources': conn.sources,
                    'address': conn.address,
                    'isLocal': conn.isLocal,
                    'isSecure': conn.isSecure,
                    'token': conn.token
                })
                if conn == self.activeConnection:
                    serverObj['connections'][-1]['active'] = True
        else:
            serverObj['connections'] = [{
                'sources': self.activeConnection.sources,
                'address': self.activeConnection.address,
                'isLocal': self.activeConnection.isLocal,
                'isSecure': self.activeConnection.isSecure,
                'token': self.activeConnection.token or self.getToken(),
                'active': True
            }]

        return json.dumps(serverObj)


def dummyPlexServer():
    return createPlexServer()


def createPlexServer():
    return PlexServer()


def createPlexServerForConnection(conn):
    obj = createPlexServer()
    obj.connections.append(conn)
    obj.activeConnection = conn
    return obj


def createPlexServerForName(uuid, name):
    obj = createPlexServer()
    obj.uuid = uuid
    obj.name = name
    return obj


def createPlexServerForResource(resource):
    # resource.__class__ = PlexServer
    # resource.server = resource
    # resource.session = http.Session()
    return resource
