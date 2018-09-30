import threading
import socket
import traceback
import time
import util
import netif

import plexconnection

DISCOVERY_PORT = 32414
WIN_NL = chr(13) + chr(10)


class GDMDiscovery(object):
    def __init__(self):
        self._close = False
        self.thread = None

    # def isActive(self):
    #     util.LOG('GDMDiscovery().isActive() - NOT IMPLEMENTED')
    #     return False

    # def discover(self):
    #     util.LOG('GDMDiscovery().discover() - NOT IMPLEMENTED')

    def isActive(self):
        import plexapp
        return plexapp.INTERFACE.getPreference("gdm_discovery", True) and self.thread and self.thread.isAlive()

    '''
    def discover(self):
        # Only allow discovery if enabled and not currently running
        self._close = False
        import plexapp
        if not plexapp.INTERFACE.getPreference("gdm_discovery", True) or self.isActive():
            return

        ifaces = netif.getInterfaces()

        message = "M-SEARCH * HTTP/1.1" + WIN_NL + WIN_NL

        # Broadcasting to 255.255.255.255 only works on some Rokus, but we
        # can't reliably determine the broadcast address for our current
        # interface. Try assuming a /24 network, and then fall back to the
        # multicast address if that doesn't work.

        multicast = "239.0.0.250"
        ip = multicast
        subnetRegex = re.compile("((\d+)\.(\d+)\.(\d+)\.)(\d+)")
        addr = getFirstIPAddress()  # TODO:: -------------------------------------------------------------------------------------------------------- HANDLE
        if addr:
            match = subnetRegex.search(addr)
            if match:
                ip = match.group(1) + "255"
                util.DEBUG_LOG("Using broadcast address {0}".format())

        # Socket things sometimes fail for no good reason, so try a few times.
        attempt = 0
        success = False

        while attempt < 5 and not success:
            udp = CreateObject("roDatagramSocket")
            udp.setMessagePort(Application().port)
            udp.setBroadcast(true)

            # More things that have been observed to be flaky.
            for i in range(5):
                addr = CreateObject("roSocketAddress")
                addr.setHostName(ip)
                addr.setPort(32414)
                udp.setSendToAddress(addr)

                sendTo = udp.getSendToAddress()
                if sendTo:
                    sendToStr = str(sendTo.getAddress())
                    addrStr = str(addr.getAddress())
                    util.DEBUG_LOG("GDM sendto address: " + sendToStr + " / " + addrStr)
                    if sendToStr == addrStr:
                        break

                util.ERROR_LOG("Failed to set GDM sendto address")

            udp.notifyReadable(true)
            bytesSent = udp.sendStr(message)
            util.DEBUG_LOG("Sent " + str(bytesSent) + " bytes")
            if bytesSent > 0:
                success = udp.eOK()
            else:
                success = False
                if bytesSent == 0 and ip != multicast:
                    util.LOG("Falling back to multicast address")
                    ip = multicast
                    attempt = 0

            if success:
                break
            elif attempt == 4 and ip != multicast:
                util.LOG("Falling back to multicast address")
                ip = multicast
                attempt = 0
            else:
                time.sleep(500)
                util.WARN_LOG("Retrying GDM, errno=" + str(udp.status()))
                attempt += 1

        if success:
            util.DEBUG_LOG("Successfully sent GDM discovery message, waiting for servers")
            self.servers = []
            self.timer = plexapp.createTimer(5000, self.onTimer)
            self.socket = udp
            Application().AddSocketCallback(udp, createCallable("OnSocketEvent", m))
            plexapp.APP.addTimer(self.timer)
        else:
            util.ERROR_LOG("Failed to send GDM discovery message")
            import plexapp
            import plexresource
            plexapp.SERVERMANAGER.UpdateFromConnectionType([], plexresource.ResourceConnection.SOURCE_DISCOVERED)
            self.socket = None
            self.timer = None
    '''

    def discover(self):
        import plexapp
        if not plexapp.INTERFACE.getPreference("gdm_discovery", True) or self.isActive():
            return

        self.thread = threading.Thread(target=self._discover)
        self.thread.start()

    def _discover(self):
        ifaces = netif.getInterfaces()
        sockets = []
        self.servers = []

        packet = "M-SEARCH * HTTP/1.1" + WIN_NL + WIN_NL

        for i in ifaces:
            if not i.broadcast:
                continue
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.01)  # 10ms
            s.bind((i.ip, 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sockets.append((s, i))

        success = False

        for attempt in (0, 1):
            for s, i in sockets:
                if self._close:
                    return
                util.DEBUG_LOG('  o-> Broadcasting to {0}: {1}'.format(i.name, i.broadcast))
                try:
                    s.sendto(packet, (i.broadcast, DISCOVERY_PORT))
                    success = True
                except:
                    util.ERROR()

            if success:
                break

        end = time.time() + 5

        while time.time() < end:
            for s, i in sockets:
                if self._close:
                    return
                try:
                    message, address = s.recvfrom(4096)
                    self.onSocketEvent(message, address)
                except socket.timeout:
                    pass
                except:
                    traceback.print_exc()

        self.discoveryFinished()

    def onSocketEvent(self, message, addr):
        util.DEBUG_LOG('Received GDM message:\n' + str(message))

        hostname = addr[0]  # socket.gethostbyaddr(addr[0])[0]

        name = parseFieldValue(message, "Name: ")
        port = parseFieldValue(message, "Port: ") or "32400"
        machineID = parseFieldValue(message, "Resource-Identifier: ")
        secureHost = parseFieldValue(message, "Host: ")

        util.DEBUG_LOG("Received GDM response for " + repr(name) + " at http://" + hostname + ":" + port)

        if not name or not machineID:
            return

        import plexserver
        conn = plexconnection.PlexConnection(plexconnection.PlexConnection.SOURCE_DISCOVERED, "http://" + hostname + ":" + port, True, None, bool(secureHost))
        server = plexserver.createPlexServerForConnection(conn)
        server.uuid = machineID
        server.name = name
        server.sameNetwork = True

        # If the server advertised a secure hostname, add a secure connection as well, and
        # set the http connection as a fallback.
        #
        if secureHost:
            server.connections.insert(
                0,
                plexconnection.PlexConnection(
                    plexconnection.PlexConnection.SOURCE_DISCOVERED, "https://" + hostname.replace(".", "-") + "." + secureHost + ":" + port, True, None
                )
            )

        self.servers.append(server)

    def discoveryFinished(self, *args, **kwargs):
        # Time's up, report whatever we found
        self.close()

        if self.servers:
            util.LOG("Finished GDM discovery, found {0} server(s)".format(len(self.servers)))
            import plexapp
            plexapp.SERVERMANAGER.updateFromConnectionType(self.servers, plexconnection.PlexConnection.SOURCE_DISCOVERED)
            self.servers = None

    def close(self):
        self._close = True


def parseFieldValue(message, label):
    if label not in message:
        return None

    return message.split(label, 1)[-1].split(chr(13))[0]


DISCOVERY = GDMDiscovery()

'''
# GDM Advertising

class GDMAdvertiser(object):

    def __init__(self):
            self.responseString = None

    def createSocket()
        listenAddr = CreateObject("roSocketAddress")
        listenAddr.setPort(32412)
        listenAddr.setAddress("0.0.0.0")

        udp = CreateObject("roDatagramSocket")

        if not udp.setAddress(listenAddr) then
            Error("Failed to set address on GDM advertiser socket")
            return
        end if

        if not udp.setBroadcast(true) then
            Error("Failed to set broadcast on GDM advertiser socket")
            return
        end if

        udp.notifyReadable(true)
        udp.setMessagePort(Application().port)

        m.socket = udp

        Application().AddSocketCallback(udp, createCallable("OnSocketEvent", m))

        Debug("Created GDM player advertiser")


    def refresh()
        # Always regenerate our response, even if it might not have changed, it's
        # just not that expensive.
        m.responseString = invalid

        enabled = AppSettings().GetBoolPreference("remotecontrol")
        if enabled AND m.socket = invalid then
            m.CreateSocket()
        else if not enabled AND m.socket <> invalid then
            m.Close()
        end if


    def cleanup()
        m.Close()
        fn = function() :m.GDMAdvertiser = invalid :
        fn()


    def onSocketEvent(msg as object)
        # PMS polls every five seconds, so this is chatty when not debugging.
        # Debug("Got a GDM advertiser socket event, is readable: " + tostr(m.socket.isReadable()))

        if m.socket.isReadable() then
            message = m.socket.receiveStr(4096)
            endIndex = instr(1, message, chr(13)) - 1
            if endIndex <= 0 then endIndex = message.Len()
            line = Mid(message, 1, endIndex)

            if line = "M-SEARCH * HTTP/1.1" then
                response = m.GetResponseString()

                # Respond directly to whoever sent the search message.
                sock = CreateObject("roDatagramSocket")
                sock.setSendToAddress(m.socket.getReceivedFromAddress())
                bytesSent = sock.sendStr(response)
                sock.Close()
                if bytesSent <> Len(response) then
                    Error("GDM player response only sent " + tostr(bytesSent) + " bytes out of " + tostr(Len(response)))
                end if
            else
                Error("Received unexpected message on GDM advertiser socket: " + tostr(line) + ";")
            end if
        end if


    def getResponseString() as string
        if m.responseString = invalid then
            buf = box("HTTP/1.0 200 OK" + WinNL())

            settings = AppSettings()

            appendNameValue(buf, "Name", settings.GetGlobal("friendlyName"))
            appendNameValue(buf, "Port", WebServer().port.tostr())
            appendNameValue(buf, "Product", "Plex for Roku")
            appendNameValue(buf, "Content-Type", "plex/media-player")
            appendNameValue(buf, "Protocol", "plex")
            appendNameValue(buf, "Protocol-Version", "1")
            appendNameValue(buf, "Protocol-Capabilities", "timeline,playback,navigation,playqueues")
            appendNameValue(buf, "Version", settings.GetGlobal("appVersionStr"))
            appendNameValue(buf, "Resource-Identifier", settings.GetGlobal("clientIdentifier"))
            appendNameValue(buf, "Device-Class", "stb")

            m.responseString = buf

            Debug("Built GDM player response:" + m.responseString)
        end if

        return m.responseString


    sub appendNameValue(buf, name, value)
        line = name + ": " + value + WinNL()
        buf.AppendString(line, Len(line))

'''
