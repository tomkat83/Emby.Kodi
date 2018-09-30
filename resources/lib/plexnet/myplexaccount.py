import json
import time
import hashlib
from xml.etree import ElementTree

import plexapp
import myplexrequest
import locks
import callback
import asyncadapter

import util

ACCOUNT = None


class HomeUser(util.AttributeDict):
    pass


class MyPlexAccount(object):
    def __init__(self):
        # Strings
        self.ID = None
        self.title = None
        self.username = None
        self.thumb = None
        self.email = None
        self.authToken = None
        self.pin = None
        self.thumb = None

        # Booleans
        self.isAuthenticated = plexapp.INTERFACE.getPreference('auto_signin', False)
        self.isSignedIn = False
        self.isOffline = False
        self.isExpired = False
        self.isPlexPass = False
        self.isManaged = False
        self.isSecure = False
        self.hasQueue = False

        self.isAdmin = False
        self.switchUser = False

        self.adminHasPlexPass = False

        self.lastHomeUserUpdate = None
        self.homeUsers = []

    def init(self):
        self.loadState()

    def saveState(self):
        obj = {
            'ID': self.ID,
            'title': self.title,
            'username': self.username,
            'email': self.email,
            'authToken': self.authToken,
            'pin': self.pin,
            'isPlexPass': self.isPlexPass,
            'isManaged': self.isManaged,
            'isAdmin': self.isAdmin,
            'isSecure': self.isSecure,
            'adminHasPlexPass': self.adminHasPlexPass
        }

        plexapp.INTERFACE.setRegistry("MyPlexAccount", json.dumps(obj), "myplex")

    def loadState(self):
        # Look for the new JSON serialization. If it's not there, look for the
        # old token and Plex Pass values.

        plexapp.APP.addInitializer("myplex")

        jstring = plexapp.INTERFACE.getRegistry("MyPlexAccount", None, "myplex")

        if jstring:
            try:
                obj = json.loads(jstring)
            except:
                util.ERROR()
                obj = None

            if obj:
                self.ID = obj.get('ID') or self.ID
                self.title = obj.get('title') or self.title
                self.username = obj.get('username') or self.username
                self.email = obj.get('email') or self.email
                self.authToken = obj.get('authToken') or self.authToken
                self.pin = obj.get('pin') or self.pin
                self.isPlexPass = obj.get('isPlexPass') or self.isPlexPass
                self.isManaged = obj.get('isManaged') or self.isManaged
                self.isAdmin = obj.get('isAdmin') or self.isAdmin
                self.isSecure = obj.get('isSecure') or self.isSecure
                self.isProtected = bool(obj.get('pin'))
                self.adminHasPlexPass = obj.get('adminHasPlexPass') or self.adminHasPlexPass

        if self.authToken:
            request = myplexrequest.MyPlexRequest("/users/account")
            context = request.createRequestContext("account", callback.Callable(self.onAccountResponse))
            plexapp.APP.startRequest(request, context)
        else:
            plexapp.APP.clearInitializer("myplex")

    def logState(self):
        util.LOG("Authenticated as {0}:{1}".format(self.ID, repr(self.title)))
        util.LOG("SignedIn: {0}".format(self.isSignedIn))
        util.LOG("Offline: {0}".format(self.isOffline))
        util.LOG("Authenticated: {0}".format(self.isAuthenticated))
        util.LOG("PlexPass: {0}".format(self.isPlexPass))
        util.LOG("Managed: {0}".format(self.isManaged))
        util.LOG("Protected: {0}".format(self.isProtected))
        util.LOG("Admin: {0}".format(self.isAdmin))
        util.LOG("AdminPlexPass: {0}".format(self.adminHasPlexPass))

    def onAccountResponse(self, request, response, context):
        oldId = self.ID

        if response.isSuccess():
            data = response.getBodyXml()

            # The user is signed in
            self.isSignedIn = True
            self.isOffline = False
            self.ID = data.attrib.get('id')
            self.title = data.attrib.get('title')
            self.username = data.attrib.get('username')
            self.email = data.attrib.get('email')
            self.thumb = data.attrib.get('thumb')
            self.authToken = data.attrib.get('authenticationToken')
            self.isPlexPass = (data.find('subscription') is not None and data.find('subscription').attrib.get('active') == '1')
            self.isManaged = data.attrib.get('restricted') == '1'
            self.isSecure = data.attrib.get('secure') == '1'
            self.hasQueue = bool(data.attrib.get('queueEmail'))

            # PIN
            if data.attrib.get('pin'):
                self.pin = data.attrib.get('pin')
            else:
                self.pin = None
            self.isProtected = bool(self.pin)

            # update the list of users in the home
            self.updateHomeUsers()

            # set admin attribute for the user
            self.isAdmin = False
            if self.homeUsers:
                for user in self.homeUsers:
                    if self.ID == user.id:
                        self.isAdmin = str(user.admin) == "1"
                        break

            if self.isAdmin and self.isPlexPass:
                self.adminHasPlexPass = True

            # consider a single, unprotected user authenticated
            if not self.isAuthenticated and not self.isProtected and len(self.homeUsers) <= 1:
                self.isAuthenticated = True

            self.logState()

            self.saveState()
            plexapp.MANAGER.publish()
            plexapp.refreshResources()
        elif response.getStatus() >= 400 and response.getStatus() < 500:
            # The user is specifically unauthorized, clear everything
            util.WARN_LOG("Sign Out: User is unauthorized")
            self.signOut(True)
        else:
            # Unexpected error, keep using whatever we read from the registry
            util.WARN_LOG("Unexpected response from plex.tv ({0}), switching to OFFLINE mode".format(response.getStatus()))
            self.logState()
            self.isOffline = True
            # consider a single, unprotected user authenticated
            if not self.isAuthenticated and not self.isProtected:
                self.isAuthenticated = True

        plexapp.APP.clearInitializer("myplex")
        # Logger().UpdateSyslogHeader()  # TODO: ------------------------------------------------------------------------------------------------------IMPLEMENT

        if oldId != self.ID or self.switchUser:
            self.switchUser = None
            plexapp.APP.trigger("change:user", account=self, reallyChanged=oldId != self.ID)

        plexapp.APP.trigger("account:response")

    def signOut(self, expired=False):
        # Strings
        self.ID = None
        self.title = None
        self.username = None
        self.email = None
        self.authToken = None
        self.pin = None
        self.lastHomeUserUpdate = None

        # Booleans
        self.isSignedIn = False
        self.isPlexPass = False
        self.adminHasPlexPass = False
        self.isManaged = False
        self.isSecure = False
        self.isExpired = expired

        # Clear the saved resources
        plexapp.INTERFACE.clearRegistry("mpaResources", "xml_cache")

        # Remove all saved servers
        plexapp.SERVERMANAGER.clearServers()

        # Enable the welcome screen again
        plexapp.INTERFACE.setPreference("show_welcome", True)

        plexapp.APP.trigger("change:user", account=self, reallyChanged=True)

        self.saveState()

    def hasPlexPass(self):
        if self.isPlexPass or self.isManaged:
            return True

        return self.adminHasPlexPass

    def validateToken(self, token, switchUser=False):
        self.authToken = token
        self.switchUser = switchUser

        request = myplexrequest.MyPlexRequest("/users/sign_in.xml")
        context = request.createRequestContext("sign_in", callback.Callable(self.onAccountResponse))
        if self.isOffline:
            context.timeout = self.isOffline and asyncadapter.AsyncTimeout(1).setConnectTimeout(1)
        plexapp.APP.startRequest(request, context, {})

    def refreshAccount(self):
        if not self.authToken:
            return
        self.validateToken(self.authToken, False)

    def updateHomeUsers(self):
        # Ignore request and clear any home users we are not signed in
        if not self.isSignedIn:
            self.homeUsers = []
            if self.isOffline:
                self.homeUsers.append(MyPlexAccount())

            self.lastHomeUserUpdate = None
            return

        # Cache home users for 60 seconds, mainly to stop back to back tests
        epoch = time.time()
        if not self.lastHomeUserUpdate:
            self.lastHomeUserUpdate = epoch
        elif self.lastHomeUserUpdate + 60 > epoch:
            util.DEBUG_LOG("Skipping home user update (updated {0} seconds ago)".format(epoch - self.lastHomeUserUpdate))
            return

        req = myplexrequest.MyPlexRequest("/api/home/users")
        xml = req.getToStringWithTimeout()
        data = ElementTree.fromstring(xml)
        if data.attrib.get('size') and data.find('User') is not None:
            self.homeUsers = []
            for user in data.findall('User'):
                homeUser = HomeUser(user.attrib)
                homeUser.isAdmin = homeUser.admin == "1"
                homeUser.isManaged = homeUser.restricted == "1"
                homeUser.isProtected = homeUser.protected == "1"
                self.homeUsers.append(homeUser)

            self.lastHomeUserUpdate = epoch

        util.LOG("home users: {0}".format(self.homeUsers))

    def switchHomeUser(self, userId, pin=''):
        if userId == self.ID and self.isAuthenticated:
            return True

        # Offline support
        if self.isOffline:
            hashed = 'NONE'
            if pin and self.authToken:
                hashed = hashlib.sha256(pin + self.authToken).digest()

            if not self.isProtected or self.isAuthenticated or hashed == (self.pin or ""):
                util.DEBUG_LOG("OFFLINE access granted")
                self.isAuthenticated = True
                self.validateToken(self.authToken, True)
                return True
        else:
            # build path and post to myplex to swith the user
            path = '/api/home/users/{0}/switch'.format(userId)
            req = myplexrequest.MyPlexRequest(path)
            xml = req.postToStringWithTimeout({'pin': pin})
            data = ElementTree.fromstring(xml)

            if data.attrib.get('authenticationToken'):
                self.isAuthenticated = True
                # validate the token (trigger change:user) on user change or channel startup
                if userId != self.ID or not locks.LOCKS.isLocked("idleLock"):
                    self.validateToken(data.attrib.get('authenticationToken'), True)
                return True

        return False

    def isActive(self):
        return self.isSignedIn or self.isOffline


ACCOUNT = MyPlexAccount()
