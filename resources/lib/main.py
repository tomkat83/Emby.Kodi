#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
import logging
import sys
import threading
import gc

import xbmc

from . import plex, util, backgroundthread
from .plexnet import plexapp, threadutils
from .windows import userselect

from . import utils
from . import userclient
from . import initialsetup
from . import kodimonitor
from . import librarysync
from . import websocket_client
from . import plex_companion
from . import plex_functions as PF
from . import command_pipeline
from . import playback_starter
from . import playqueue
from . import artwork
from . import variables as v
from . import state
from . import loghandler

###############################################################################
loghandler.config()
LOG = logging.getLogger("PLEX.main")
###############################################################################


class Service():

    server_online = True
    warn_auth = True

    user = None
    ws = None
    library = None
    plexcompanion = None

    user_running = False
    ws_running = False
    alexa_running = False
    library_running = False
    plexcompanion_running = False
    kodimonitor_running = False
    playback_starter_running = False
    image_cache_thread_running = False

    def __init__(self):
        # Initial logging
        LOG.info("======== START %s ========", v.ADDON_NAME)
        LOG.info("Platform: %s", v.PLATFORM)
        LOG.info("KODI Version: %s", v.KODILONGVERSION)
        LOG.info("%s Version: %s", v.ADDON_NAME, v.ADDON_VERSION)
        LOG.info("PKC Direct Paths: %s",
                 utils.settings('useDirectPaths') == '1')
        LOG.info("Number of sync threads: %s",
                 utils.settings('syncThreadNumber'))
        LOG.info('Playlist m3u encoding: %s', v.M3U_ENCODING)
        LOG.info("Full sys.argv received: %s", sys.argv)
        LOG.info('Sync playlists: %s', utils.settings('enablePlaylistSync'))
        LOG.info('Synching only specific Kodi playlists: %s',
                 utils.settings('syncSpecificKodiPlaylists') == 'true')
        LOG.info('Kodi playlist prefix: %s',
                 utils.settings('syncSpecificKodiPlaylistsPrefix'))
        LOG.info('Synching only specific Plex playlists: %s',
                 utils.settings('syncSpecificPlexPlaylistsPrefix') == 'true')
        LOG.info('Play playlist prefix: %s',
                 utils.settings('syncSpecificPlexPlaylistsPrefix'))
        self.monitor = xbmc.Monitor()
        # Load/Reset PKC entirely - important for user/Kodi profile switch
        initialsetup.reload_pkc()

    def _stop_pkc(self):
        """
        Kodi's abortRequested is really unreliable :-(
        """
        return self.monitor.abortRequested() or state.STOP_PKC

    def ServiceEntryPoint(self):
        # Important: Threads depending on abortRequest will not trigger
        # if profile switch happens more than once.
        _stop_pkc = self._stop_pkc
        monitor = self.monitor

        # Server auto-detect
        initialsetup.InitialSetup().setup()

        # Detect playback start early on
        self.command_pipeline = command_pipeline.Monitor_Window()
        self.command_pipeline.start()

        # Initialize important threads, handing over self for callback purposes
        self.user = userclient.UserClient()
        self.ws = websocket_client.PMS_Websocket()
        self.alexa = websocket_client.Alexa_Websocket()
        self.library = librarysync.LibrarySync()
        self.plexcompanion = plex_companion.PlexCompanion()
        self.specialmonitor = kodimonitor.SpecialMonitor()
        self.playback_starter = playback_starter.PlaybackStarter()
        self.playqueue = playqueue.PlayqueueMonitor()
        if utils.settings('enableTextureCache') == "true":
            self.image_cache_thread = artwork.Image_Cache_Thread()

        welcome_msg = True
        counter = 0
        while not _stop_pkc():

            if utils.window('plex_kodiProfile') != v.KODI_PROFILE:
                # Profile change happened, terminate this thread and others
                LOG.info("Kodi profile was: %s and changed to: %s. "
                         "Terminating old PlexKodiConnect thread.",
                         v.KODI_PROFILE, utils.window('plex_kodiProfile'))
                break

            # Before proceeding, need to make sure:
            # 1. Server is online
            # 2. User is set
            # 3. User has access to the server

            if utils.window('plex_online') == "true":
                # Plex server is online
                # Verify if user is set and has access to the server
                if (self.user.user is not None) and self.user.has_access:
                    if not self.kodimonitor_running:
                        # Start up events
                        self.warn_auth = True
                        if welcome_msg is True:
                            # Reset authentication warnings
                            welcome_msg = False
                            utils.dialog('notification',
                                         utils.lang(29999),
                                         "%s %s" % (utils.lang(33000),
                                                    self.user.user),
                                         icon='{plex}',
                                         time=2000,
                                         sound=False)
                        # Start monitoring kodi events
                        self.kodimonitor_running = kodimonitor.KodiMonitor()
                        self.specialmonitor.start()
                        # Start the Websocket Client
                        if not self.ws_running:
                            self.ws_running = True
                            self.ws.start()
                        # Start the Alexa thread
                        if (not self.alexa_running and
                                utils.settings('enable_alexa') == 'true'):
                            self.alexa_running = True
                            self.alexa.start()
                        # Start the syncing thread
                        if not self.library_running:
                            self.library_running = True
                            self.library.start()
                        # Start the Plex Companion thread
                        if not self.plexcompanion_running:
                            self.plexcompanion_running = True
                            self.plexcompanion.start()
                        if not self.playback_starter_running:
                            self.playback_starter_running = True
                            self.playback_starter.start()
                        self.playqueue.start()
                        if (not self.image_cache_thread_running and
                                utils.settings('enableTextureCache') == "true"):
                            self.image_cache_thread_running = True
                            self.image_cache_thread.start()
                else:
                    if (self.user.user is None) and self.warn_auth:
                        # Alert user is not authenticated and suppress future
                        # warning
                        self.warn_auth = False
                        LOG.warn("Not authenticated yet.")

                    # User access is restricted.
                    # Keep verifying until access is granted
                    # unless server goes offline or Kodi is shut down.
                    while self.user.has_access is False:
                        # Verify access with an API call
                        self.user.check_access()

                        if utils.window('plex_online') != "true":
                            # Server went offline
                            break

                        if monitor.waitForAbort(3):
                            # Abort was requested while waiting. We should exit
                            break
            else:
                # Wait until Plex server is online
                # or Kodi is shut down.
                while not self._stop_pkc():
                    server = self.user.get_server()
                    if server is False:
                        # No server info set in add-on settings
                        pass
                    elif PF.check_connection(server, verifySSL=True) is False:
                        # Server is offline or cannot be reached
                        # Alert the user and suppress future warning
                        if self.server_online:
                            self.server_online = False
                            utils.window('plex_online', value="false")
                            # Suspend threads
                            state.SUSPEND_LIBRARY_THREAD = True
                            LOG.error("Plex Media Server went offline")
                            if utils.settings('show_pms_offline') == 'true':
                                utils.dialog('notification',
                                             utils.lang(33001),
                                             "%s %s" % (utils.lang(29999),
                                                        utils.lang(33002)),
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
                                    utils.settings('show_pms_offline') == 'true'):
                                utils.dialog('notification',
                                             utils.lang(29999),
                                             utils.lang(33003),
                                             icon='{plex}',
                                             time=5000,
                                             sound=False)
                        LOG.info("Server %s is online and ready.", server)
                        utils.window('plex_online', value="true")
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
        utils.window('plex_service_started', clear=True)
        LOG.info("======== STOP %s ========", v.ADDON_NAME)


def waitForThreads():
    LOG.debug('Checking for any remaining threads')
    while len(threading.enumerate()) > 1:
        for t in threading.enumerate():
            if t != threading.currentThread():
                if t.isAlive():
                    LOG.debug('Waiting on thread: %s', t.name)
                    if isinstance(t, threading._Timer):
                        t.cancel()
                        t.join()
                    elif isinstance(t, threadutils.KillableThread):
                        t.kill(force_and_wait=True)
                    else:
                        t.join()
    LOG.debug('All threads done')


def signout():
    util.setSetting('auth.token', '')
    LOG.info('Signing out...')
    plexapp.ACCOUNT.signOut()


def main():
    LOG.info('Starting PKC %s', util.ADDON.getAddonInfo('version'))
    LOG.info('User-agent: %s', plex.defaultUserAgent())

    try:
        while not xbmc.abortRequested:
            if plex.init():
                while not xbmc.abortRequested:
                    if (
                        not plexapp.ACCOUNT.isOffline and not
                        plexapp.ACCOUNT.isAuthenticated and
                        (len(plexapp.ACCOUNT.homeUsers) > 1 or plexapp.ACCOUNT.isProtected)

                    ):
                        result = userselect.start()
                        if not result:
                            return
                        elif result == 'signout':
                            signout()
                            break
                        elif result == 'signin':
                            break
                        LOG.info('User selected')

                    try:
                        selectedServer = plexapp.SERVERMANAGER.selectedServer

                        if not selectedServer:
                            LOG.debug('Waiting for selected server...')
                            for timeout, skip_preferred, skip_owned in ((10, True, False), (10, True, True)):
                                plex.CallbackEvent(plexapp.APP, 'change:selectedServer', timeout=timeout).wait()

                                selectedServer = plexapp.SERVERMANAGER.checkSelectedServerSearch(skip_preferred=skip_preferred, skip_owned=skip_owned)
                                if selectedServer:
                                    break
                            else:
                                LOG.debug('Finished waiting for selected server...')

                        LOG.info('Starting with server: %s', selectedServer)

                        windowutils.HOME = home.HomeWindow.open()
                        util.CRON.cancelReceiver(windowutils.HOME)

                        if not windowutils.HOME.closeOption:
                            return

                        closeOption = windowutils.HOME.closeOption

                        windowutils.shutdownHome()

                        if closeOption == 'signout':
                            signout()
                            break
                        elif closeOption == 'switch':
                            plexapp.ACCOUNT.isAuthenticated = False
                    finally:
                        windowutils.shutdownHome()
                        gc.collect(2)

            else:
                break
    except:
        util.ERROR()
    finally:
        LOG.info('SHUTTING DOWN...')
        # player.shutdown()
        plexapp.APP.preShutdown()
        if util.CRON:
            util.CRON.stop()
        backgroundthread.BGThreader.shutdown()
        plexapp.APP.shutdown()
        waitForThreads()
        LOG.info('SHUTDOWN FINISHED')

        from .windows import kodigui
        kodigui.MONITOR = None
        util.shutdown()
        gc.collect(2)
