# -*- coding: utf-8 -*-

###############################################################################

import logging
from json import loads

from xbmc import Monitor, Player, sleep

import downloadutils
import plexdb_functions as plexdb
from utils import window, settings, CatchExceptions, tryDecode, tryEncode
from PlexFunctions import scrobble
from kodidb_functions import get_kodiid_from_filename
from PlexAPI import API
from variables import REMAP_TYPE_FROM_PLEXTYPE
import state

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


class KodiMonitor(Monitor):

    def __init__(self, callback):
        self.mgr = callback
        self.doUtils = downloadutils.DownloadUtils().downloadUrl
        self.xbmcplayer = Player()
        self.playqueue = self.mgr.playqueue
        Monitor.__init__(self)
        log.info("Kodi monitor started.")

    def onScanStarted(self, library):
        log.debug("Kodi library scan %s running." % library)
        if library == "video":
            window('plex_kodiScan', value="true")

    def onScanFinished(self, library):
        log.debug("Kodi library scan %s finished." % library)
        if library == "video":
            window('plex_kodiScan', clear=True)

    def onSettingsChanged(self):
        """
        Monitor the PKC settings for changes made by the user
        """
        # settings: window-variable
        items = {
            'logLevel': 'plex_logLevel',
            'enableContext': 'plex_context',
            'plex_restricteduser': 'plex_restricteduser',
            'dbSyncIndicator': 'dbSyncIndicator',
            'remapSMB': 'remapSMB',
            'replaceSMB': 'replaceSMB',
            'force_transcode_pix': 'plex_force_transcode_pix',
            'fetch_pms_item_number': 'fetch_pms_item_number'
        }
        # Path replacement
        for typus in REMAP_TYPE_FROM_PLEXTYPE.values():
            for arg in ('Org', 'New'):
                key = 'remapSMB%s%s' % (typus, arg)
                items[key] = key
        # Reset the window variables from the settings variables
        for settings_value, window_value in items.iteritems():
            if window(window_value) != settings(settings_value):
                log.debug('PKC settings changed: %s is now %s'
                          % (settings_value, settings(settings_value)))
                window(window_value, value=settings(settings_value))
                if settings_value == 'fetch_pms_item_number':
                    log.info('Requesting playlist/nodes refresh')
                    window('plex_runLibScan', value="views")

    @CatchExceptions(warnuser=False)
    def onNotification(self, sender, method, data):

        if data:
            data = loads(data, 'utf-8')
            log.debug("Method: %s Data: %s" % (method, data))

        if method == "Player.OnPlay":
            self.PlayBackStart(data)

        elif method == "Player.OnStop":
            # Should refresh our video nodes, e.g. on deck
            # xbmc.executebuiltin('ReloadSkin()')
            pass

        elif method == "VideoLibrary.OnUpdate":
            # Manually marking as watched/unwatched
            playcount = data.get('playcount')
            item = data.get('item')

            try:
                kodiid = item['id']
                item_type = item['type']
            except (KeyError, TypeError):
                log.info("Item is invalid for playstate update.")
            else:
                # Send notification to the server.
                with plexdb.Get_Plex_DB() as plexcur:
                    plex_dbitem = plexcur.getItem_byKodiId(kodiid, item_type)
                try:
                    itemid = plex_dbitem[0]
                except TypeError:
                    log.error("Could not find itemid in plex database for a "
                              "video library update")
                else:
                    # Stop from manually marking as watched unwatched, with
                    # actual playback.
                    if window('plex_skipWatched%s' % itemid) == "true":
                        # property is set in player.py
                        window('plex_skipWatched%s' % itemid, clear=True)
                    else:
                        # notify the server
                        if playcount > 0:
                            scrobble(itemid, 'watched')
                        else:
                            scrobble(itemid, 'unwatched')

        elif method == "VideoLibrary.OnRemove":
            pass

        elif method == "System.OnSleep":
            # Connection is going to sleep
            log.info("Marking the server as offline. SystemOnSleep activated.")
            window('plex_online', value="sleep")

        elif method == "System.OnWake":
            # Allow network to wake up
            sleep(10000)
            window('plex_onWake', value="true")
            window('plex_online', value="false")

        elif method == "GUI.OnScreensaverDeactivated":
            if settings('dbSyncScreensaver') == "true":
                sleep(5000)
                window('plex_runLibScan', value="full")

        elif method == "System.OnQuit":
            log.info('Kodi OnQuit detected - shutting down')
            state.STOP_PKC = True

    def PlayBackStart(self, data):
        """
        Called whenever a playback is started
        """
        # Get currently playing file - can take a while. Will be utf-8!
        try:
            currentFile = self.xbmcplayer.getPlayingFile()
        except:
            currentFile = None
            count = 0
            while currentFile is None:
                sleep(100)
                try:
                    currentFile = self.xbmcplayer.getPlayingFile()
                except:
                    pass
                if count == 50:
                    log.info("No current File, cancel OnPlayBackStart...")
                    return
                else:
                    count += 1
        # Just to be on the safe side
        currentFile = tryDecode(currentFile)
        log.debug("Currently playing file is: %s" % currentFile)

        # Get the type of media we're playing
        try:
            typus = data['item']['type']
        except (TypeError, KeyError):
            log.info("Item is invalid for PMS playstate update.")
            return
        log.debug("Playing itemtype is (or appears to be): %s" % typus)

        # Try to get a Kodi ID
        # If PKC was used - native paths, not direct paths
        plex_id = window('plex_%s.itemid' % tryEncode(currentFile))
        # Get rid of the '' if the window property was not set
        plex_id = None if not plex_id else plex_id
        kodiid = None
        if plex_id is None:
            log.debug('Did not get Plex id from window properties')
            try:
                kodiid = data['item']['id']
            except (TypeError, KeyError):
                log.debug('Did not get a Kodi id from Kodi, darn')
        # For direct paths, if we're not streaming something
        # When using Widgets, Kodi doesn't tell us shit so we need this hack
        if (kodiid is None and plex_id is None and typus != 'song'
                and not currentFile.startswith('http')):
            (kodiid, typus) = get_kodiid_from_filename(currentFile)
            if kodiid is None:
                return

        if plex_id is None:
            # Get Plex' item id
            with plexdb.Get_Plex_DB() as plexcursor:
                plex_dbitem = plexcursor.getItem_byKodiId(kodiid, typus)
            try:
                plex_id = plex_dbitem[0]
            except TypeError:
                log.info("No Plex id returned for kodiid %s. Aborting playback"
                         " report" % kodiid)
                return
        log.debug("Found Plex id %s for Kodi id %s for type %s"
                  % (plex_id, kodiid, typus))

        # Switch subtitle tracks if applicable
        subtitle = window('plex_%s.subtitle' % tryEncode(currentFile))
        if window(tryEncode('plex_%s.playmethod' % currentFile)) \
                == 'Transcode' and subtitle:
            if window('plex_%s.subtitle' % currentFile) == 'None':
                self.xbmcplayer.showSubtitles(False)
            else:
                self.xbmcplayer.setSubtitleStream(int(subtitle))

        # Set some stuff if Kodi initiated playback
        if ((settings('useDirectPaths') == "1" and not typus == "song")
                or
                (typus == "song" and settings('enableMusic') == "true")):
            if self.StartDirectPath(plex_id,
                                    typus,
                                    tryEncode(currentFile)) is False:
                log.error('Could not initiate monitoring; aborting')
                return

        # Save currentFile for cleanup later and to be able to access refs
        window('plex_lastPlayedFiled', value=currentFile)
        window('plex_currently_playing_itemid', value=plex_id)
        window("plex_%s.itemid" % tryEncode(currentFile), value=plex_id)
        log.info('Finish playback startup')

    def StartDirectPath(self, plex_id, type, currentFile):
        """
        Set some additional stuff if playback was initiated by Kodi, not PKC
        """
        xml = self.doUtils('{server}/library/metadata/%s' % plex_id)
        try:
            xml[0].attrib
        except:
            log.error('Did not receive a valid XML for plex_id %s.' % plex_id)
            return False
        # Setup stuff, because playback was started by Kodi, not PKC
        api = API(xml[0])
        listitem = api.CreateListItemFromPlexItem()
        api.set_playback_win_props(currentFile, listitem)
        if type == "song" and settings('streamMusic') == "true":
            window('plex_%s.playmethod' % currentFile, value="DirectStream")
        else:
            window('plex_%s.playmethod' % currentFile, value="DirectPlay")
        log.debug('Window properties set for direct paths!')
