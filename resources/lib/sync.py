#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import xbmc

from .downloadutils import DownloadUtils as DU
from . import library_sync, timing
from . import backgroundthread, utils, artwork, variables as v, app
from . import kodi_db

if library_sync.PLAYLIST_SYNC_ENABLED:
    from . import playlists

LOG = getLogger('PLEX.sync')


class Sync(backgroundthread.KillableThread):
    """
    The one and only library sync thread. Spawn only 1!
    """
    def __init__(self):
        self.sync_successful = False
        self.last_full_sync = 0
        self.metadata_thread = None
        self.image_cache_thread = None
        # Lock used to wait on a full sync, e.g. on initial sync
        # self.lock = backgroundthread.threading.Lock()
        super(Sync, self).__init__()

    def triage_lib_scans(self):
        """
        Decides what to do if app.SYNC.run_lib_scan has been set. E.g. manually
        triggered full or repair syncs
        """
        if app.SYNC.run_lib_scan in ("full", "repair"):
            LOG.info('Full library scan requested, starting')
            show_dialog = True if app.SYNC.run_lib_scan == 'repair' \
                else None
            self.start_library_sync(show_dialog=show_dialog,
                                    repair=app.SYNC.run_lib_scan == 'repair',
                                    block=True)
            if (not self.sync_successful and
                    not self.should_suspend() and
                    not self.should_cancel()):
                # ERROR in library sync
                LOG.warn('Triggered full/repair sync has not been successful')
        elif app.SYNC.run_lib_scan == 'fanart':
            # Only look for missing fanart (No) or refresh all fanart (Yes)
            from .windows import optionsdialog
            refresh = optionsdialog.show(utils.lang(29999),
                                         utils.lang(39223),
                                         utils.lang(39224),  # refresh all
                                         utils.lang(39225)) == 0
            if not self.start_additional_metadata(refresh=refresh):
                # Fanart download already running
                utils.dialog('notification',
                             heading='{plex}',
                             message=utils.lang(30015),
                             icon='{plex}',
                             sound=False)
        elif app.SYNC.run_lib_scan == 'textures':
            LOG.info("Caching of images requested")
            if not utils.yesno_dialog("Image Texture Cache", utils.lang(39250)):
                return
            # ask to reset all existing or not
            if utils.yesno_dialog('Image Texture Cache', utils.lang(39251)):
                kodi_db.reset_cached_images()
            self.start_image_cache_thread()

    def on_library_scan_finished(self, successful):
        """
        Hit this after the full sync has finished
        """
        self.sync_successful = successful
        self.last_full_sync = timing.unix_timestamp()
        if not successful:
            LOG.warn('Could not finish scheduled full sync')
        app.APP.resume_metadata_thread()
        app.APP.resume_caching_thread()

    def start_library_sync(self, show_dialog=None, repair=False, block=False):
        app.APP.suspend_metadata_thread(block=True)
        app.APP.suspend_caching_thread(block=True)
        show_dialog = show_dialog if show_dialog is not None else app.SYNC.sync_dialog
        library_sync.start(show_dialog, repair, self.on_library_scan_finished)

    def start_additional_metadata(self, refresh):
        if not app.SYNC.artwork:
            LOG.info('Not synching Plex PMS artwork, not getting artwork')
            return False
        elif self.metadata_thread is None or not self.metadata_thread.is_alive():
            LOG.info('Start downloading additional metadata with refresh %s',
                     refresh)
            self.metadata_thread = library_sync.MetadataThread(self.on_metadata_finished, refresh)
            self.metadata_thread.start()
            return True
        else:
            LOG.info('Still downloading metadata')
            return False

    @staticmethod
    def on_metadata_finished(successful):
        # FanartTV lookup completed
        if successful:
            # Toggled to "Yes"
            utils.settings('plex_status_fanarttv_lookup', value=utils.lang(107))

    def start_image_cache_thread(self):
        if not utils.settings('enableTextureCache') == "true":
            LOG.info('Image caching has been deactivated')
            return
        if not app.SYNC.artwork:
            LOG.info('Not synching Plex artwork - not caching')
            return
        if self.image_cache_thread and self.image_cache_thread.is_alive():
            self.image_cache_thread.cancel()
            self.image_cache_thread.join()
        self.image_cache_thread = artwork.ImageCachingThread()
        self.image_cache_thread.start()

    def run(self):
        LOG.info("---===### Starting Sync Thread ###===---")
        app.APP.register_thread(self)
        try:
            self._run_internal()
        except Exception:
            utils.ERROR(txt='sync.py crashed', notify=True)
            raise
        finally:
            try:
                app.APP.deregister_thread(self)
            except ValueError:
                pass
            LOG.info("###===--- Sync Thread Stopped ---===###")

    def _run_internal(self):
        install_sync_done = utils.settings('SyncInstallRunDone') == 'true'
        playlist_monitor = None
        initial_sync_done = False
        last_websocket_processing = 0
        # Link to Websocket queue
        queue = app.APP.websocket_queue

        # Check whether we need to reset the Kodi DB
        if install_sync_done:
            current_version = utils.settings('dbCreatedWithVersion')
            if not utils.compare_version(current_version,
                                         v.MIN_DB_VERSION):
                LOG.warn("Db version out of date: %s minimum version "
                         "required: %s", current_version, v.MIN_DB_VERSION)
                # In order to not wait for this thread to suspend
                app.APP.deregister_thread(self)
                # DB out of date. Proceed to recreate?
                if not utils.yesno_dialog(utils.lang(29999),
                                          utils.lang(39401)):
                    LOG.warn("Db version out of date! USER IGNORED!")
                    # PKC may not work correctly until reset
                    utils.messageDialog(utils.lang(29999),
                                        '%s%s' % (utils.lang(29999),
                                                  utils.lang(39402)))
                else:
                    utils.reset(ask_user=False)
                return

        utils.init_dbs()

        while not self.should_cancel():
            # In the event the server goes offline
            if self.should_suspend():
                if self.wait_while_suspended():
                    return
            if not install_sync_done:
                # Very FIRST sync ever upon installation or reset of Kodi DB
                LOG.info('Initial start-up full sync starting')
                xbmc.executebuiltin('InhibitIdleShutdown(true)')
                # This call will block until scan is completed
                self.start_library_sync(show_dialog=True, block=True)
                if self.sync_successful:
                    LOG.info('Initial start-up full sync successful')
                    utils.settings('SyncInstallRunDone', value='true')
                    install_sync_done = True
                    initial_sync_done = True
                    utils.settings('dbCreatedWithVersion', v.ADDON_VERSION)
                    # Reload skin in order to ensure items showing up on Kodi
                    # Homescreen
                    xbmc.executebuiltin('ReloadSkin()')
                    if library_sync.PLAYLIST_SYNC_ENABLED:
                        playlist_monitor = playlists.kodi_playlist_monitor()
                    self.start_additional_metadata(refresh=False)
                    self.start_image_cache_thread()
                else:
                    LOG.error('Initial start-up full sync unsuccessful')
                    self.sleep(1)
                xbmc.executebuiltin('InhibitIdleShutdown(false)')

            elif not initial_sync_done:
                # First sync upon PKC restart. Skipped if very first sync upon
                # PKC installation has been completed
                LOG.info('Doing initial sync on Kodi startup')
                self.start_library_sync(block=True)
                if self.sync_successful:
                    initial_sync_done = True
                    LOG.info('Done initial sync on Kodi startup')
                    if library_sync.PLAYLIST_SYNC_ENABLED:
                        playlist_monitor = playlists.kodi_playlist_monitor()
                    self.start_additional_metadata(refresh=False)
                    self.start_image_cache_thread()
                else:
                    LOG.info('Startup sync has not yet been successful')
                    self.sleep(1)

            # Currently no db scan, so we could start a new scan
            else:
                # Full scan was requested from somewhere else
                if app.SYNC.run_lib_scan is not None:
                    self.triage_lib_scans()
                    # Reset the flag
                    app.SYNC.run_lib_scan = None
                    continue

                # Standard syncs - don't force-show dialogs
                now = timing.unix_timestamp()
                if (now - self.last_full_sync > app.SYNC.full_sync_intervall and
                        not app.APP.is_playing_video):
                    LOG.info('Doing scheduled full library scan')
                    self.start_library_sync()
                else:
                    # Check back whether we should process something Only do
                    # this once a while (otherwise, potentially many screen
                    # refreshes lead to flickering)
                    if (library_sync.WEBSOCKET_MESSAGES and
                            now - last_websocket_processing > 5 and
                            (utils.settings('delayBackgroundSyncWhilePlaying') == "false" or not app.APP.is_playing_video)):
                        last_websocket_processing = now
                        library_sync.process_websocket_messages()
                    # See if there is a PMS message we need to handle
                    try:
                        message = queue.get(block=False)
                    except backgroundthread.queue.Empty:
                        pass
                    # Got a message from PMS; process it
                    else:
                        library_sync.store_websocket_message(message)
                        queue.task_done()
                        # Sleep just a bit
                        self.sleep(0.01)
                        continue
            self.sleep(0.1)
        # Shut down playlist monitoring
        if playlist_monitor:
            playlist_monitor.stop()
        # doUtils could still have a session open due to interrupted sync
        try:
            DU().stopSession()
        except AttributeError:
            pass
