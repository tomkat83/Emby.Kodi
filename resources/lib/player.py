# -*- coding: utf-8 -*-

###############################################################################
from logging import getLogger
import copy

import xbmc

import kodidb_functions as kodidb
import plexdb_functions as plexdb
from downloadutils import DownloadUtils as DU
from plexbmchelper.subscribers import LOCKER
from utils import kodi_time_to_millis, unix_date_to_kodi, unix_timestamp
import variables as v
import state

###############################################################################

LOG = getLogger("PLEX." + __name__)

###############################################################################


@LOCKER.lockthis
def playback_cleanup(ended=False):
    """
    PKC cleanup after playback ends/is stopped. Pass ended=True if Kodi
    completely finished playing an item (because we will get and use wrong
    timing data otherwise)
    """
    LOG.debug('playback_cleanup called')
    # We might have saved a transient token from a user flinging media via
    # Companion (if we could not use the playqueue to store the token)
    state.PLEX_TRANSIENT_TOKEN = None
    for playerid in state.ACTIVE_PLAYERS:
        status = state.PLAYER_STATES[playerid]
        # Remember the last played item later
        state.OLD_PLAYER_STATES[playerid] = copy.deepcopy(status)
        # Stop transcoding
        if status['playmethod'] == 'Transcode':
            LOG.debug('Tell the PMS to stop transcoding')
            DU().downloadUrl(
                '{server}/video/:/transcode/universal/stop',
                parameters={'session': v.PKC_MACHINE_IDENTIFIER})
        if playerid == 1:
            # Bookmarks might not be pickup up correctly, so let's do them
            # manually. Applies to addon paths, but direct paths might have
            # started playback via PMS
            _record_playstate(status, ended)
        # Reset the player's status
        state.PLAYER_STATES[playerid] = copy.deepcopy(state.PLAYSTATE)
    # As all playback has halted, reset the players that have been active
    state.ACTIVE_PLAYERS = []
    LOG.debug('Finished PKC playback cleanup')


def _record_playstate(status, ended):
    if not status['plex_id']:
        LOG.debug('No Plex id found to record playstate for status %s', status)
        return
    with plexdb.Get_Plex_DB() as plex_db:
        kodi_db_item = plex_db.getItem_byId(status['plex_id'])
    if kodi_db_item is None:
        # Item not (yet) in Kodi library
        LOG.debug('No playstate update due to Plex id not found: %s', status)
        return
    totaltime = float(kodi_time_to_millis(status['totaltime'])) / 1000
    if ended:
        progress = 0.99
        time = v.IGNORE_SECONDS_AT_START + 1
    else:
        time = float(kodi_time_to_millis(status['time'])) / 1000
        try:
            progress = time / totaltime
        except ZeroDivisionError:
            progress = 0.0
        LOG.debug('Playback progress %s (%s of %s seconds)',
                  progress, time, totaltime)
    playcount = status['playcount']
    last_played = unix_date_to_kodi(unix_timestamp())
    if playcount is None:
        LOG.debug('playcount not found, looking it up in the Kodi DB')
        with kodidb.GetKodiDB('video') as kodi_db:
            playcount = kodi_db.get_playcount(kodi_db_item[1])
        playcount = 0 if playcount is None else playcount
    if time < v.IGNORE_SECONDS_AT_START:
        LOG.debug('Ignoring playback less than %s seconds',
                  v.IGNORE_SECONDS_AT_START)
        # Annoying Plex bug - it'll reset an already watched video to unwatched
        playcount = None
        last_played = None
        time = 0
    elif progress >= v.MARK_PLAYED_AT:
        LOG.debug('Recording entirely played video since progress > %s',
                  v.MARK_PLAYED_AT)
        playcount += 1
        time = 0
    with kodidb.GetKodiDB('video') as kodi_db:
        kodi_db.addPlaystate(kodi_db_item[1],
                             time,
                             totaltime,
                             playcount,
                             last_played)
    # Hack to force "in progress" widget to appear if it wasn't visible before
    if (state.FORCE_RELOAD_SKIN and
            xbmc.getCondVisibility('Window.IsVisible(Home.xml)')):
        LOG.debug('Refreshing skin to update widgets')
        xbmc.executebuiltin('ReloadSkin()')


class PKC_Player(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        LOG.info("Started playback monitor.")

    def onPlayBackStarted(self):
        """
        Will be called when xbmc starts playing a file.
        """
        pass

    def onPlayBackPaused(self):
        """
        Will be called when playback is paused
        """
        pass

    def onPlayBackResumed(self):
        """
        Will be called when playback is resumed
        """
        pass

    def onPlayBackSeek(self, time, seekOffset):
        """
        Will be called when user seeks to a certain time during playback
        """
        pass

    def onPlayBackStopped(self):
        """
        Will be called when playback is stopped by the user
        """
        LOG.debug("ONPLAYBACK_STOPPED")
        playback_cleanup()

    def onPlayBackEnded(self):
        """
        Will be called when playback ends due to the media file being finished
        """
        LOG.debug("ONPLAYBACK_ENDED")
        if state.PKC_CAUSED_STOP is True:
            state.PKC_CAUSED_STOP = False
            LOG.debug('PKC caused this playback stop - ignoring')
        else:
            playback_cleanup(ended=True)
