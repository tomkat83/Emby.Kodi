# -*- coding: utf-8 -*-
###############################################################################
from logging import getLogger
from os import path as os_path
from sys import path as sys_path, argv

from xbmc import translatePath, Monitor
from xbmcaddon import Addon

###############################################################################

_ADDON = Addon(id='plugin.video.plexkodiconnect')
try:
    _ADDON_PATH = _ADDON.getAddonInfo('path').decode('utf-8')
except TypeError:
    _ADDON_PATH = _ADDON.getAddonInfo('path').decode()
try:
    _BASE_RESOURCE = translatePath(os_path.join(
        _ADDON_PATH,
        'resources',
        'lib')).decode('utf-8')
except TypeError:
    _BASE_RESOURCE = translatePath(os_path.join(
        _ADDON_PATH,
        'resources',
        'lib')).decode()
sys_path.append(_BASE_RESOURCE)

###############################################################################

from utils import settings, window, language as lang, dialog
from userclient import UserClient
import initialsetup
from kodimonitor import KodiMonitor, SpecialMonitor
from librarysync import LibrarySync
from websocket_client import PMS_Websocket, Alexa_Websocket

from PlexFunctions import check_connection
from PlexCompanion import PlexCompanion
from command_pipeline import Monitor_Window
from playback_starter import Playback_Starter
from playqueue import PlayqueueMonitor
from artwork import Image_Cache_Thread
import variables as v
import state

###############################################################################
import loghandler

loghandler.config()
LOG = getLogger("PLEX.service")
###############################################################################


class Service():

    server_online = True
    warn_auth = True

    user = None
    ws = None
    library = None
    plexCompanion = None

    user_running = False
    ws_running = False
    alexa_running = False
    library_running = False
    plexCompanion_running = False
    kodimonitor_running = False
    playback_starter_running = False
    image_cache_thread_running = False

    def __init__(self):
        # Initial logging
        LOG.info("======== START %s ========", v.ADDON_NAME)
        LOG.info("Platform: %s", v.PLATFORM)
        LOG.info("KODI Version: %s", v.KODILONGVERSION)
        LOG.info("%s Version: %s", v.ADDON_NAME, v.ADDON_VERSION)
        LOG.info("PKC Direct Paths: %s", settings('useDirectPaths') == "true")
        LOG.info("Number of sync threads: %s", settings('syncThreadNumber'))
        LOG.info("Full sys.argv received: %s", argv)
        self.monitor = Monitor()
        # Load/Reset PKC entirely - important for user/Kodi profile switch
        initialsetup.reload_pkc()

    def __stop_PKC(self):
        """
        Kodi's abortRequested is really unreliable :-(
        """
        return self.monitor.abortRequested() or state.STOP_PKC

    def ServiceEntryPoint(self):
        # Important: Threads depending on abortRequest will not trigger
        # if profile switch happens more than once.
        __stop_PKC = self.__stop_PKC
        monitor = self.monitor
        kodiProfile = v.KODI_PROFILE

        # Server auto-detect
        initialsetup.InitialSetup().setup()

        # Detect playback start early on
        self.command_pipeline = Monitor_Window()
        self.command_pipeline.start()

        # Initialize important threads, handing over self for callback purposes
        self.user = UserClient()
        self.ws = PMS_Websocket()
        self.alexa = Alexa_Websocket()
        self.library = LibrarySync()
        self.plexCompanion = PlexCompanion()
        self.specialMonitor = SpecialMonitor()
        self.playback_starter = Playback_Starter()
        self.playqueue = PlayqueueMonitor()
        if settings('enableTextureCache') == "true":
            self.image_cache_thread = Image_Cache_Thread()

        welcome_msg = True
        counter = 0
        while not __stop_PKC():

            if window('plex_kodiProfile') != kodiProfile:
                # Profile change happened, terminate this thread and others
                LOG.info("Kodi profile was: %s and changed to: %s. "
                         "Terminating old PlexKodiConnect thread.",
                         kodiProfile, window('plex_kodiProfile'))
                break

            # Before proceeding, need to make sure:
            # 1. Server is online
            # 2. User is set
            # 3. User has access to the server

            if window('plex_online') == "true":
                # Plex server is online
                # Verify if user is set and has access to the server
                if (self.user.currUser is not None) and self.user.HasAccess:
                    if not self.kodimonitor_running:
                        # Start up events
                        self.warn_auth = True
                        if welcome_msg is True:
                            # Reset authentication warnings
                            welcome_msg = False
                            dialog('notification',
                                   lang(29999),
                                   "%s %s" % (lang(33000),
                                              self.user.currUser),
                                   icon='{plex}',
                                   time=2000,
                                   sound=False)
                        # Start monitoring kodi events
                        self.kodimonitor_running = KodiMonitor()
                        self.specialMonitor.start()
                        # Start the Websocket Client
                        if not self.ws_running:
                            self.ws_running = True
                            self.ws.start()
                        # Start the Alexa thread
                        if (not self.alexa_running and
                                settings('enable_alexa') == 'true'):
                            self.alexa_running = True
                            self.alexa.start()
                        # Start the syncing thread
                        if not self.library_running:
                            self.library_running = True
                            self.library.start()
                        # Start the Plex Companion thread
                        if not self.plexCompanion_running:
                            self.plexCompanion_running = True
                            self.plexCompanion.start()
                        if not self.playback_starter_running:
                            self.playback_starter_running = True
                            self.playback_starter.start()
                        self.playqueue.start()
                        if (not self.image_cache_thread_running and
                                settings('enableTextureCache') == "true"):
                            self.image_cache_thread_running = True
                            self.image_cache_thread.start()
                else:
                    if (self.user.currUser is None) and self.warn_auth:
                        # Alert user is not authenticated and suppress future
                        # warning
                        self.warn_auth = False
                        LOG.warn("Not authenticated yet.")

                    # User access is restricted.
                    # Keep verifying until access is granted
                    # unless server goes offline or Kodi is shut down.
                    while self.user.HasAccess is False:
                        # Verify access with an API call
                        self.user.hasAccess()

                        if window('plex_online') != "true":
                            # Server went offline
                            break

                        if monitor.waitForAbort(3):
                            # Abort was requested while waiting. We should exit
                            break
            else:
                # Wait until Plex server is online
                # or Kodi is shut down.
                while not self.__stop_PKC():
                    server = self.user.getServer()
                    if server is False:
                        # No server info set in add-on settings
                        pass
                    elif check_connection(server, verifySSL=True) is False:
                        # Server is offline or cannot be reached
                        # Alert the user and suppress future warning
                        if self.server_online:
                            self.server_online = False
                            window('plex_online', value="false")
                            # Suspend threads
                            state.SUSPEND_LIBRARY_THREAD = True
                            LOG.error("Plex Media Server went offline")
                            if settings('show_pms_offline') == 'true':
                                dialog('notification',
                                       lang(33001),
                                       "%s %s" % (lang(29999), lang(33002)),
                                       icon='{plex}',
                                       sound=False)
                        counter += 1
                        # Periodically check if the IP changed, e.g. per minute
                        if counter > 20:
                            counter = 0
                            setup = initialsetup.InitialSetup()
                            tmp = setup.pick_pms()
                            if tmp is not None:
                                setup.write_pms_to_settings(tmp)
                    else:
                        # Server is online
                        counter = 0
                        if not self.server_online:
                            # Server was offline when Kodi started.
                            # Wait for server to be fully established.
                            if monitor.waitForAbort(5):
                                # Abort was requested while waiting.
                                break
                            self.server_online = True
                            # Alert the user that server is online.
                            if (welcome_msg is False and
                                    settings('show_pms_offline') == 'true'):
                                dialog('notification',
                                       lang(29999),
                                       lang(33003),
                                       icon='{plex}',
                                       time=5000,
                                       sound=False)
                        LOG.info("Server %s is online and ready.", server)
                        window('plex_online', value="true")
                        if state.AUTHENTICATED:
                            # Server got offline when we were authenticated.
                            # Hence resume threads
                            state.SUSPEND_LIBRARY_THREAD = False

                        # Start the userclient thread
                        if not self.user_running:
                            self.user_running = True
                            self.user.start()

                        break

                    if monitor.waitForAbort(3):
                        # Abort was requested while waiting.
                        break

            if monitor.waitForAbort(0.05):
                # Abort was requested while waiting. We should exit
                break
        # Terminating PlexKodiConnect

        # Tell all threads to terminate (e.g. several lib sync threads)
        state.STOP_PKC = True
        window('plex_service_started', clear=True)
        LOG.info("======== STOP %s ========", v.ADDON_NAME)


# Safety net - Kody starts PKC twice upon first installation!
if window('plex_service_started') == 'true':
    EXIT = True
else:
    window('plex_service_started', value='true')
    EXIT = False

# Delay option
DELAY = int(settings('startupDelay'))

LOG.info("Delaying Plex startup by: %s sec...", DELAY)
if EXIT:
    LOG.error('PKC service.py already started - exiting this instance')
elif DELAY and Monitor().waitForAbort(DELAY):
    # Start the service
    LOG.info("Abort requested while waiting. PKC not started.")
else:
    Service().ServiceEntryPoint()
