import json

import http
import plexconnection
import plexresource
import plexserver
import myplexserver
import signalsmixin
import callback
import plexapp
import gdm
import util


class SearchContext(dict):
    def __getattr__(self, attr):
        return self.get(attr)

    def __setattr__(self, attr, value):
        self[attr] = value


class PlexServerManager(signalsmixin.SignalsMixin):
    def __init__(self):
        signalsmixin.SignalsMixin.__init__(self)
        # obj.Append(ListenersMixin())
        self.serversByUuid = {}
        self.selectedServer = None
        self.transcodeServer = None
        self.channelServer = None
        self.deferReachabilityTimer = None

        self.startSelectedServerSearch()
        self.loadState()

        plexapp.APP.on("change:user", callback.Callable(self.onAccountChange))
        plexapp.APP.on("change:allow_insecure", callback.Callable(self.onSecurityChange))
        plexapp.APP.on("change:manual_connections", callback.Callable(self.onManualConnectionChange))

    def getSelectedServer(self):
        return self.selectedServer

    def setSelectedServer(self, server, force=False):
        # Don't do anything if the server is already selected.
        if self.selectedServer and self.selectedServer == server:
            return False

        if server:
            # Don't select servers that don't have connections.
            if not server.activeConnection:
                return False

            # Don't select servers that are not supported
            if not server.isSupported:
                return False

        if not self.selectedServer or force:
            util.LOG("Setting selected server to {0}".format(server))
            self.selectedServer = server

            # Update our saved state.
            self.saveState()

            # Notify anyone who might care.
            plexapp.APP.trigger("change:selectedServer", server=server)

            return True

        return False

    def getServer(self, uuid=None):
        if uuid is None:
            return None
        elif uuid == "myplex":
            return myplexserver.MyPlexServer()
        else:
            return self.serversByUuid[uuid]

    def getServers(self):
        servers = []
        for uuid in self.serversByUuid:
            if uuid != "myplex":
                servers.append(self.serversByUuid[uuid])

        return servers

    def hasPendingRequests(self):
        for server in self.getServers():
            if server.pendingReachabilityRequests:
                return True

        return False

    def removeServer(self, server):
        del self.serversByUuid[server.uuid]

        self.trigger('remove:server')

        if server == self.selectedServer:
            util.LOG("The selected server went away")
            self.setSelectedServer(None, force=True)

        if server == self.transcodeServer:
            util.LOG("The selected transcode server went away")
            self.transcodeServer = None

        if server == self.channelServer:
            util.LOG("The selected channel server went away")
            self.channelServer = None

    def updateFromConnectionType(self, servers, source):
        self.markDevicesAsRefreshing()

        for server in servers:
            self.mergeServer(server)

        if self.searchContext and source == plexresource.ResourceConnection.SOURCE_MYPLEX:
            self.searchContext.waitingForResources = False

        self.deviceRefreshComplete(source)
        self.updateReachability(True, True)
        self.saveState()

    def updateFromDiscovery(self, server):
        merged = self.mergeServer(server)

        if not merged.activeConnection:
            merged.updateReachability(False, True)
        else:
            # self.notifyAboutDevice(merged, True)
            pass

    def markDevicesAsRefreshing(self):
        for uuid in self.serversByUuid.keys():
            self.serversByUuid[uuid].markAsRefreshing()

    def mergeServer(self, server):
        if server.uuid in self.serversByUuid:
            existing = self.serversByUuid[server.uuid]
            existing.merge(server)
            util.DEBUG_LOG("Merged {0}".format(repr(server.name)))
            return existing
        else:
            self.serversByUuid[server.uuid] = server
            util.DEBUG_LOG("Added new server {0}".format(repr(server.name)))
            self.trigger("new:server", server=server)
            return server

    def deviceRefreshComplete(self, source):
        toRemove = []
        for uuid in self.serversByUuid:
            if not self.serversByUuid[uuid].markUpdateFinished(source):
                toRemove.append(uuid)

        for uuid in toRemove:
            server = self.serversByUuid[uuid]

            util.DEBUG_LOG("Server {0} has no more connections - removing".format(repr(server.name)))
            # self.notifyAboutDevice(server, False)
            self.removeServer(server)

    def updateReachability(self, force=False, preferSearch=False, defer=False):
        # We don't need to test any servers unless we are signed in and authenticated.
        if not plexapp.ACCOUNT.isAuthenticated and plexapp.ACCOUNT.isActive():
            util.LOG("Ignore testing server reachability until we're authenticated")
            return

        # To improve reachability performance and app startup, we'll try to test the
        # preferred server first, and defer the connection tests for a few seconds.

        hasPreferredServer = bool(self.searchContext.preferredServer)
        preferredServerExists = hasPreferredServer and self.searchContext.preferredServer in self.serversByUuid

        if preferSearch and hasPreferredServer and preferredServerExists:
            # Update the preferred server immediately if requested and exits
            util.LOG("Updating reachability for preferred server: force={0}".format(force))
            self.serversByUuid[self.searchContext.preferredServer].updateReachability(force)
            self.deferUpdateReachability()
        elif defer:
            self.deferUpdateReachability()
        elif hasPreferredServer and not preferredServerExists and gdm.DISCOVERY.isActive():
            # Defer the update if requested or if GDM discovery is enabled and
            # active while the preferred server doesn't exist.

            util.LOG("Defer update reachability until GDM has finished to help locate the preferred server")
            self.deferUpdateReachability(True, False)
        else:
            if self.deferReachabilityTimer:
                self.deferReachabilityTimer.cancel()
                self.deferReachabilityTimer = None

            util.LOG("Updating reachability for all devices: force={0}".format(force))
            for uuid in self.serversByUuid:
                self.serversByUuid[uuid].updateReachability(force)

    def cancelReachability(self):
        if self.deferReachabilityTimer:
            self.deferReachabilityTimer.cancel()
            self.deferReachabilityTimer = None

        for uuid in self.serversByUuid:
            self.serversByUuid[uuid].cancelReachability()

    def updateReachabilityResult(self, server, reachable=False):
        searching = not self.selectedServer and self.searchContext

        if reachable:
            # If we're in the middle of a search for our selected server, see if
            # this is a candidate.
            self.trigger('reachable:server', server=server)
            if searching:
                # If this is what we were hoping for, select it
                if server.uuid == self.searchContext.preferredServer:
                    self.setSelectedServer(server, True)
                elif server.synced:
                    self.searchContext.fallbackServer = server
                elif self.compareServers(self.searchContext.bestServer, server) < 0:
                    self.searchContext.bestServer = server
        else:
            # If this is what we were hoping for, see if there are any more pending
            # requests to hope for.

            if searching and server.uuid == self.searchContext.preferredServer and server.pendingReachabilityRequests <= 0:
                self.searchContext.preferredServer = None

            if server == self.selectedServer:
                util.LOG("Selected server is not reachable")
                self.setSelectedServer(None, True)

            if server == self.transcodeServer:
                util.LOG("The selected transcode server is not reachable")
                self.transcodeServer = None

            if server == self.channelServer:
                util.LOG("The selected channel server is not reachable")
                self.channelServer = None

        # See if we should settle for the best we've found so far.
        self.checkSelectedServerSearch()

    def checkSelectedServerSearch(self, skip_preferred=False, skip_owned=False):
        if self.selectedServer:
            return self.selectedServer
        elif self.searchContext:
            # If we're still waiting on the resources response then there's no
            # reason to settle, so don't even iterate over our servers.

            if self.searchContext.waitingForResources:
                util.DEBUG_LOG("Still waiting for plex.tv resources")
                return

            waitingForPreferred = False
            waitingForOwned = False
            waitingForAnything = False
            waitingToTestAll = bool(self.deferReachabilityTimer)

            if skip_preferred:
                self.searchContext.preferredServer = None
                if self.deferReachabilityTimer:
                    self.deferReachabilityTimer.cancel()
                    self.deferReachabilityTimer = None

            if not skip_owned:
                # Iterate over all our servers and see if we're waiting on any results
                servers = self.getServers()
                pendingCount = 0
                for server in servers:
                    if server.pendingReachabilityRequests > 0:
                        pendingCount += server.pendingReachabilityRequests
                        if server.uuid == self.searchContext.preferredServer:
                            waitingForPreferred = True
                        elif server.owned:
                            waitingForOwned = True
                        else:
                            waitingForAnything = True

                pendingString = "{0} pending reachability tests".format(pendingCount)

            if waitingForPreferred:
                util.LOG("Still waiting for preferred server: " + pendingString)
            elif waitingToTestAll:
                util.LOG("Preferred server not reachable, testing all servers now")
                self.updateReachability(True, False, False)
            elif waitingForOwned and (not self.searchContext.bestServer or not self.searchContext.bestServer.owned):
                util.LOG("Still waiting for an owned server: " + pendingString)
            elif waitingForAnything and not self.searchContext.bestServer:
                util.LOG("Still waiting for any server: {0}".format(pendingString))
            else:
                # No hope for anything better, let's select what we found
                util.LOG("Settling for the best server we found")
                self.setSelectedServer(self.searchContext.bestServer or self.searchContext.fallbackServer, True)
                return self.selectedServer

    def compareServers(self, first, second):
        if not first or not first.isSupported:
            return second and -1 or 0
        elif not second:
            return 1
        elif first.owned != second.owned:
            return first.owned and 1 or -1
        elif first.isLocalConnection() != second.isLocalConnection():
            return first.isLocalConnection() and 1 or -1
        else:
            return 0

    def loadState(self):
        jstring = plexapp.INTERFACE.getRegistry("PlexServerManager")
        if not jstring:
            return

        try:
            obj = json.loads(jstring)
        except:
            util.ERROR()
            obj = None

        if not obj:
            util.ERROR_LOG("Failed to parse PlexServerManager JSON")
            return

        for serverObj in obj['servers']:
            server = plexserver.createPlexServerForName(serverObj['uuid'], serverObj['name'])
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

            self.serversByUuid[server.uuid] = server

        util.LOG("Loaded {0} servers from registry".format(len(obj['servers'])))
        self.updateReachability(False, True)

    def saveState(self):
        # Serialize our important information to JSON and save it to the registry.
        # We'll always update server info upon connecting, so we don't need much
        # info here. We do have to use roArray instead of roList, because Brightscript.

        obj = {}

        servers = self.getServers()
        obj['servers'] = []

        for server in servers:
            # Don't save secondary servers. They should be discovered through GDM or myPlex.
            if not server.isSecondary():
                serverObj = {
                    'name': server.name,
                    'uuid': server.uuid,
                    'owned': server.owned,
                    'sameNetwork': server.sameNetwork,
                    'connections': []
                }

                for i in range(len(server.connections)):
                    conn = server.connections[i]
                    serverObj['connections'].append({
                        'sources': conn.sources,
                        'address': conn.address,
                        'isLocal': conn.isLocal,
                        'isSecure': conn.isSecure,
                        'token': conn.token
                    })

                obj['servers'].append(serverObj)

        if self.selectedServer and not self.selectedServer.synced and not self.selectedServer.isSecondary():
            plexapp.INTERFACE.setPreference("lastServerId", self.selectedServer.uuid)

        plexapp.INTERFACE.setRegistry("PlexServerManager", json.dumps(obj))

    def clearState(self):
        plexapp.INTERFACE.setRegistry("PlexServerManager", '')

    def isValidForTranscoding(self, server):
        return server and server.activeConnection and server.owned and not server.synced and not server.isSecondary()

    def getChannelServer(self):
        if not self.channelServer or not self.channelServer.isReachable():
            self.channelServer = None

            # Attempt to find a server that supports channels and transcoding
            for s in self.getServers():
                if s.supportsVideoTranscoding and s.allowChannelAccess and s.isReachable() and self.compareServers(self.channelServer, s) < 0:
                    self.channelServer = s

            # Fallback to any server that supports channels
            if not self.channelServer:
                for s in self.getServers():
                    if s.allowChannelAccess and s.isReachable() and self.compareServers(self.channelServer, s) < 0:
                        self.channelServer = s

            if self.channelServer:
                util.LOG("Setting channel server to {0}".format(self.channelServer))

        return self.channelServer

    def getTranscodeServer(self, transcodeType=None):
        if not self.selectedServer:
            return None

        transcodeMap = {
            'audio': "supportsAudioTranscoding",
            'video': "supportsVideoTranscoding",
            'photo': "supportsPhotoTranscoding"
        }
        transcodeSupport = transcodeMap[transcodeType]

        # Try to use a better transcoding server for synced or secondary servers
        if self.selectedServer.synced or self.selectedServer.isSecondary():
            if self.transcodeServer and self.transcodeServer.isReachable():
                return self.transcodeServer

            self.transcodeServer = None
            for server in self.getServers():
                if not server.synced and server.isReachable() and self.compareServers(self.transcodeServer, server) < 0:
                    if not transcodeSupport or server.transcodeSupport:
                        self.transcodeServer = server

            if self.transcodeServer:
                transcodeTypeString = transcodeType or ''
                util.LOG("Found a better {0} transcode server than {1}, using: {2}".format(transcodeTypeString, self.selectedserver, self.transcodeServer))
                return self.transcodeServer

        return self.selectedServer

    def startSelectedServerSearch(self, reset=False):
        if reset:
            self.selectedServer = None
            self.transcodeServer = None
            self.channelServer = None

        # Keep track of some information during our search
        self.searchContext = SearchContext({
            'bestServer': None,
            'preferredServer': plexapp.INTERFACE.getPreference('lastServerId', ''),
            'waitingForResources': plexapp.ACCOUNT.isSignedIn
        })

        util.LOG("Starting selected server search, hoping for {0}".format(self.searchContext.preferredServer))

    def onAccountChange(self, account, reallyChanged=False):
        # Clear any AudioPlayer data before invalidating the active server
        if reallyChanged:
            # AudioPlayer().Cleanup()
            # PhotoPlayer().Cleanup()

            # Clear selected and transcode servers on user change
            self.selectedServer = None
            self.transcodeServer = None
            self.channelServer = None
            self.cancelReachability()

        if account.isSignedIn:
            # If the user didn't really change, such as selecting the previous user
            # on the lock screen, then we don't need to clear anything. We can
            # avoid a costly round of reachability checks.

            if not reallyChanged:
                return

            # A request to refresh resources has already been kicked off. We need
            # to clear out any connections for the previous user and then start
            # our selected server search.

            self.updateFromConnectionType([], plexresource.ResourceConnection.SOURCE_MYPLEX)
            self.updateFromConnectionType([], plexresource.ResourceConnection.SOURCE_DISCOVERED)
            self.updateFromConnectionType([], plexresource.ResourceConnection.SOURCE_MANUAL)

            self.startSelectedServerSearch(True)
        else:
            # Clear servers/connections from plex.tv
            self.updateFromConnectionType([], plexresource.ResourceConnection.SOURCE_MYPLEX)

    def deferUpdateReachability(self, addTimer=True, logInfo=True):
        if addTimer and not self.deferReachabilityTimer:
            self.deferReachabilityTimer = plexapp.createTimer(1000, callback.Callable(self.onDeferUpdateReachabilityTimer), repeat=True)
            plexapp.APP.addTimer(self.deferReachabilityTimer)
        else:
            if self.deferReachabilityTimer:
                self.deferReachabilityTimer.reset()

        if self.deferReachabilityTimer and logInfo:
            util.LOG('Defer update reachability for all devices a few seconds: GDMactive={0}'.format(gdm.DISCOVERY.isActive()))

    def onDeferUpdateReachabilityTimer(self):
        if not self.selectedServer and self.searchContext:
            for server in self.getServers():
                if server.pendingReachabilityRequests > 0 and server.uuid == self.searchContext.preferredServer:
                    util.DEBUG_LOG(
                        'Still waiting on {0} responses from preferred server: {1}'.format(
                            server.pendingReachabilityRequests, self.searchContext.preferredServer
                        )
                    )
                    return

        self.deferReachabilityTimer.cancel()
        self.deferReachabilityTimer = None
        self.updateReachability(True, False, False)

    def resetLastTest(self):
        for uuid in self.serversByUuid:
            self.serversByUuid[uuid].resetLastTest()

    def clearServers(self):
        self.cancelReachability()
        self.serversByUuid = {}
        self.saveState()

    def onSecurityChange(self, value=None):
        # If the security policy changes, then we will need to allow all
        # connections to be retested by resetting the last test. We can
        # simply call `self.resetLastTest()` to allow all connection to be
        # tested when the server dropdown is enable, but we may as well
        # test all the connections immediately.

        plexapp.refreshResources(True)

    def onManualConnectionChange(self, value=None):
        # Clear all manual connections on change. We will keep the selected
        # server around temporarily if it's a manual connection regardless
        # if it's been removed.

        # Remember the current server in case it's removed
        server = self.getSelectedServer()
        activeConn = []
        if server and server.activeConnection:
            activeConn.append(server.activeConnection)

        # Clear all manual connections
        self.updateFromConnectionType([], plexresource.ResourceConnection.SOURCE_MANUAL)

        # Reused the previous selected server if our manual connection has gone away
        if not self.getSelectedServer() and activeConn.sources == plexresource.ResourceConnection.SOURCE_MANUAL:
            server.activeConnection = activeConn
            server.connections.append(activeConn)
            self.setSelectedServer(server, True)

    def refreshManualConnections(self):
        manualConnections = self.getManualConnections()
        if not manualConnections:
            return

        util.LOG("Refreshing {0} manual connections".format(len(manualConnections)))

        for conn in manualConnections:
            # Default to http, as the server will need to be signed in for https to work,
            # so the client should too. We'd also have to allow hostname entry, instead of
            # IP address for the cert to validate.

            proto = "http"
            port = conn.port or "32400"
            serverAddress = "{0}://{1}:{2}".format(proto, conn.connection, port)

            request = http.HttpRequest(serverAddress + "/identity")
            context = request.createRequestContext("manual_connections", callback.Callable(self.onManualConnectionsResponse))
            context.serverAddress = serverAddress
            context.address = conn.connection
            context.proto = proto
            context.port = port
            plexapp.APP.startRequest(request, context)

    def onManualConnectionsResponse(self, request, response, context):
        if not response.isSuccess():
            return

        data = response.getBodyXml()
        if data is not None:
            serverAddress = context.serverAddress
            util.DEBUG_LOG("Received manual connection response for {0}".format(serverAddress))

            machineID = data.attrib.get('machineIdentifier')
            name = context.address
            if not name or not machineID:
                return

            # TODO(rob): Do we NOT want to consider manual connections local?
            conn = plexconnection.PlexConnection(plexresource.ResourceConnection.SOURCE_MANUAL, serverAddress, True, None)
            server = plexserver.createPlexServerForConnection(conn)
            server.uuid = machineID
            server.name = name
            server.sourceType = plexresource.ResourceConnection.SOURCE_MANUAL
            self.updateFromConnectionType([server], plexresource.ResourceConnection.SOURCE_MANUAL)

    def getManualConnections(self):
        manualConnections = []

        jstring = plexapp.INTERFACE.getPreference('manual_connections')
        if jstring:
            connections = json.loads(jstring)
            if isinstance(connections, list):
                for conn in connections:
                    conn = util.AttributeDict(conn)
                    if conn.connection:
                        manualConnections.append(conn)

        return manualConnections

# TODO(schuyler): Notifications
# TODO(schuyler): Transcode (and primary) server selection


MANAGER = PlexServerManager()
