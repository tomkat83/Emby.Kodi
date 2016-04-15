# -*- coding: utf-8 -*-

###############################################################################

import threading

import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

import utils
import downloadutils

import PlexAPI
from PlexFunctions import GetMachineIdentifier

###############################################################################


@utils.logging
@utils.ThreadMethodsAdditionalSuspend('suspend_Userclient')
@utils.ThreadMethods
class UserClient(threading.Thread):

    # Borg - multiple instances, shared state
    __shared_state = {}

    def __init__(self):
        self.__dict__ = self.__shared_state

        self.auth = True
        self.retry = 0

        self.currUser = None
        self.currUserId = None
        self.currServer = None
        self.currToken = None
        self.HasAccess = True
        self.AdditionalUser = []

        self.userSettings = None

        self.addon = xbmcaddon.Addon()
        self.doUtils = downloadutils.DownloadUtils()

        threading.Thread.__init__(self)

    def getUsername(self):
        """
        Returns username as unicode
        """

        username = utils.settings('username')

        if not username:
            self.logMsg("No username saved, trying to get Plex username", 0)
            username = utils.settings('plexLogin')
            if not username:
                self.logMsg("Also no Plex username found", 0)
                return ""

        return username

    def getServer(self, prefix=True):

        settings = utils.settings

        # Original host
        self.servername = settings('plex_servername')
        HTTPS = settings('https') == "true"
        host = settings('ipaddress')
        port = settings('port')
        self.machineIdentifier = settings('plex_machineIdentifier')

        server = host + ":" + port

        if not host:
            self.logMsg("No server information saved.", 2)
            return False

        # If https is true
        if prefix and HTTPS:
            server = "https://%s" % server
        # If https is false
        elif prefix and not HTTPS:
            server = "http://%s" % server
        # User entered IP; we need to get the machineIdentifier
        if self.machineIdentifier == '' and prefix is True:
            self.machineIdentifier = GetMachineIdentifier(server)
            if self.machineIdentifier is None:
                self.machineIdentifier = ''
            settings('plex_machineIdentifier', value=self.machineIdentifier)
        self.logMsg('Returning active server: %s' % server)
        return server

    def getSSLverify(self):
        # Verify host certificate
        return None if utils.settings('sslverify') == 'true' else False

    def getSSL(self):
        # Client side certificate
        return None if utils.settings('sslcert') == 'None' \
            else utils.settings('sslcert')

    def setUserPref(self):
        self.logMsg('Setting user preferences', 0)
        # Only try to get user avatar if there is a token
        if self.currToken:
            url = PlexAPI.PlexAPI().GetUserArtworkURL(self.currUser)
            if url:
                utils.window('PlexUserImage', value=url)
        # Set resume point max
        # url = "{server}/emby/System/Configuration?format=json"
        # result = doUtils.downloadUrl(url)

        # utils.settings('markPlayed', value=str(result['MaxResumePct']))

    def hasAccess(self):
        # Plex: always return True for now
        return True
        # hasAccess is verified in service.py
        log = self.logMsg
        window = utils.window

        url = "{server}/emby/Users?format=json"
        result = self.doUtils.downloadUrl(url)

        if result == False:
            # Access is restricted, set in downloadutils.py via exception
            log("Access is restricted.", 1)
            self.HasAccess = False

        elif window('emby_online') != "true":
            # Server connection failed
            pass

        elif window('emby_serverStatus') == "restricted":
            log("Access is granted.", 1)
            self.HasAccess = True
            window('emby_serverStatus', clear=True)
            xbmcgui.Dialog().notification(self.addonName,
                                          utils.language(33007))

    def loadCurrUser(self, username, userId, usertoken, authenticated=False):
        self.logMsg('Loading current user', 0)
        window = utils.window
        settings = utils.settings
        doUtils = self.doUtils

        self.currUserId = userId
        self.currToken = usertoken
        self.currServer = self.getServer()
        self.ssl = self.getSSLverify()
        self.sslcert = self.getSSL()

        if authenticated is False:
            self.logMsg('Testing validity of current token', 0)
            res = PlexAPI.PlexAPI().CheckConnection(self.currServer,
                                                    token=self.currToken,
                                                    verifySSL=self.ssl)
            if res is False:
                self.logMsg('Answer from PMS is not as expected. Retrying', -1)
                return False
            elif res == 401:
                self.logMsg('Token is no longer valid', -1)
                return False
            elif res >= 400:
                self.logMsg('Answer from PMS is not as expected. Retrying', -1)
                return False

        # Set to windows property
        window('currUserId', value=userId)
        window('plex_username', value=username)
        # This is the token for the current PMS (might also be '')
        window('pms_token', value=self.currToken)
        # This is the token for plex.tv for the current user
        # Is only '' if user is not signed in to plex.tv
        window('plex_token', value=settings('plexToken'))
        window('pms_server', value=self.currServer)
        window('plex_machineIdentifier', value=self.machineIdentifier)
        window('plex_servername', value=self.servername)
        window('plex_authenticated', value='true')
        window('plex_serverowned', value=settings('plex_serverowned'))

        window('useDirectPaths', value='true'
               if utils.settings('useDirectPaths') == "1" else 'false')
        window('replaceSMB', value='true'
               if utils.settings('replaceSMB') == "true" else 'false')
        window('remapSMB', value='true'
               if utils.settings('remapSMB') == "true" else 'false')
        if window('remapSMB') == 'true':
            items = ('movie', 'tv', 'music')
            for item in items:
                # Normalize! Get rid of potential (back)slashes at the end
                org = settings('remapSMB%sOrg' % item)
                new = settings('remapSMB%sNew' % item)
                if org.endswith('\\') or org.endswith('/'):
                    org = org[:-1]
                if new.endswith('\\') or new.endswith('/'):
                    new = new[:-1]
                window('remapSMB%sOrg' % item, value=org)
                window('remapSMB%sNew' % item, value=new)

        # Start DownloadUtils session
        doUtils.startSession(reset=True)
        # self.getAdditionalUsers()
        # Set user preferences in settings
        self.currUser = username
        self.setUserPref()

        # Writing values to settings file
        settings('username', value=username)
        settings('userid', value=userId)
        settings('accessToken', value=usertoken)

        dialog = xbmcgui.Dialog()
        if utils.settings('connectMsg') == "true":
            if username:
                dialog.notification(
                    heading=self.addonName,
                    message="Welcome " + username,
                    icon="special://home/addons/plugin.video.plexkodiconnect/icon.png")
            else:
                dialog.notification(
                    heading=self.addonName,
                    message="Welcome",
                    icon="special://home/addons/plugin.video.plexkodiconnect/icon.png")
        return True

    def authenticate(self):
        log = self.logMsg
        log('Authenticating user', 1)
        lang = utils.language
        window = utils.window
        settings = utils.settings
        dialog = xbmcgui.Dialog()

        # Give attempts at entering password / selecting user
        if self.retry >= 2:
            log("Too many retries to login.", -1)
            window('emby_serverStatus', value="Stop")
            dialog.ok(lang(33001),
                      lang(39023))
            xbmc.executebuiltin(
                'Addon.OpenSettings(plugin.video.plexkodiconnect)')
            return False

        # Get /profile/addon_data
        addondir = xbmc.translatePath(
            self.addon.getAddonInfo('profile')).decode('utf-8')
        hasSettings = xbmcvfs.exists("%ssettings.xml" % addondir)

        # If there's no settings.xml
        if not hasSettings:
            log("Error, no settings.xml found.", -1)
            self.auth = False
            return False
        server = self.getServer()
        # If there is no server we can connect to
        if not server:
            log("Missing server information.", 0)
            self.auth = False
            return False

        # If there is a username in the settings, try authenticating
        username = settings('username')
        userId = settings('userid')
        usertoken = settings('accessToken')
        enforceLogin = settings('enforceUserLogin')
        # Found a user in the settings, try to authenticate
        if username and enforceLogin == 'false':
            log('Trying to authenticate with old settings', 0)
            if self.loadCurrUser(username,
                                 userId,
                                 usertoken,
                                 authenticated=False):
                # SUCCESS: loaded a user from the settings
                return True
            else:
                # Failed to use the settings - delete them!
                log("Failed to use the settings credentials. Deleting them", 1)
                settings('username', value='')
                settings('userid', value='')
                settings('accessToken', value='')

        plx = PlexAPI.PlexAPI()

        # Could not use settings - try to get Plex user list from plex.tv
        plextoken = settings('plexToken')
        if plextoken:
            log("Trying to connect to plex.tv to get a user list", 0)
            userInfo = plx.ChoosePlexHomeUser(plextoken)
            if userInfo is False:
                # FAILURE: Something went wrong, try again
                self.auth = True
                self.retry += 1
                return False
            username = userInfo['username']
            userId = userInfo['userid']
            usertoken = userInfo['token']
        else:
            log("Trying to authenticate without a token", 0)
            username = ''
            userId = ''
            usertoken = ''

        if self.loadCurrUser(username, userId, usertoken, authenticated=False):
            # SUCCESS: loaded a user from the settings
            return True
        else:
            # FAILUR: Something went wrong, try again
            self.auth = True
            self.retry += 1
            return False

    def resetClient(self):
        self.logMsg("Reset UserClient authentication.", 1)

        self.doUtils.stopSession()

        settings = utils.settings
        window = utils.window

        window('plex_authenticated', clear=True)
        window('pms_token', clear=True)
        window('plex_token', clear=True)
        window('pms_server', clear=True)
        window('plex_machineIdentifier', clear=True)
        window('plex_servername', clear=True)
        window('currUserId', clear=True)
        window('plex_username', clear=True)

        settings('username', value='')
        settings('userid', value='')
        settings('accessToken', value='')

        # Reset token in downloads
        self.doUtils.setToken('')
        self.doUtils.setUserId('')
        self.doUtils.setUsername('')

        self.currToken = None
        self.auth = True
        self.currUser = None
        self.currUserId = None

        self.retry = 0

    def run(self):
        log = self.logMsg
        window = utils.window

        log("----===## Starting UserClient ##===----", 0)
        while not self.threadStopped():
            while self.threadSuspended():
                if self.threadStopped():
                    break
                xbmc.sleep(1000)

            status = window('emby_serverStatus')

            if status == "Stop":
                xbmc.sleep(500)
                continue

            # Verify the connection status to server
            elif status == "restricted":
                # Parental control is restricting access
                self.HasAccess = False

            elif status == "401":
                # Unauthorized access, revoke token
                window('emby_serverStatus', value="Auth")
                self.resetClient()
                xbmc.sleep(2000)

            if self.auth and (self.currUser is None):
                # Try to authenticate user
                if not status or status == "Auth":
                    # Set auth flag because we no longer need
                    # to authenticate the user
                    self.auth = False
                    if self.authenticate():
                        # Successfully authenticated and loaded a user
                        log("Successfully authenticated!", 1)
                        log("Current user: %s" % self.currUser, 1)
                        log("Current userId: %s" % self.currUserId, 1)
                        log("Current accessToken: xxxx", 1)
                        self.retry = 0
                        window('suspend_LibraryThread', clear=True)
                        window('emby_serverStatus', clear=True)

            if not self.auth and (self.currUser is None):
                # Loop if no server found
                server = self.getServer()

                # The status Stop is for when user cancelled password dialog.
                # Or retried too many times
                if server and status != "Stop":
                    # Only if there's information found to login
                    log("Server found: %s" % server, 2)
                    self.auth = True

            # Minimize CPU load
            xbmc.sleep(100)

        self.doUtils.stopSession()
        log("##===---- UserClient Stopped ----===##", 0)
