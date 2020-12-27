#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import secrets

from .. import utils, json_rpc as js

LOG = getLogger('PLEX.connection')


class Connection(object):
    def __init__(self, entrypoint=False):
        self.verify_ssl_cert = None
        self.ssl_cert_path = None
        self.machine_identifier = None
        self.server_name = None
        self.https = None
        self.host = None
        self.port = None
        self.server = None
        self.online = False
        self.webserver_host = None
        self.webserver_port = None
        self.webserver_username = None
        self.webserver_password = None

        if entrypoint:
            self.load_entrypoint()
        else:
            self.load_webserver()
            self.load()
            # Token passed along, e.g. if playback initiated by Plex Companion. Might be
            # another user playing something! Token identifies user
            self.plex_transient_token = None

    def load_webserver(self):
        """
        PKC needs Kodi webserver to work correctly
        """
        LOG.debug('Loading Kodi webserver details')
        if not utils.settings('enableTextureCache') == 'true':
            LOG.info('Artwork caching disabled')
            return
        self.webserver_password = js.get_setting('services.webserverpassword')
        if not self.webserver_password:
            LOG.warn('No password set for the Kodi web server. Generating a '
                     'new random password')
            self.webserver_password = secrets.token_urlsafe(16)
            js.set_setting('services.webserverpassword', self.webserver_password)
        if not js.get_setting('services.webserver'):
            # The Kodi webserver is needed for artwork caching. PKC already set
            # a strong, random password automatically if you haven't done so
            # already. Please confirm the next dialog that you want to enable
            # the webserver now with Yes.
            utils.messageDialog(utils.lang(29999), utils.lang(30004))
            # Enable the webserver, it is disabled. Will force a Kodi pop-up
            js.set_setting('services.webserver', True)
            if not js.get_setting('services.webserver'):
                LOG.warn('User chose to not enable Kodi webserver')
                utils.settings('enableTextureCache', value='false')
        self.webserver_host = 'localhost'
        self.webserver_port = js.get_setting('services.webserverport')
        self.webserver_username = js.get_setting('services.webserverusername')

    def load(self):
        LOG.debug('Loading connection settings')
        # Shall we verify SSL certificates? "None" will leave SSL enabled
        # Ignore this setting for Kodi >= 18 as Kodi 18 is much stricter
        # with checking SSL certs
        self.verify_ssl_cert = None
        # Do we have an ssl certificate for PKC we need to use?
        self.ssl_cert_path = utils.settings('sslcert') \
            if utils.settings('sslcert') != 'None' else None

        self.machine_identifier = utils.settings('plex_machineIdentifier') or None
        self.server_name = utils.settings('plex_servername') or None
        self.https = utils.settings('https') == 'true'
        self.host = utils.settings('ipaddress') or None
        self.port = int(utils.settings('port')) if utils.settings('port') else None
        if not self.host:
            self.server = None
        elif self.https:
            self.server = 'https://%s:%s' % (self.host, self.port)
        else:
            self.server = 'http://%s:%s' % (self.host, self.port)
        self.online = False
        LOG.debug('Set server %s (%s) to %s',
                  self.server_name, self.machine_identifier, self.server)

    def load_entrypoint(self):
        self.verify_ssl_cert = None
        self.ssl_cert_path = utils.settings('sslcert') \
            if utils.settings('sslcert') != 'None' else None
        self.https = utils.settings('https') == 'true'
        self.host = utils.settings('ipaddress') or None
        self.port = int(utils.settings('port')) if utils.settings('port') else None
        if not self.host:
            self.server = None
        elif self.https:
            self.server = 'https://%s:%s' % (self.host, self.port)
        else:
            self.server = 'http://%s:%s' % (self.host, self.port)

    def clear(self):
        LOG.debug('Clearing connection settings')
        self.machine_identifier = None
        self.server_name = None
        self.https = None
        self.host = None
        self.port = None
        self.server = None
