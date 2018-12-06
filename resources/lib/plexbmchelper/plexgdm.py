#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PlexGDM.py - Version 0.2

This class implements the Plex GDM (G'Day Mate) protocol to discover
local Plex Media Servers.  Also allow client registration into all local
media servers.


This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
MA 02110-1301, USA.
"""
from __future__ import absolute_import, division, unicode_literals
import logging
import socket
import threading
import time
from xbmc import sleep

from ..downloadutils import DownloadUtils as DU
from .. import utils
from .. import variables as v

###############################################################################

log = logging.getLogger('PLEX.plexgdm')

###############################################################################


class plexgdm:

    def __init__(self):
        self.discover_message = 'M-SEARCH * HTTP/1.0'
        self.client_header = '* HTTP/1.0'
        self.client_data = None

        self._multicast_address = '239.0.0.250'
        self.discover_group = (self._multicast_address, 32414)
        self.client_register_group = (self._multicast_address, 32413)
        self.client_update_port = int(utils.settings('companionUpdatePort'))

        self.server_list = []
        self.discovery_interval = 120

        self._discovery_is_running = False
        self._registration_is_running = False

        self.client_registered = False
        self.download = DU().downloadUrl

    def clientDetails(self):
        self.client_data = (
            "Content-Type: plex/media-player\n"
            "Resource-Identifier: %s\n"
            "Name: %s\n"
            "Port: %s\n"
            "Product: %s\n"
            "Version: %s\n"
            "Protocol: plex\n"
            "Protocol-Version: 1\n"
            "Protocol-Capabilities: timeline,playback,navigation,"
            "playqueues\n"
            "Device-Class: HTPC\n"
        ) % (
            v.PKC_MACHINE_IDENTIFIER,
            v.DEVICENAME,
            v.COMPANION_PORT,
            v.ADDON_NAME,
            v.ADDON_VERSION
        )

    def getClientDetails(self):
        return self.client_data

    def register_as_client(self):
        """
        Registers PKC's Plex Companion to the PMS
        """
        try:
            log.debug("Sending registration data: HELLO %s\n%s"
                      % (self.client_header, self.client_data))
            self.update_sock.sendto("HELLO %s\n%s"
                                    % (self.client_header, self.client_data),
                                    self.client_register_group)
            log.debug('(Re-)registering PKC Plex Companion successful')
        except:
            log.error("Unable to send registration message")

    def client_update(self):
        self.update_sock = socket.socket(socket.AF_INET,
                                         socket.SOCK_DGRAM,
                                         socket.IPPROTO_UDP)
        update_sock = self.update_sock

        # Set socket reuse, may not work on all OSs.
        try:
            update_sock.setsockopt(socket.SOL_SOCKET,
                                   socket.SO_REUSEADDR,
                                   1)
        except:
            pass

        # Attempt to bind to the socket to recieve and send data.  If we cant
        # do this, then we cannot send registration
        try:
            update_sock.bind(('0.0.0.0', self.client_update_port))
        except:
            log.error("Unable to bind to port [%s] - Plex Companion will not "
                      "be registered. Change the Plex Companion update port!"
                      % self.client_update_port)
            if utils.settings('companion_show_gdm_port_warning') == 'true':
                from .windows import optionsdialog
                # Plex Companion could not open the GDM port. Please change it
                # in the PKC settings.
                if optionsdialog.show(utils.lang(29999),
                                      'Port %s\n%s' % (self.client_update_port,
                                                       utils.lang(39079)),
                                      utils.lang(30013),  # Never show again
                                      utils.lang(186)) == 0:
                    utils.settings('companion_show_gdm_port_warning',
                                   value='false')
                from xbmc import executebuiltin
                executebuiltin(
                    'Addon.OpenSettings(plugin.video.plexkodiconnect)')
            return

        update_sock.setsockopt(socket.IPPROTO_IP,
                               socket.IP_MULTICAST_TTL,
                               255)
        update_sock.setsockopt(socket.IPPROTO_IP,
                               socket.IP_ADD_MEMBERSHIP,
                               socket.inet_aton(
                                   self._multicast_address) +
                               socket.inet_aton('0.0.0.0'))
        update_sock.setblocking(0)

        # Send initial client registration
        self.register_as_client()

        # Now, listen format client discovery reguests and respond.
        while self._registration_is_running:
            try:
                data, addr = update_sock.recvfrom(1024)
                log.debug("Recieved UDP packet from [%s] containing [%s]"
                          % (addr, data.strip()))
            except socket.error:
                pass
            else:
                if "M-SEARCH * HTTP/1." in data:
                    log.debug("Detected client discovery request from %s. "
                              " Replying" % str(addr))
                    try:
                        update_sock.sendto("HTTP/1.0 200 OK\n%s"
                                           % self.client_data,
                                           addr)
                    except:
                        log.error("Unable to send client update message")

                    log.debug("Sending registration data HTTP/1.0 200 OK")
                    self.client_registered = True
            sleep(500)
        log.info("Client Update loop stopped")
        # When we are finished, then send a final goodbye message to
        # deregister cleanly.
        log.debug("Sending registration data: BYE %s\n%s"
                  % (self.client_header, self.client_data))
        try:
            update_sock.sendto("BYE %s\n%s"
                               % (self.client_header, self.client_data),
                               self.client_register_group)
        except:
            log.error("Unable to send client update message")
        self.client_registered = False

    def check_client_registration(self):
        if not self.client_registered:
            log.debug('Client has not been marked as registered')
            return False
        if not self.server_list:
            log.info("Server list is empty. Unable to check")
            return False
        for server in self.server_list:
            if server['uuid'] == utils.window('plex_machineIdentifier'):
                media_server = server['server']
                media_port = server['port']
                scheme = server['protocol']
                break
        else:
            log.info("Did not find our server!")
            return False

        log.debug("Checking server [%s] on port [%s]"
                  % (media_server, media_port))
        xml = self.download(
            '%s://%s:%s/clients' % (scheme, media_server, media_port))
        try:
            xml[0].attrib
        except (TypeError, IndexError, AttributeError):
            log.error('Could not download clients for %s' % media_server)
            return False
        registered = False
        for client in xml:
            if (client.attrib.get('machineIdentifier') ==
                    v.PKC_MACHINE_IDENTIFIER):
                registered = True
        if registered:
            return True
        else:
            log.info("Client registration not found. "
                     "Client data is: %s" % xml)
        return False

    def getServerList(self):
        return self.server_list

    def discover(self):
        currServer = utils.window('pms_server')
        if not currServer:
            return
        currServerProt, currServerIP, currServerPort = \
            currServer.split(':')
        currServerIP = currServerIP.replace('/', '')
        # Currently active server was not discovered via GDM; ADD
        self.server_list = [{
            'port': currServerPort,
            'protocol': currServerProt,
            'class': None,
            'content-type': 'plex/media-server',
            'discovery': 'auto',
            'master': 1,
            'owned': '1',
            'role': 'master',
            'server': currServerIP,
            'serverName': utils.window('plex_servername'),
            'updated': int(time.time()),
            'uuid': utils.window('plex_machineIdentifier'),
            'version': 'irrelevant'
        }]

    def setInterval(self, interval):
        self.discovery_interval = interval

    def stop_all(self):
        self.stop_discovery()
        self.stop_registration()

    def stop_discovery(self):
        if self._discovery_is_running:
            log.info("Discovery shutting down")
            self._discovery_is_running = False
            self.discover_t.join()
            del self.discover_t
        else:
            log.info("Discovery not running")

    def stop_registration(self):
        if self._registration_is_running:
            log.info("Registration shutting down")
            self._registration_is_running = False
            self.register_t.join()
            del self.register_t
        else:
            log.info("Registration not running")

    def run_discovery_loop(self):
        # Run initial discovery
        self.discover()

        discovery_count = 0
        while self._discovery_is_running:
            discovery_count += 1
            if discovery_count > self.discovery_interval:
                self.discover()
                discovery_count = 0
            sleep(500)

    def start_discovery(self, daemon=False):
        if not self._discovery_is_running:
            log.info("Discovery starting up")
            self._discovery_is_running = True
            self.discover_t = threading.Thread(target=self.run_discovery_loop)
            self.discover_t.setDaemon(daemon)
            self.discover_t.start()
        else:
            log.info("Discovery already running")

    def start_registration(self, daemon=False):
        if not self._registration_is_running:
            log.info("Registration starting up")
            self._registration_is_running = True
            self.register_t = threading.Thread(target=self.client_update)
            self.register_t.setDaemon(daemon)
            self.register_t.start()
        else:
            log.info("Registration already running")

    def start_all(self, daemon=False):
        self.start_discovery(daemon)
        if utils.settings('plexCompanion') == 'true':
            self.start_registration(daemon)
