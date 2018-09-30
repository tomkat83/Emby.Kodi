from defusedxml import ElementTree
import urllib

import plexapp
import plexconnection
import plexserver
import myplexrequest
import callback
import util


class MyPlexManager(object):
    def publish(self):
        util.LOG('MyPlexManager().publish() - NOT IMPLEMENTED')
        return  # TODO: ----------------------------------------------------------------------------------------------------------------------------- IMPLEMENT?
        request = myplexrequest.MyPlexRequest("/devices/" + plexapp.INTERFACE.getGlobal("clientIdentifier"))
        context = request.createRequestContext("publish")

        addrs = plexapp.INTERFACE.getGlobal("roDeviceInfo").getIPAddrs()

        for iface in addrs:
            request.addParam(urllib.quote("Connection[][uri]"), "http://{0):8324".format(addrs[iface]))

        plexapp.APP.startRequest(request, context, "_method=PUT")

    def refreshResources(self, force=False):
        if force:
            plexapp.SERVERMANAGER.resetLastTest()

        request = myplexrequest.MyPlexRequest("/pms/resources")
        context = request.createRequestContext("resources", callback.Callable(self.onResourcesResponse))

        if plexapp.ACCOUNT.isSecure:
            request.addParam("includeHttps", "1")

        plexapp.APP.startRequest(request, context)

    def onResourcesResponse(self, request, response, context):
        servers = []

        response.parseResponse()

        # Save the last successful response to cache
        if response.isSuccess() and response.event:
            plexapp.INTERFACE.setRegistry("mpaResources", response.event.text.encode('utf-8'), "xml_cache")
            util.DEBUG_LOG("Saved resources response to registry")
        # Load the last successful response from cache
        elif plexapp.INTERFACE.getRegistry("mpaResources", None, "xml_cache"):
            data = ElementTree.fromstring(plexapp.INTERFACE.getRegistry("mpaResources", None, "xml_cache"))
            response.parseFakeXMLResponse(data)
            util.DEBUG_LOG("Using cached resources")

        if response.container:
            for resource in response.container:
                util.DEBUG_LOG(
                    "Parsed resource from plex.tv: type:{0} clientIdentifier:{1} name:{2} product:{3} provides:{4}".format(
                        resource.type,
                        resource.clientIdentifier,
                        resource.name.encode('utf-8'),
                        resource.product.encode('utf-8'),
                        resource.provides.encode('utf-8')
                    )
                )

                for conn in resource.connections:
                    util.DEBUG_LOG('  {0}'.format(conn))

                if 'server' in resource.provides:
                    server = plexserver.createPlexServerForResource(resource)
                    util.DEBUG_LOG('  {0}'.format(server))
                    servers.append(server)

        plexapp.SERVERMANAGER.updateFromConnectionType(servers, plexconnection.PlexConnection.SOURCE_MYPLEX)


MANAGER = MyPlexManager()
