import random

import http
import plexapp
import callback
import util


class ConnectionSource(int):
    def init(self, name):
        self.name = name
        return self

    def __repr__(self):
        return self.name


class PlexConnection(object):
    # Constants
    STATE_UNKNOWN = "unknown"
    STATE_UNREACHABLE = "unreachable"
    STATE_REACHABLE = "reachable"
    STATE_UNAUTHORIZED = "unauthorized"
    STATE_INSECURE = "insecure_untested"

    SOURCE_MANUAL = ConnectionSource(1).init('MANUAL')
    SOURCE_DISCOVERED = ConnectionSource(2).init('DISCOVERED')
    SOURCE_MANUAL_AND_DISCOVERED = ConnectionSource(3).init('MANUAL, DISCOVERED')
    SOURCE_MYPLEX = ConnectionSource(4).init('MYPLEX')
    SOURCE_MANUAL_AND_MYPLEX = ConnectionSource(5).init('MANUAL, MYPLEX')
    SOURCE_DISCOVERED_AND_MYPLEX = ConnectionSource(6).init('DISCOVERED, MYPLEX')
    SOURCE_ALL = ConnectionSource(7).init('ALL')

    SCORE_REACHABLE = 4
    SCORE_LOCAL = 2
    SCORE_SECURE = 1

    SOURCE_BY_VAL = {
        1: SOURCE_MANUAL,
        2: SOURCE_DISCOVERED,
        3: SOURCE_MANUAL_AND_DISCOVERED,
        4: SOURCE_MYPLEX,
        5: SOURCE_MANUAL_AND_MYPLEX,
        6: SOURCE_DISCOVERED_AND_MYPLEX,
        7: SOURCE_ALL
    }

    def __init__(self, source, address, isLocal, token, isFallback=False):
        self.state = self.STATE_UNKNOWN
        self.sources = source
        self.address = address
        self.isLocal = isLocal
        self.isSecure = address[:5] == 'https'
        self.isFallback = isFallback
        self.token = token
        self.refreshed = True
        self.score = 0
        self.request = None

        self.lastTestedAt = 0
        self.hasPendingRequest = False

        self.getScore(True)

    def __eq__(self, other):
        if not other:
            return False
        if self.__class__ != other.__class__:
            return False
        return self.address == other.address

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return "Connection: {0} local: {1} token: {2} sources: {3} state: {4}".format(
            self.address,
            self.isLocal,
            util.hideToken(self.token),
            repr(self.sources),
            self.state
        )

    def __repr__(self):
        return self.__str__()

    def merge(self, other):
        # plex.tv trumps all, otherwise assume newer is better
        # ROKU: if (other.sources and self.SOURCE_MYPLEX) <> 0 then
        if other.sources == self.SOURCE_MYPLEX:
            self.token = other.token
        else:
            self.token = self.token or other.token

        self.address = other.address
        self.sources = self.SOURCE_BY_VAL[self.sources | other.sources]
        self.isLocal = self.isLocal | other.isLocal
        self.isSecure = other.isSecure
        self.isFallback = self.isFallback or other.isFallback
        self.refreshed = True

        self.getScore(True)

    def testReachability(self, server, allowFallback=False):
        # Check if we will allow the connection test. If this is a fallback connection,
        # then we will defer it until we "allowFallback" (test insecure connections
        # after secure tests have completed and failed). Insecure connections will be
        # tested if the policy "always" allows them, or if set to "same_network" and
        # the current connection is local and server has (publicAddressMatches=1).

        allowConnectionTest = not self.isFallback
        if not allowConnectionTest:
            insecurePolicy = plexapp.INTERFACE.getPreference("allow_insecure")
            if insecurePolicy == "always" or (insecurePolicy == "same_network" and server.sameNetwork and self.isLocal):
                allowConnectionTest = allowFallback
                server.hasFallback = not allowConnectionTest
                util.LOG(
                    '{0} for {1}'.format(
                        allowConnectionTest and "Continuing with insecure connection testing" or "Insecure connection testing is deferred", server
                    )
                )
            else:
                util.LOG("Insecure connections not allowed. Ignore insecure connection test for {0}".format(server))
                self.state = self.STATE_INSECURE
                callable = callback.Callable(server.onReachabilityResult, [self], random.randint(0, 256))
                callable.deferCall()
                return True

        if allowConnectionTest:
            if not self.isSecure and (
                not allowFallback and
                server.hasSecureConnections() or
                server.activeConnection and
                server.activeConnection.state != self.STATE_REACHABLE and
                server.activeConnection.isSecure
            ):
                util.DEBUG_LOG("Invalid insecure connection test in progress")
            self.request = http.HttpRequest(self.buildUrl(server, "/"))
            context = self.request.createRequestContext("reachability", callback.Callable(self.onReachabilityResponse))
            context.server = server
            util.addPlexHeaders(self.request, server.getToken())
            self.hasPendingRequest = plexapp.APP.startRequest(self.request, context)
            return True

        return False

    def cancelReachability(self):
        if self.request:
            self.request.ignoreResponse = True
            self.request.cancel()

    def onReachabilityResponse(self, request, response, context):
        self.hasPendingRequest = False
        # It's possible we may have a result pending before we were able
        # to cancel it, so we'll just ignore it.

        # if request.ignoreResponse:
        #     return

        if response.isSuccess():
            data = response.getBodyXml()
            if data is not None and context.server.collectDataFromRoot(data):
                self.state = self.STATE_REACHABLE
            else:
                # This is unexpected, but treat it as unreachable
                util.ERROR_LOG("Unable to parse root response from {0}".format(context.server))
                self.state = self.STATE_UNREACHABLE
        elif response.getStatus() == 401:
            self.state = self.STATE_UNAUTHORIZED
        else:
            self.state = self.STATE_UNREACHABLE

        self.getScore(True)

        context.server.onReachabilityResult(self)

    def buildUrl(self, server, path, includeToken=False):
        if '://' in path:
            url = path
        else:
            url = self.address + path

        if includeToken:
            # If we have a token, use it. Otherwise see if any other connections
            # for this server have one. That will let us use a plex.tv token for
            # something like a manually configured connection.

            token = self.token or server.getToken()

            if token:
                url = http.addUrlParam(url, "X-Plex-Token=" + token)

        return url

    def simpleBuildUrl(self, server, path):
        token = (self.token or server.getToken())
        param = ''
        if token:
            param = '&X-Plex-Token={0}'.format(token)

        return '{0}{1}{2}'.format(self.address, path, param)

    def getScore(self, recalc=False):
        if recalc:
            self.score = 0
            if self.state == self.STATE_REACHABLE:
                self.score += self.SCORE_REACHABLE
            if self.isSecure:
                self.score += self.SCORE_SECURE
            if self.isLocal:
                self.score += self.SCORE_LOCAL

        return self.score
