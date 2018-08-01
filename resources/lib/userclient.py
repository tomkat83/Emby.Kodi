#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread

from xbmc import sleep, executebuiltin

from .downloadutils import DownloadUtils as DU
from . import utils
from . import path_ops
from . import plex_tv
from . import plex_functions as PF
from . import variables as v
from . import state

###############################################################################

LOG = getLogger('PLEX.userclient')

###############################################################################


@utils.thread_methods(add_suspends=['SUSPEND_USER_CLIENT'])
class UserClient(Thread):
    """
    Manage Plex users
    """
    # Borg - multiple instances, shared state
    __shared_state = {}

    def __init__(self):
        self.__dict__ = self.__shared_state

        self.auth = True
        self.retry = 0

        self.user = None
        self.has_access = True

        self.server = None
        self.server_name = None
        self.machine_identifier = None
        self.token = None
        self.ssl = None
        self.sslcert = None

        self.do_utils = None

        Thread.__init__(self)

    def get_server(self):
        """
        Get the current PMS' URL
        """
        # Original host
        self.server_name = utils.settings('plex_servername')
        https = utils.settings('https') == "true"
        host = utils.settings('ipaddress')
        port = utils.settings('port')
        self.machine_identifier = utils.settings('plex_machineIdentifier')
        if not host:
            LOG.debug("No server information saved.")
            return False
        server = host + ":" + port
        # If https is true
        if https:
            server = "https://%s" % server
        # If https is false
        else:
            server = "http://%s" % server
        # User entered IP; we need to get the machineIdentifier
        if not self.machine_identifier:
            self.machine_identifier = PF.GetMachineIdentifier(server)
            if not self.machine_identifier:
                self.machine_identifier = ''
            utils.settings('plex_machineIdentifier',
                           value=self.machine_identifier)
        LOG.debug('Returning active server: %s', server)
        return server

    @staticmethod
    def get_ssl_verify():
        """
        Do we need to verify the SSL certificate? Return None if that is the
        case, else False
        """
        return None if utils.settings('sslverify') == 'true' else False

    @staticmethod
    def get_ssl_certificate():
        """
        Client side certificate
        """
        return None if utils.settings('sslcert') == 'None' \
            else utils.settings('sslcert')

    def set_user_prefs(self):
        """
        Load a user's profile picture
        """
        LOG.debug('Setting user preferences')
        # Only try to get user avatar if there is a token
        if self.token:
            url = PF.GetUserArtworkURL(self.user)
            if url:
                utils.window('PlexUserImage', value=url)

    @staticmethod
    def check_access():
        # Plex: always return True for now
        return True

    def load_user(self, username, user_id, usertoken, authenticated=False):
        """
        Load the current user's details for PKC
        """
        LOG.debug('Loading current user')
        self.token = usertoken
        self.server = self.get_server()
        self.ssl = self.get_ssl_verify()
        self.sslcert = self.get_ssl_certificate()

        if authenticated is False:
            if self.server is None:
                return False
            LOG.debug('Testing validity of current token')
            res = PF.check_connection(self.server,
                                      token=self.token,
                                      verifySSL=self.ssl)
            if res is False:
                # PMS probably offline
                return False
            elif res == 401:
                LOG.error('Token is no longer valid')
                return 401
            elif res >= 400:
                LOG.error('Answer from PMS is not as expected. Retrying')
                return False

        # Set to windows property
        state.PLEX_USER_ID = user_id or None
        state.PLEX_USERNAME = username
        # This is the token for the current PMS (might also be '')
        utils.window('pms_token', value=usertoken)
        state.PMS_TOKEN = usertoken
        # This is the token for plex.tv for the current user
        # Is only '' if user is not signed in to plex.tv
        utils.window('plex_token', value=utils.settings('plexToken'))
        state.PLEX_TOKEN = utils.settings('plexToken') or None
        utils.window('plex_restricteduser',
                     value=utils.settings('plex_restricteduser'))
        state.RESTRICTED_USER = True \
            if utils.settings('plex_restricteduser') == 'true' else False
        utils.window('pms_server', value=self.server)
        utils.window('plex_machineIdentifier', value=self.machine_identifier)
        utils.window('plex_servername', value=self.server_name)
        utils.window('plex_authenticated', value='true')
        state.AUTHENTICATED = True

        utils.window('useDirectPaths',
                     value='true' if utils.settings('useDirectPaths') == "1"
                     else 'false')
        state.DIRECT_PATHS = True if utils.settings('useDirectPaths') == "1" \
            else False
        state.INDICATE_MEDIA_VERSIONS = True \
            if utils.settings('indicate_media_versions') == "true" else False
        utils.window('plex_force_transcode_pix',
                     value='true' if utils.settings('force_transcode_pix') == "1"
                     else 'false')

        # Start DownloadUtils session
        self.do_utils = DU()
        self.do_utils.startSession(reset=True)
        # Set user preferences in settings
        self.user = username
        self.set_user_prefs()

        # Writing values to settings file
        utils.settings('username', value=username)
        utils.settings('userid', value=user_id)
        utils.settings('accessToken', value=usertoken)
        return True

    def authenticate(self):
        """
        Authenticate the current user
        """
        LOG.debug('Authenticating user')

        # Give attempts at entering password / selecting user
        if self.retry >= 2:
            LOG.error("Too many retries to login.")
            state.PMS_STATUS = 'Stop'
            utils.dialog('ok', utils.lang(33001), utils.lang(39023))
            executebuiltin(
                'Addon.Openutils.settings(plugin.video.plexkodiconnect)')
            return False

        # If there's no settings.xml
        if not path_ops.exists("%ssettings.xml" % v.ADDON_PROFILE):
            LOG.error("Error, no settings.xml found.")
            self.auth = False
            return False
        server = self.get_server()
        # If there is no server we can connect to
        if not server:
            LOG.info("Missing server information.")
            self.auth = False
            return False

        # If there is a username in the settings, try authenticating
        username = utils.settings('username')
        userId = utils.settings('userid')
        usertoken = utils.settings('accessToken')
        enforceLogin = utils.settings('enforceUserLogin')
        # Found a user in the settings, try to authenticate
        if username and enforceLogin == 'false':
            LOG.debug('Trying to authenticate with old settings')
            answ = self.load_user(username,
                                  userId,
                                  usertoken,
                                  authenticated=False)
            if answ is True:
                # SUCCESS: loaded a user from the settings
                return True
            elif answ == 401:
                LOG.error("User token no longer valid. Sign user out")
                utils.settings('username', value='')
                utils.settings('userid', value='')
                utils.settings('accessToken', value='')
            else:
                LOG.debug("Could not yet authenticate user")
                return False

        # Could not use settings - try to get Plex user list from plex.tv
        plextoken = utils.settings('plexToken')
        if plextoken:
            LOG.info("Trying to connect to plex.tv to get a user list")
            userInfo = plex_tv.choose_home_user(plextoken)
            if userInfo is False:
                # FAILURE: Something went wrong, try again
                self.auth = True
                self.retry += 1
                return False
            username = userInfo['username']
            userId = userInfo['userid']
            usertoken = userInfo['token']
        else:
            LOG.info("Trying to authenticate without a token")
            username = ''
            userId = ''
            usertoken = ''

        if self.load_user(username, userId, usertoken, authenticated=False):
            # SUCCESS: loaded a user from the settings
            return True
        # Something went wrong, try again
        self.auth = True
        self.retry += 1
        return False

    def reset_client(self):
        """
        Reset all user settings
        """
        LOG.debug("Reset UserClient authentication.")
        try:
            self.do_utils.stopSession()
        except AttributeError:
            pass
        utils.window('plex_authenticated', clear=True)
        state.AUTHENTICATED = False
        utils.window('pms_token', clear=True)
        state.PLEX_TOKEN = None
        state.PLEX_TRANSIENT_TOKEN = None
        state.PMS_TOKEN = None
        utils.window('plex_token', clear=True)
        utils.window('pms_server', clear=True)
        utils.window('plex_machineIdentifier', clear=True)
        utils.window('plex_servername', clear=True)
        state.PLEX_USER_ID = None
        state.PLEX_USERNAME = None
        utils.window('plex_restricteduser', clear=True)
        state.RESTRICTED_USER = False

        utils.settings('username', value='')
        utils.settings('userid', value='')
        utils.settings('accessToken', value='')

        self.token = None
        self.auth = True
        self.user = None

        self.retry = 0

    def run(self):
        """
        Do the work
        """
        LOG.info("----===## Starting UserClient ##===----")
        stopped = self.stopped
        suspended = self.suspended
        while not stopped():
            while suspended():
                if stopped():
                    break
                sleep(1000)

            if state.PMS_STATUS == "Stop":
                sleep(500)
                continue

            elif state.PMS_STATUS == "401":
                # Unauthorized access, revoke token
                state.PMS_STATUS = 'Auth'
                utils.window('plex_serverStatus', value='Auth')
                self.reset_client()
                sleep(3000)

            if self.auth and (self.user is None):
                # Try to authenticate user
                if not state.PMS_STATUS or state.PMS_STATUS == "Auth":
                    # Set auth flag because we no longer need
                    # to authenticate the user
                    self.auth = False
                    if self.authenticate():
                        # Successfully authenticated and loaded a user
                        LOG.info("Successfully authenticated!")
                        LOG.info("Current user: %s", self.user)
                        LOG.info("Current userId: %s", state.PLEX_USER_ID)
                        self.retry = 0
                        state.SUSPEND_LIBRARY_THREAD = False
                        utils.window('plex_serverStatus', clear=True)
                        state.PMS_STATUS = False

            if not self.auth and (self.user is None):
                # Loop if no server found
                server = self.get_server()

                # The status Stop is for when user cancelled password dialog.
                # Or retried too many times
                if server and state.PMS_STATUS != "Stop":
                    # Only if there's information found to login
                    LOG.debug("Server found: %s", server)
                    self.auth = True

            # Minimize CPU load
            sleep(100)

        LOG.info("##===---- UserClient Stopped ----===##")
