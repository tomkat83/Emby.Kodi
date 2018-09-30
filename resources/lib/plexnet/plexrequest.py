from xml.etree import ElementTree

import plexserver
import plexresult
import http
import util


class PlexRequest(http.HttpRequest):
    def __init__(self, server, path, method=None):
        server = server or plexserver.dummyPlexServer()

        http.HttpRequest.__init__(self, server.buildUrl(path, includeToken=True), method)

        self.server = server
        self.path = path

        util.addPlexHeaders(self, server.getToken())

    def onResponse(self, event, context):
        if context.get('completionCallback'):
            result = plexresult.PlexResult(self.server, self.path)
            result.setResponse(event)
            context['completionCallback'](self, result, context)

    def doRequestWithTimeout(self, timeout=10, postBody=None):
        # non async request/response
        if postBody:
            data = ElementTree.fromstring(self.postToStringWithTimeout(postBody, timeout))
        else:
            data = ElementTree.fromstring(self.getToStringWithTimeout(timeout))

        response = plexresult.PlexResult(self.server, self.path)
        response.setResponse(self.event)
        response.parseFakeXMLResponse(data)

        return response


class PlexServerRequest(PlexRequest):
    def onResponse(self, event, context):
        if context.get('completionCallback'):
            result = plexresult.PlexServerResult(self.server, self.path)
            result.setResponse(event)
            context['completionCallback'](self, result, context)
