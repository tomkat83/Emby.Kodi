# -*- coding: utf-8 -*-

###############################################################################

import os
import sys
from datetime import datetime
import Queue

import xbmc
import xbmcaddon
import xbmcgui

###############################################################################

_addon = xbmcaddon.Addon(id='plugin.video.plexkodiconnect')
addon_path = _addon.getAddonInfo('path').decode('utf-8')
base_resource = xbmc.translatePath(os.path.join(addon_path, 'resources', 'lib')).decode('utf-8')
sys.path.append(base_resource)

###############################################################################

import userclient
import clientinfo
import initialsetup
import kodimonitor
import librarysync
import player
import utils
import videonodes
import websocket_client as wsc
import downloadutils

import PlexAPI
import PlexCompanion

###############################################################################


@utils.logging
class Service():

    welcome_msg = True
    server_online = True
    warn_auth = True

    userclient_running = False
    websocket_running = False
    library_running = False
    kodimonitor_running = False
    plexCompanion_running = False

    def __init__(self):

        log = self.logMsg
        window = utils.window

        self.clientInfo = clientinfo.ClientInfo()
        logLevel = self.getLogLevel()
        self.monitor = xbmc.Monitor()

        window('emby_logLevel', value=str(logLevel))
        window('emby_kodiProfile', value=xbmc.translatePath("special://profile"))
        window('emby_pluginpath', value=utils.settings('useDirectPaths'))

        self.runPlexCompanion = utils.settings('plexCompanion')

        # Initial logging
        log("======== START %s ========" % self.addonName, 0)
        log("Platform: %s" % (self.clientInfo.getPlatform()), 0)
        log("KODI Version: %s" % xbmc.getInfoLabel('System.BuildVersion'), 0)
        log("%s Version: %s" % (self.addonName, self.clientInfo.getVersion()), 0)
        log("Using plugin paths: %s" % (utils.settings('useDirectPaths') != "true"), 0)
        log("Log Level: %s" % logLevel, 0)

        # Reset window props for profile switch
        properties = [

            "emby_online", "emby_serverStatus", "emby_onWake",
            "emby_syncRunning", "emby_dbCheck", "emby_kodiScan",
            "emby_shouldStop", "currUserId", "emby_dbScan", "emby_sessionId",
            "emby_initialScan", "emby_customplaylist", "emby_playbackProps",
            "plex_runLibScan", "plex_username", "pms_token", "plex_token",
            "pms_server", "plex_machineIdentifier", "plex_servername",
            "plex_authenticated", "PlexUserImage", "useDirectPaths",
            "replaceSMB", "remapSMB", "remapSMBmovieOrg", "remapSMBtvOrg",
            "remapSMBmusicOrg", "remapSMBmovieNew", "remapSMBtvNew",
            "remapSMBmusicNew", "suspend_LibraryThread", "plex_terminateNow",
            "kodiplextimeoffset", "countError", "countUnauthorized"
        ]
        for prop in properties:
            window(prop, clear=True)

        # Clear video nodes properties
        videonodes.VideoNodes().clearProperties()
        
        # Set the minimum database version
        window('emby_minDBVersion', value="1.1.1")

    def getLogLevel(self):
        try:
            logLevel = int(utils.settings('logLevel'))
        except ValueError:
            logLevel = 0
        return logLevel

    def ServiceEntryPoint(self):

        log = self.logMsg
        window = utils.window
        lang = utils.language

        # Important: Threads depending on abortRequest will not trigger
        # if profile switch happens more than once.
        monitor = self.monitor
        kodiProfile = xbmc.translatePath("special://profile")

        # Server auto-detect
        initialsetup.InitialSetup().setup()

        # Queue for background sync
        queue = Queue.Queue(maxsize=200)

        connectMsg = True if utils.settings('connectMsg') == 'true' else False

        # Initialize important threads
        user = userclient.UserClient()
        ws = wsc.WebSocket(queue)
        library = librarysync.LibrarySync(queue)
        kplayer = player.Player()
        xplayer = xbmc.Player()
        plx = PlexAPI.PlexAPI()

        # Sync and progress report
        lastProgressUpdate = datetime.today()

        while not monitor.abortRequested():

            if window('emby_kodiProfile') != kodiProfile:
                # Profile change happened, terminate this thread and others
                log("Kodi profile was: %s and changed to: %s. Terminating old Emby thread."
                    % (kodiProfile, utils.window('emby_kodiProfile')), 1)
                
                break
            
            # Before proceeding, need to make sure:
            # 1. Server is online
            # 2. User is set
            # 3. User has access to the server

            if window('emby_online') == "true":
                # Emby server is online
                # Verify if user is set and has access to the server
                if (user.currUser is not None) and user.HasAccess:
                    # If an item is playing
                    if xplayer.isPlaying():
                        try:
                            # Update and report progress
                            playtime = xplayer.getTime()
                            totalTime = xplayer.getTotalTime()
                            currentFile = kplayer.currentFile

                            # Update positionticks
                            if kplayer.played_info.get(currentFile) is not None:
                                kplayer.played_info[currentFile]['currentPosition'] = playtime
                            
                            td = datetime.today() - lastProgressUpdate
                            secDiff = td.seconds
                            
                            # Report progress to Emby server
                            if (secDiff > 3):
                                kplayer.reportPlayback()
                                lastProgressUpdate = datetime.today()
                            
                            elif window('emby_command') == "true":
                                # Received a remote control command that
                                # requires updating immediately
                                window('emby_command', clear=True)
                                kplayer.reportPlayback()
                                lastProgressUpdate = datetime.today()
                        except Exception as e:
                            log("Exception in Playback Monitor Service: %s" % e, 1)
                            pass
                    else:
                        # Start up events
                        self.warn_auth = True
                        if connectMsg and self.welcome_msg:
                            # Reset authentication warnings
                            self.welcome_msg = False
                            xbmcgui.Dialog().notification(
                                heading=self.addonName,
                                message="%s %s" % (lang(33000), user.currUser),
                                icon="special://home/addons/plugin.video.plexkodiconnect/icon.png",
                                time=2000,
                                sound=False)
                        # Start monitoring kodi events
                        if not self.kodimonitor_running:
                            self.kodimonitor_running = kodimonitor.KodiMonitor()

                        # Start the Websocket Client
                        if not self.websocket_running:
                            self.websocket_running = True
                            ws.start()
                        # Start the syncing thread
                        if not self.library_running:
                            self.library_running = True
                            library.start()
                        # Start the Plex Companion thread
                        if not self.plexCompanion_running and \
                                self.runPlexCompanion == "true":
                            self.plexCompanion_running = True
                            plexCompanion = PlexCompanion.PlexCompanion()
                            plexCompanion.start()
                else:
                    if (user.currUser is None) and self.warn_auth:
                        # Alert user is not authenticated and suppress future warning
                        self.warn_auth = False
                        log("Not authenticated yet.", 1)

                    # User access is restricted.
                    # Keep verifying until access is granted
                    # unless server goes offline or Kodi is shut down.
                    while user.HasAccess == False:
                        # Verify access with an API call
                        user.hasAccess()

                        if window('emby_online') != "true":
                            # Server went offline
                            break

                        if monitor.waitForAbort(5):
                            # Abort was requested while waiting. We should exit
                            break
                        xbmc.sleep(50)
            else:
                # Wait until Emby server is online
                # or Kodi is shut down.
                while not monitor.abortRequested():
                    server = user.getServer()
                    if server is False:
                        # No server info set in add-on settings
                        pass
                    elif plx.CheckConnection(server, verifySSL=True) is False:
                        # Server is offline or cannot be reached
                        # Alert the user and suppress future warning
                        if self.server_online:
                            log("Server is offline.", 1)
                            window('emby_online', value="false")
                            # Suspend threads
                            window('suspend_LibraryThread', value='true')

                            xbmcgui.Dialog().notification(
                                heading=lang(33001),
                                message="%s %s"
                                        % (self.addonName, lang(33002)),
                                icon="special://home/addons/plugin.video."
                                     "plexkodiconnect/icon.png",
                                sound=False)
                        self.server_online = False
                    else:
                        # Server is online
                        if not self.server_online:
                            # Server was offline when Kodi started.
                            # Wait for server to be fully established.
                            if monitor.waitForAbort(5):
                                # Abort was requested while waiting.
                                break
                            # Alert the user that server is online.
                            xbmcgui.Dialog().notification(
                                heading=self.addonName,
                                message=lang(33003),
                                icon="special://home/addons/plugin.video."
                                     "plexkodiconnect/icon.png",
                                time=2000,
                                sound=False)
                        self.server_online = True
                        log("Server %s is online and ready." % server, 1)
                        window('emby_online', value="true")
                        if window('plex_authenticated') == 'true':
                            # Server got offline when we were authenticated.
                            # Hence resume threads
                            window('suspend_LibraryThread', clear=True)

                        # Start the userclient thread
                        if not self.userclient_running:
                            self.userclient_running = True
                            user.start()

                        break

                    if monitor.waitForAbort(1):
                        # Abort was requested while waiting.
                        break
                    xbmc.sleep(50)

            if monitor.waitForAbort(1):
                # Abort was requested while waiting. We should exit
                break

        # Terminating PlexKodiConnect

        # Tell all threads to terminate (e.g. several lib sync threads)
        utils.window('plex_terminateNow', value='true')

        try:
            plexCompanion.stopThread()
        except:
            xbmc.log('plexCompanion already shut down')

        try:
            library.stopThread()
        except:
            xbmc.log('Library sync already shut down')

        try:
            ws.stopThread()
        except:
            xbmc.log('Websocket client already shut down')

        try:
            user.stopThread()
        except:
            xbmc.log('User client already shut down')

        try:
            downloadutils.DownloadUtils().stopSession()
        except:
            pass

        log("======== STOP %s ========" % self.addonName, 0)

# Delay option
delay = int(utils.settings('startupDelay'))

xbmc.log("Delaying Plex startup by: %s sec..." % delay)
if delay and xbmc.Monitor().waitForAbort(delay):
    # Start the service
    xbmc.log("Abort requested while waiting. Emby for kodi not started.")
else:
    Service().ServiceEntryPoint()
