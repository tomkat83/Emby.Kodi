#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Plex Companion listener
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from re import sub
from SocketServer import ThreadingMixIn
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from urlparse import urlparse, parse_qs
import xbmc

from .. import companion
from .. import json_rpc as js
from .. import clientinfo
from .. import variables as v

###############################################################################

LOG = getLogger('PLEX.listener')
PLAYER = xbmc.Player()
MONITOR = xbmc.Monitor()

# Hack we need in order to keep track of the open connections from Plex Web
CLIENT_DICT = {}

###############################################################################

RESOURCES_XML = ('%s<MediaContainer>\n'
    '  <Player'
        ' title="{title}"'
        ' protocol="plex"'
        ' protocolVersion="1"'
        ' protocolCapabilities="timeline,playback,navigation,playqueues"'
        ' machineIdentifier="{machineIdentifier}"'
        ' product="%s"'
        ' platform="%s"'
        ' platformVersion="%s"'
        ' deviceClass="pc"/>\n'
    '</MediaContainer>\n') % (v.XML_HEADER,
                              v.ADDON_NAME,
                              v.PLATFORM,
                              v.ADDON_VERSION)

class MyHandler(BaseHTTPRequestHandler):
    """
    BaseHTTPRequestHandler implementation of Plex Companion listener
    """
    protocol_version = 'HTTP/1.1'

    def __init__(self, *args, **kwargs):
        self.serverlist = []
        BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

    def do_HEAD(self):
        LOG.debug("Serving HEAD request...")
        self.answer_request(0)

    def do_GET(self):
        LOG.debug("Serving GET request...")
        self.answer_request(1)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.send_header('X-Plex-Client-Identifier', v.PKC_MACHINE_IDENTIFIER)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Connection', 'close')
        self.send_header('Access-Control-Max-Age', '1209600')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods',
                         'POST, GET, OPTIONS, DELETE, PUT, HEAD')
        self.send_header(
            'Access-Control-Allow-Headers',
            'x-plex-version, x-plex-platform-version, x-plex-username, '
            'x-plex-client-identifier, x-plex-target-client-identifier, '
            'x-plex-device-name, x-plex-platform, x-plex-product, accept, '
            'x-plex-device, x-plex-device-screen-resolution')
        self.end_headers()
        self.wfile.close()

    def sendOK(self):
        self.send_response(200)

    def response(self, body, headers=None, code=200):
        headers = {} if headers is None else headers
        try:
            self.send_response(code)
            for key in headers:
                self.send_header(key, headers[key])
            self.send_header('Content-Length', len(body))
            self.send_header('Connection', "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.close()
        except:
            pass

    def answer_request(self, send_data):
        self.serverlist = self.server.client.getServerList()
        sub_mgr = self.server.subscription_manager

        request_path = self.path[1:]
        request_path = sub(r"\?.*", "", request_path)
        url = urlparse(self.path)
        paramarrays = parse_qs(url.query)
        params = {}
        for key in paramarrays:
            params[key] = paramarrays[key][0]
        LOG.debug("remote request_path: %s", request_path)
        LOG.debug("params received from remote: %s", params)
        sub_mgr.update_command_id(self.headers.get(
                'X-Plex-Client-Identifier', self.client_address[0]),
            params.get('commandID'))
        if request_path == "version":
            self.response(
                "PlexKodiConnect Plex Companion: Running\nVersion: %s"
                % v.ADDON_VERSION)
        elif request_path == "verify":
            self.response("XBMC JSON connection test:\n" + js.ping())
        elif request_path == 'resources':
            self.response(
                RESOURCES_XML.format(
                    title=v.DEVICENAME,
                    machineIdentifier=v.PKC_MACHINE_IDENTIFIER),
                clientinfo.getXArgsDeviceInfo(include_token=False))
        elif request_path == 'player/timeline/poll':
            # Plex web does polling if connected to PKC via Companion
            # Only reply if there is indeed something playing
            # Otherwise, all clients seem to keep connection open
            if params.get('wait') == '1':
                MONITOR.waitForAbort(0.95)
            if self.client_address[0] not in CLIENT_DICT:
                CLIENT_DICT[self.client_address[0]] = []
            tracker = CLIENT_DICT[self.client_address[0]]
            tracker.append(self.client_address[1])
            while (not PLAYER.isPlaying() and
                   not MONITOR.abortRequested() and
                   sub_mgr.stop_sent_to_web and not
                   (len(tracker) >= 4 and
                    tracker[0] == self.client_address[1])):
                # Keep at most 3 connections open, then drop the first one
                # Doesn't need to be thread-save
                # Silly stuff really
                MONITOR.waitForAbort(1)
            # Let PKC know that we're releasing this connection
            tracker.pop(0)
            msg = sub_mgr.msg(js.get_players()).format(
                command_id=params.get('commandID', 0))
            if sub_mgr.isplaying:
                self.response(
                    msg,
                    {
                        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
                        'X-Plex-Protocol': '1.0',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Max-Age': '1209600',
                        'Access-Control-Expose-Headers':
                            'X-Plex-Client-Identifier',
                        'Content-Type': 'text/xml;charset=utf-8'
                    })
            elif not sub_mgr.stop_sent_to_web:
                sub_mgr.stop_sent_to_web = True
                LOG.debug('Signaling STOP to Plex Web')
                self.response(
                    msg,
                    {
                        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
                        'X-Plex-Protocol': '1.0',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Max-Age': '1209600',
                        'Access-Control-Expose-Headers':
                            'X-Plex-Client-Identifier',
                        'Content-Type': 'text/xml;charset=utf-8'
                    })
            else:
                # Fail connection with HTTP 500 error - has been open too long
                self.response(
                    'Need to close this connection on the PKC side',
                    {
                        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
                        'X-Plex-Protocol': '1.0',
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Max-Age': '1209600',
                        'Access-Control-Expose-Headers':
                            'X-Plex-Client-Identifier',
                        'Content-Type': 'text/xml;charset=utf-8'
                    },
                    code=500)
        elif "/subscribe" in request_path:
            self.response(v.COMPANION_OK_MESSAGE,
                          clientinfo.getXArgsDeviceInfo(include_token=False))
            protocol = params.get('protocol')
            host = self.client_address[0]
            port = params.get('port')
            uuid = self.headers.get('X-Plex-Client-Identifier')
            command_id = params.get('commandID', 0)
            sub_mgr.add_subscriber(protocol,
                                   host,
                                   port,
                                   uuid,
                                   command_id)
        elif "/unsubscribe" in request_path:
            self.response(v.COMPANION_OK_MESSAGE,
                          clientinfo.getXArgsDeviceInfo(include_token=False))
            uuid = self.headers.get('X-Plex-Client-Identifier') \
                or self.client_address[0]
            sub_mgr.remove_subscriber(uuid)
        else:
            # Throw it to companion.py
            companion.process_command(request_path, params)
            self.response('', clientinfo.getXArgsDeviceInfo(include_token=False))


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """
    Using ThreadingMixIn Thread magic
    """
    daemon_threads = True

    def __init__(self, client, subscription_manager, *args, **kwargs):
        """
        client: Class handle to plexgdm.plexgdm. We can thus ask for an up-to-
        date serverlist without instantiating anything

        same for SubscriptionMgr
        """
        self.client = client
        self.subscription_manager = subscription_manager
        HTTPServer.__init__(self, *args, **kwargs)
