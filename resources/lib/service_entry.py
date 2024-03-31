#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys

import xbmc
import xbmcvfs

from . import utils, clientinfo
from . import initialsetup
from . import kodimonitor
from . import sync, library_sync
from . import websocket_client
from . import plex_db
from . import plex_companion
from . import plex_functions as PF
from . import playback_starter
from . import variables as v
from . import app
from . import loghandler
from . import backgroundthread
from . import skip_plex_markers
from . import downloadutils
from .windows import userselect

###############################################################################
loghandler.config()
LOG = logging.getLogger("PLEX.service")
###############################################################################

WINDOW_PROPERTIES = (
    "pms_token", "plex_token", "plex_authenticated", "plex_restricteduser",
    "plex_allows_mediaDeletion", "plexkodiconnect.command", "plex_result")


class Service(object):
    ws = None
    sync = None

    def __init__(self):
        self._init_done = False
        # Detect switch of Kodi profile - a second instance of PKC is started
        self.profile = xbmcvfs.translatePath('special://profile')
        utils.window('plex_kodi_profilepath', value=self.profile)

        # Kodi Version supported by PKC?
        try:
            v.database_paths()
        except RuntimeError as err:

            # Database does not exists
            LOG.error('The current Kodi version is incompatible')
            LOG.error('Error: %s', err)
            # "The current Kodi version is not supported by PKC. Please consult
            # the Plex forum."
            utils.messageDialog(utils.lang(29999), utils.lang(39403))
            return
        # Initial logging
        LOG.info("======== START %s ========", v.ADDON_NAME)
        LOG.info("KODI Version: %s", v.KODILONGVERSION)
        LOG.info("%s Version: %s", v.ADDON_NAME, v.ADDON_VERSION)
        LOG.info("PKC Direct Paths: %s",
                 utils.settings('useDirectPaths') == '1')
        LOG.info("Escape paths: %s", utils.settings('escapePath') == 'true')
        LOG.info("Synching Plex artwork to Kodi: %s",
                 utils.settings('usePlexArtwork') == 'true')
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
        LOG.info("Db version: %s", utils.settings('dbCreatedWithVersion'))
        LOG.info('Kodi video database version: %s', v.DB_VIDEO_VERSION)
        LOG.info('Kodi music database version: %s', v.DB_MUSIC_VERSION)
        LOG.info('Kodi texture database version: %s', v.DB_TEXTURE_VERSION)

        # Reset some status in the PKC settings
        # toggled to "No"
        utils.settings('plex_status_fanarttv_lookup', value=utils.lang(106))
        # toggled to "No"
        utils.settings('plex_status_image_caching', value=utils.lang(106))

        # Reset window props
        for prop in WINDOW_PROPERTIES:
            utils.window(prop, clear=True)

        # Show a dedicated context menu entry for "Extras"?
        utils.window('plex_context_show_extras',
                     value=utils.settings('plex_context_show_extras'))

        clientinfo.getDeviceId()

        self.startup_completed = False
        self.server_has_been_online = True
        self.welcome_msg = True
        self.connection_check_counter = 0
        self.setup = None
        self.pms_ws = None
        self.alexa_ws = None
        # Flags for other threads
        self.connection_check_running = False
        self.auth_running = False
        self._init_done = True

    def should_cancel(self):
        if self.profile != utils.window('plex_kodi_profilepath'):
            LOG.info('Kodi profile switch detected, shutting this instance down')
            return True
        return app.APP.monitor.abortRequested() or app.APP.stop_pkc

    def on_connection_check(self, result):
        """
        Call this method after PF.check_connection()
        """
        try:
            if result is False:
                # Server is offline or cannot be reached
                # Alert the user and suppress future warning
                if app.CONN.online:
                    # PMS was online before
                    LOG.warn("Plex Media Server went offline")
                    app.CONN.online = False
                    app.APP.suspend_threads()
                    LOG.debug('Threads suspended')
                    if utils.settings('show_pms_offline') == 'true':
                        utils.dialog('notification',
                                     utils.lang(33001),
                                     "%s %s" % (utils.lang(29999),
                                                utils.lang(33002)),
                                     icon='{plex}',
                                     sound=False)
                self.connection_check_counter += 1
                # Periodically check if the IP changed every 15 seconds
                if self.connection_check_counter > 150:
                    self.connection_check_counter = 0
                    server = self.setup.pick_pms()
                    if server:
                        LOG.debug('Found server: %s', server)
                        self.setup.save_pms_settings(server['baseURL'], server['token'])
                        self.setup.write_pms_to_settings(server)
                        app.CONN.load()
                        app.ACCOUNT.reset_session()
            else:
                # Server is online
                self.connection_check_counter = 0
                if not app.CONN.online:
                    # Server was offline before
                    if (self.welcome_msg is False and
                            utils.settings('show_pms_offline') == 'true'):
                        # Alert the user that server is online
                        utils.dialog('notification',
                                     utils.lang(29999),
                                     utils.lang(33003),
                                     icon='{plex}',
                                     time=5000,
                                     sound=False)
                LOG.info("Server is online and ready")
                if app.ACCOUNT.authenticated:
                    # Server got offline when we were authenticated.
                    # Hence resume threads
                    app.APP.resume_threads()
                app.CONN.online = True
        finally:
            self.connection_check_running = False

    @staticmethod
    def log_out():
        """
        Ensures that lib sync threads are suspended; signs out user
        """
        LOG.info('Log-out requested')
        app.APP.suspend_threads()
        LOG.info('Successfully suspended threads')
        app.ACCOUNT.log_out()
        LOG.info('User has been logged out')

    def choose_pms_server(self, manual=False):
        LOG.info("Choosing PMS server requested, starting")
        if manual:
            if not self.setup.enter_new_pms_address():
                return False
        else:
            server = self.setup.pick_pms(showDialog=True)
            if not server:
                LOG.info('We did not connect to a new PMS, aborting')
                return False
            LOG.info("User chose server %s with url %s",
                     server['name'], server['baseURL'])
            if (server['machineIdentifier'] == app.CONN.machine_identifier and
                    server['baseURL'] == app.CONN.server):
                LOG.info('User chose old PMS to connect to')
                return False
            # Save changes to to file
            self.setup.save_pms_settings(server['baseURL'], server['token'])
            self.setup.write_pms_to_settings(server)
        self.log_out()
        # Wipe Kodi and Plex database as well as playlists and video nodes
        utils.wipe_database()
        app.CONN.load()
        app.ACCOUNT.reset_session()
        app.ACCOUNT.set_unauthenticated()
        self.server_has_been_online = False
        self.welcome_msg = False
        # Force a full sync of all items
        library_sync.force_full_sync()
        app.SYNC.run_lib_scan = 'full'
        # Enable the main loop to continue
        app.APP.suspend = False
        LOG.info("Choosing new PMS complete")
        return True

    def switch_plex_user(self):
        self.log_out()
        # First remove playlists and video nodes of old user
        library_sync.delete_files()
        app.ACCOUNT.set_unauthenticated()
        # Force full sync after login
        library_sync.force_full_sync()
        app.SYNC.run_lib_scan = 'full'
        # Enable the main loop to display user selection dialog
        app.APP.suspend = False
        return True

    def toggle_plex_tv(self):
        if app.ACCOUNT.plex_token:
            LOG.info('Resetting plex.tv credentials in settings')
            self.log_out()
            app.ACCOUNT.clear()
        else:
            LOG.info('Login to plex.tv')
            if self.setup.plex_tv_sign_in():
                self.setup.write_credentials_to_settings()
                app.ACCOUNT.load()
                # Enable the main loop to continue
                app.APP.suspend = False

    def watchlist_add(self, raw_params):
        return self.watchlist_modify('addToWatchlist', raw_params)

    def watchlist_remove(self, raw_params):
        return self.watchlist_modify('removeFromWatchlist', raw_params)

    def watchlist_modify(self, api_type, raw_params):
        params = dict(utils.parse_qsl(raw_params))
        kodi_id = params.get('kodi_id')
        kodi_type = params.get('kodi_type')

        LOG.info('watchlist_modify %s %s %s', api_type, kodi_id, kodi_type)

        watchlist_plex_guid = None

        with plex_db.PlexDB(lock=False) as plexdb:
            plex_item = plexdb.item_by_kodi_id(kodi_id, kodi_type)
            if not plex_item:
                return False

            plex_guid = plex_item['plex_guid']
            if not plex_guid:
                return False

            plex_type = plex_item['plex_type']

            if plex_type == v.PLEX_TYPE_MOVIE or plex_type == v.PLEX_TYPE_SHOW:
                watchlist_plex_guid = plex_guid

            elif plex_type == v.PLEX_TYPE_SEASON or plex_type == v.PLEX_TYPE_EPISODE:
                plex_show_item = plexdb.item_by_id(plex_item['show_id'], v.PLEX_TYPE_SHOW)
                if plex_show_item:
                    watchlist_plex_guid = plex_show_item['plex_guid']

        if watchlist_plex_guid is None:
            return False

        # ratingKey query param accepts the last section in the plex_guid
        watchlist_rating_key = watchlist_plex_guid.split('/')[-1]

        downloadutils.DownloadUtils().downloadUrl('https://discover.provider.plex.tv/actions/%s?ratingKey=%s' % (api_type, watchlist_rating_key),
            action_type = 'PUT',
            authenticate=False,
            headerOptions={'X-Plex-Token': utils.window('plex_token')})

        xbmc.executebuiltin('UpdateLibrary(video)')

    def authenticate(self):
        """
        Authenticate the current user or prompt to log-in

        Returns True if successful, False if not. 'aborted' if user chose to
        abort
        """
        if self._do_auth():
            if self.welcome_msg is True:
                # Reset authentication warnings
                self.welcome_msg = False
                utils.dialog('notification',
                             utils.lang(29999),
                             "%s %s" % (utils.lang(33000),
                                        app.ACCOUNT.plex_username),
                             icon='{plex}',
                             time=2000,
                             sound=False)
            app.reload()
            app.APP.resume_threads()
        self.auth_running = False

    def enter_new_pms_address(self):
        server = self.setup.enter_new_pms_address()
        if not server:
            return
        self.log_out()
        # Save changes to to file
        self.setup.save_pms_settings(server['baseURL'], server['token'])
        self.setup.write_pms_to_settings(server)
        # Wipe Kodi and Plex database as well as playlists and video nodes
        utils.wipe_database()
        app.CONN.load()
        app.ACCOUNT.reset_session()
        app.ACCOUNT.set_unauthenticated()
        self.server_has_been_online = False
        self.welcome_msg = False
        # Force a full sync of all items
        library_sync.force_full_sync()
        app.SYNC.run_lib_scan = 'full'
        # Enable the main loop to continue
        app.APP.suspend = False
        LOG.info("Entering PMS address complete")
        return True

    def choose_plex_libraries(self):
        if not app.CONN.online:
            LOG.error('PMS not online to choose libraries')
            # "{0} offline"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(39213).format(app.CONN.server_name or ''),
                         icon='{plex}')
            return
        if not app.ACCOUNT.authenticated:
            LOG.error('Not yet authenticated for PMS to choose libraries')
            # "Unauthorized for PMS"
            utils.dialog('notification', utils.lang(29999), utils.lang(30017))
            return
        app.APP.suspend_threads()
        from .library_sync import sections
        try:
            # Get newest sections from the PMS
            if not sections.sync_from_pms(self, pick_libraries=True):
                return
            # Force a full sync of all items
            library_sync.force_full_sync()
            app.SYNC.run_lib_scan = 'full'
        finally:
            app.APP.resume_threads()

    def reset_playlists_and_nodes(self):
        """
        Resets the Kodi playlists and nodes for all the PKC libraries by
        deleting all of them first, then rewriting everything
        """
        app.APP.suspend_threads()
        from .library_sync import sections
        try:
            sections.clear_window_vars()
            sections.delete_videonode_files()
            # Get newest sections from the PMS
            if not sections.sync_from_pms(self, pick_libraries=False):
                LOG.warn('We could not successfully reset the playlists!')
                # "Plex playlists/nodes refresh failed"
                utils.dialog('notification',
                             utils.lang(29999),
                             utils.lang(39406),
                             icon='{plex}',
                             sound=False)
                return
            # "Plex playlists/nodes refreshed"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(39405),
                         icon='{plex}',
                         sound=False)
        finally:
            app.APP.resume_threads()
            xbmc.executebuiltin('ReloadSkin()')

    def _do_auth(self):
        LOG.info('Authenticating user')
        if app.ACCOUNT.plex_username and not app.ACCOUNT.force_login:            # Found a user in the settings, try to authenticate
            LOG.info('Trying to authenticate with old settings')
            res = PF.check_connection(app.CONN.server,
                                      token=app.ACCOUNT.pms_token,
                                      verifySSL=app.CONN.verify_ssl_cert)
            if res is False:
                LOG.error('Something went wrong while checking connection')
                return False
            elif res == 401:
                LOG.error('User %s no longer has access - signing user out',
                          app.ACCOUNT.plex_username)
                self.log_out()
                return False
            elif res >= 400:
                LOG.error('Answer from PMS is not as expected')
                return False
            LOG.info('Successfully authenticated using old settings')
            app.ACCOUNT.set_authenticated()
            return True

        user = None
        while True:
            # Could not use settings - try to get Plex user list from plex.tv
            if app.ACCOUNT.plex_token:
                LOG.info("Trying to connect to plex.tv to get a user list")
                user, _ = userselect.start()
                if not user:
                    LOG.info('No user received')
                    app.APP.suspend = True
                    app.APP.suspend_threads()
                    LOG.debug('Threads suspended')
                    return False
                username = user.title
                user_id = user.id
                token = user.authToken
            else:
                LOG.info("Trying to authenticate without a token")
                username = ''
                user_id = ''
                token = ''
            res = PF.check_connection(app.CONN.server,
                                      token=token,
                                      verifySSL=app.CONN.verify_ssl_cert)
            if res is False:
                LOG.error('Something went wrong while checking connection')
                return False
            elif res == 401:
                if app.ACCOUNT.plex_token:
                    LOG.error('User %s does not have access to PMS %s on %s',
                              username, app.CONN.server_name, app.CONN.server)
                    # "User is unauthorized for server {0}"
                    utils.messageDialog(utils.lang(29999),
                                        utils.lang(33010).format(app.CONN.server_name))
                    self.log_out()
                    return False
                else:
                    # "Failed to authenticate. Did you login to plex.tv?"
                    utils.messageDialog(utils.lang(29999), utils.lang(39023))
                    if self.setup.plex_tv_sign_in():
                        self.setup.write_credentials_to_settings()
                        app.ACCOUNT.load()
                        continue
                    else:
                        LOG.debug('Suspending threads')
                        app.APP.suspend = True
                        app.APP.suspend_threads()
                        LOG.debug('Threads suspended')
                        return False
            elif res >= 400:
                LOG.error('Answer from PMS is not as expected')
                return False
            LOG.info('Successfully authenticated')
            # Got new values that need to be saved
            utils.settings('username', value=username)
            utils.settings('userid', value=user_id)
            utils.settings('accessToken', value=token)
            if user:
                utils.settings('plex_restricteduser',
                               'true' if user.isManaged else 'false')
                app.CONN.restricted_user = user.isManaged
            else:
                utils.settings('plex_restricteduser', 'false')
                app.CONN.restricted_user = False
            app.ACCOUNT.load()
            app.ACCOUNT.set_authenticated()
            return True

    def ServiceEntryPoint(self):
        if not self._init_done:
            return
        # Important: Threads depending on abortRequest will not trigger
        # if profile switch happens more than once.
        # Some plumbing
        app.init()
        app.APP.monitor = kodimonitor.KodiMonitor()
        app.APP.player = xbmc.Player()

        # Server auto-detect
        self.setup = initialsetup.InitialSetup()
        self.setup.setup()

        # Initialize important threads
        self.pms_ws = websocket_client.get_pms_websocketapp()
        self.alexa_ws = websocket_client.get_alexa_websocketapp()
        self.sync = sync.Sync()
        self.companion_playstate_mgr = plex_companion.PlaystateMgr(
            companion_enabled=utils.settings('plexCompanion') == 'true')
        if utils.settings('plexCompanion') == 'true':
            self.companion_polling = plex_companion.Polling(self.companion_playstate_mgr)
        else:
            self.companion_polling = None

        # Main PKC program loop
        while not self.should_cancel():

            # Check for PKC commands from other Python instances
            plex_command = utils.window('plexkodiconnect.command')
            if plex_command:
                # Commands/user interaction received from other PKC Python
                # instances (default.py and context.py instead of service.py)
                utils.window('plexkodiconnect.command', clear=True)
                task = None
                if plex_command.startswith('PLAY-'):
                    # Add-on path playback!
                    task = playback_starter.PlaybackTask(
                        plex_command.replace('PLAY-', ''))
                elif plex_command.startswith('CONTEXT_menu?'):
                    task = playback_starter.PlaybackTask(
                        'dummy?mode=context_menu&%s'
                        % plex_command.replace('CONTEXT_menu?', ''))
                elif plex_command.startswith('WATCHLIST_ADD?'):
                    task = backgroundthread.FunctionAsTask(
                        self.watchlist_add, None, plex_command.replace('WATCHLIST_ADD?', ''))
                elif plex_command.startswith('WATCHLIST_REMOVE?'):
                    task = backgroundthread.FunctionAsTask(
                        self.watchlist_remove, None, plex_command.replace('WATCHLIST_REMOVE?', ''))
                elif plex_command == 'choose_pms_server':
                    task = backgroundthread.FunctionAsTask(
                        self.choose_pms_server, None)
                elif plex_command == 'switch_plex_user':
                    task = backgroundthread.FunctionAsTask(
                        self.switch_plex_user, None)
                elif plex_command == 'enter_new_pms_address':
                    task = backgroundthread.FunctionAsTask(
                        self.enter_new_pms_address, None)
                elif plex_command == 'toggle_plex_tv_sign_in':
                    task = backgroundthread.FunctionAsTask(
                        self.toggle_plex_tv, None)
                elif plex_command == 'repair-scan':
                    app.SYNC.run_lib_scan = 'repair'
                elif plex_command == 'full-scan':
                    app.SYNC.run_lib_scan = 'full'
                elif plex_command == 'fanart-scan':
                    app.SYNC.run_lib_scan = 'fanart'
                elif plex_command == 'textures-scan':
                    app.SYNC.run_lib_scan = 'textures'
                elif plex_command == 'select-libraries':
                    self.choose_plex_libraries()
                elif plex_command == 'refreshplaylist':
                    self.reset_playlists_and_nodes()
                elif plex_command == 'RESET-PKC':
                    utils.reset()
                elif plex_command == 'EXIT-PKC':
                    LOG.info('Received command from another instance to quit')
                    app.APP.stop_pkc = True
                elif plex_command == 'generate_new_uuid':
                    LOG.info('Generating new UUID for PKC')
                    clientinfo.getDeviceId(reset=True)
                else:
                    raise RuntimeError('Unknown command: %s', plex_command)
                if task:
                    backgroundthread.BGThreader.addTasksToFront([task])
                continue

            if app.APP.suspend:
                xbmc.sleep(100)
                continue

            if app.APP.update_widgets and not xbmc.getCondVisibility('Window.IsMedia'):
                '''
                In case an update happened but we were not on the homescreen
                and now we are, force widgets to update. Prevents cursor from
                moving/jumping in libraries
                '''
                app.APP.update_widgets = False
                xbmc.executebuiltin('UpdateLibrary(video)')

            # Before proceeding, need to make sure:
            # 1. Server is online
            # 2. User is set
            # 3. User has access to the server
            if not app.CONN.online:
                # Not online
                server = app.CONN.server
                if not server:
                    # No server info set in add-on settings
                    pass
                elif not self.connection_check_running:
                    self.connection_check_running = True
                    task = backgroundthread.FunctionAsTask(
                        PF.check_connection,
                        self.on_connection_check,
                        server,
                        verifySSL=app.CONN.verify_ssl_cert)
                    backgroundthread.BGThreader.addTasksToFront([task])
                    continue
            elif not app.ACCOUNT.authenticated:
                # Plex server is online, but we're not yet authenticated
                if not self.auth_running:
                    self.auth_running = True
                    task = backgroundthread.FunctionAsTask(
                        self.authenticate, None)
                    backgroundthread.BGThreader.addTasksToFront([task])
                    continue
            elif not self.startup_completed:
                self.startup_completed = True
                self.pms_ws.start()
                self.sync.start()
                self.companion_playstate_mgr.start()
                if self.companion_polling is not None:
                    self.companion_polling.start()
                self.alexa_ws.start()

            elif app.APP.is_playing:
                skip_plex_markers.check()

            xbmc.sleep(200)

        # EXITING PKC
        # Tell all threads to terminate (e.g. several lib sync threads)
        LOG.debug('Aborting all threads')
        app.APP.stop_pkc = True
        backgroundthread.BGThreader.shutdown(block=False)
        # Load/Reset PKC entirely - important for user/Kodi profile switch
        # Clear video nodes properties
        library_sync.clear_window_vars()
        # Will block until threads have quit
        app.APP.stop_threads()
        # CLEANUP
        # Kodi's xbmc.Monitor() stalls
        # delete xbmc.Player() just to be sure
        del app.APP.monitor
        del app.APP.player


def start():
    DELAY = int(utils.settings('startupDelay'))
    LOG.info("Delaying Plex startup by: %s sec...", DELAY)
    if DELAY and xbmc.Monitor().waitForAbort(DELAY):
        # Start the service
        LOG.info("Abort requested while waiting. PKC not started.")
    else:
        Service().ServiceEntryPoint()
    LOG.info("======== STOP PlexKodiConnect service ========")
