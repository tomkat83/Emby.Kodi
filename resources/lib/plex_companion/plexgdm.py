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
import logging
import socket

from ..downloadutils import DownloadUtils as DU
from .. import backgroundthread
from .. import utils, app, variables as v

log = logging.getLogger('PLEX.plexgdm')


class plexgdm(backgroundthread.KillableThread):
    daemon = True

    def __init__(self):
        client = (
            'Content-Type: plex/media-player\n'
            f'Resource-Identifier: {v.PKC_MACHINE_IDENTIFIER}\n'
            f'Name: {v.DEVICENAME}\n'
            f'Port: {v.COMPANION_PORT}\n'
            f'Product: {v.ADDON_NAME}\n'
            f'Version: {v.ADDON_VERSION}\n'
            'Protocol: plex\n'
            'Protocol-Version: 3\n'
            'Protocol-Capabilities: timeline,playback,navigation,playqueues\n'
            'Device-Class: pc\n'
        )
        self.hello_msg = f'HELLO * HTTP/1.0\n{client}'.encode()
        self.ok_msg = f'HTTP/1.0 200 OK\n{client}'.encode()
        self.bye_msg = f'BYE * HTTP/1.0\n{client}'.encode()

        self.socket = None
        self.port = int(utils.settings('companionUpdatePort'))
        self.multicast_address = '239.0.0.250'
        self.client_register_group = (self.multicast_address, 32413)

        super().__init__()

    def on_bind_error(self):
        self.socket = None
        log.error('Unable to bind to port [%s] - Plex Companion will not '
                  'be registered. Change the Plex Companion update port!'
                  % self.port)
        if utils.settings('companion_show_gdm_port_warning') == 'true':
            from ..windows import optionsdialog
            # Plex Companion could not open the GDM port. Please change it
            # in the PKC settings.
            if optionsdialog.show(utils.lang(29999),
                                  'Port %s\n%s' % (self.port,
                                                   utils.lang(39079)),
                                  utils.lang(30013),  # Never show again
                                  utils.lang(186)) == 0:
                utils.settings('companion_show_gdm_port_warning',
                               value='false')
            from xbmc import executebuiltin
            executebuiltin(
                'Addon.OpenSettings(plugin.video.plexkodiconnect)')

    def register_as_client(self):
        '''
        Registers PKC's Plex Companion to the PMS
        '''
        log.debug('Sending registration data: HELLO')
        try:
            self.socket.sendto(self.hello_msg, self.client_register_group)
        except Exception as exc:
            log.error('Unable to send registration message. Error: %s', exc)

    def check_client_registration(self):
        """
        Checks whetere we are registered as a Plex Companion casting target
        (using the old "GDM method") on our PMS. If not, registers
        """
        if self.socket is None:
            return
        log.debug('Checking whether we are still listed as GDM Plex Companion'
                  'client on our PMS')
        xml = DU().downloadUrl('{server}/clients')
        try:
            xml[0].attrib
        except (TypeError, IndexError, AttributeError):
            log.error('Could not download GDM Plex Companion clients')
            return False
        for client in xml:
            if (client.attrib.get('machineIdentifier') == v.PKC_MACHINE_IDENTIFIER):
                break
        else:
            log.info('PKC not registered as a GDM Plex Companion client')
            self.register_as_client()

    def setup_socket(self):
        self.socket = socket.socket(socket.AF_INET,
                                    socket.SOCK_DGRAM,
                                    socket.IPPROTO_UDP)
        # Set socket reuse, may not work on all OSs.
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        # Attempt to bind to the socket to recieve and send data.  If we cant
        # do this, then we cannot send registration
        try:
            self.socket.bind(('0.0.0.0', self.port))
        except Exception:
            self.on_bind_error()
            return False
        self.socket.setsockopt(socket.IPPROTO_IP,
                               socket.IP_MULTICAST_TTL,
                               255)
        self.socket.setsockopt(socket.IPPROTO_IP,
                               socket.IP_ADD_MEMBERSHIP,
                               socket.inet_aton(self.multicast_address) + socket.inet_aton('0.0.0.0'))
        self.socket.setblocking(0)
        return True

    def teardown_socket(self):
        '''
        When we are finished, then send a final goodbye message to deregister
        cleanly.
        '''
        if self.socket is None:
            return
        log.debug('Sending goodbye: BYE')
        try:
            self.socket.sendto(self.bye_msg, self.client_register_group)
        except Exception:
            log.error('Unable to send client goodbye message')
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            # The server might already have closed the connection. On Windows,
            # this may result in WSAEINVAL (error 10022): An invalid operation
            # was attempted.
            pass
        finally:
            self.socket.close()
            self.socket = None

    def reply(self, addr):
        log.debug('Detected client discovery request from %s. Replying', addr)
        try:
            self.socket.sendto(self.ok_msg, addr)
        except Exception as error:
            log.error('Unable to send client update message to %s', addr)
            log.error('Error encountered: %s: %s', type(error), error)

    def wait_while_suspended(self):
        should_shutdown = super().wait_while_suspended()
        if not should_shutdown and not self.setup_socket():
            raise RuntimeError('Could not bind socket to port %s' % self.port)
        return should_shutdown

    def run(self):
        if not utils.settings('plexCompanion') == 'true':
            return
        log.info('----===## Starting PlexGDM client ##===----')
        app.APP.register_thread(self)
        try:
            self._run()
        finally:
            self.teardown_socket()
            app.APP.deregister_thread(self)
            log.info('----===## Stopping PlexGDM client ##===----')

    def _run(self):
        if not self.setup_socket():
            return
        # Send initial client registration
        self.register_as_client()
        # Listen for Plex Companion client discovery reguests and respond
        while not self.should_cancel():
            if self.should_suspend():
                self.teardown_socket()
                if self.wait_while_suspended():
                    break
            try:
                data, addr = self.socket.recvfrom(1024)
            except socket.error:
                pass
            else:
                data = data.decode()
                log.debug('Received UDP packet from [%s] containing [%s]'
                          % (addr, data.strip()))
                if 'M-SEARCH * HTTP/1.' in data:
                    self.reply(addr)
            self.sleep(0.5)
