#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Monitors the Kodi playqueue and adjusts the Plex playqueue accordingly
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
import xbmc

from . import utils
from . import playlist_func as PL
from . import plex_functions as PF
from .plex_api import API
from . import json_rpc as js
from . import variables as v
from . import state

###############################################################################
LOG = getLogger('PLEX.playqueue')

PLUGIN = 'plugin://%s' % v.ADDON_ID

# Our PKC playqueues (3 instances of Playqueue_Object())
PLAYQUEUES = []
###############################################################################


def init_playqueues():
    """
    Call this once on startup to initialize the PKC playqueue objects in
    the list PLAYQUEUES
    """
    if PLAYQUEUES:
        LOG.debug('Playqueues have already been initialized')
        return
    # Initialize Kodi playqueues
    with state.LOCK_PLAYQUEUES:
        for i in (0, 1, 2):
            # Just in case the Kodi response is not sorted correctly
            for queue in js.get_playlists():
                if queue['playlistid'] != i:
                    continue
                playqueue = PL.Playqueue_Object()
                playqueue.playlistid = i
                playqueue.type = queue['type']
                # Initialize each Kodi playlist
                if playqueue.type == v.KODI_TYPE_AUDIO:
                    playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
                elif playqueue.type == v.KODI_TYPE_VIDEO:
                    playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                else:
                    # Currently, only video or audio playqueues available
                    playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                    # Overwrite 'picture' with 'photo'
                    playqueue.type = v.KODI_TYPE_PHOTO
                PLAYQUEUES.append(playqueue)
    LOG.debug('Initialized the Kodi playqueues: %s', PLAYQUEUES)


def get_playqueue_from_type(kodi_playlist_type):
    """
    Returns the playqueue according to the kodi_playlist_type ('video',
    'audio', 'picture') passed in
    """
    for playqueue in PLAYQUEUES:
        if playqueue.type == kodi_playlist_type:
            break
    else:
        raise ValueError('Wrong playlist type passed in: %s',
                         kodi_playlist_type)
    return playqueue


def init_playqueue_from_plex_children(plex_id, transient_token=None):
    """
    Init a new playqueue e.g. from an album. Alexa does this

    Returns the playqueue
    """
    xml = PF.GetAllPlexChildren(plex_id)
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not download the PMS xml for %s', plex_id)
        return
    playqueue = get_playqueue_from_type(
        v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[xml[0].attrib['type']])
    playqueue.clear()
    for i, child in enumerate(xml):
        api = API(child)
        PL.add_item_to_playlist(playqueue, i, plex_id=api.plex_id())
    playqueue.plex_transient_token = transient_token
    LOG.debug('Firing up Kodi player')
    xbmc.Player().play(playqueue.kodi_pl, None, False, 0)
    return playqueue


@utils.thread_methods(add_suspends=['PMS_STATUS'])
class PlayqueueMonitor(Thread):
    """
    Unfortunately, Kodi does not tell if items within a Kodi playqueue
    (playlist) are swapped. This is what this monitor is for. Don't replace
    this mechanism till Kodi's implementation of playlists has improved
    """
    def _compare_playqueues(self, playqueue, new):
        """
        Used to poll the Kodi playqueue and update the Plex playqueue if needed
        """
        old = list(playqueue.items)
        index = list(range(0, len(old)))
        LOG.debug('Comparing new Kodi playqueue %s with our play queue %s',
                  new, old)
        for i, new_item in enumerate(new):
            if (new_item['file'].startswith('plugin://') and
                    not new_item['file'].startswith(PLUGIN)):
                # Ignore new media added by other addons
                continue
            for j, old_item in enumerate(old):
                if self.stopped():
                    # Chances are that we got an empty Kodi playlist due to
                    # Kodi exit
                    return
                try:
                    if (old_item.file.startswith('plugin://') and
                            not old_item.file.startswith(PLUGIN)):
                        # Ignore media by other addons
                        continue
                except AttributeError:
                    # were not passed a filename; ignore
                    pass
                if 'id' in new_item:
                    identical = (old_item.kodi_id == new_item['id'] and
                                 old_item.kodi_type == new_item['type'])
                else:
                    try:
                        plex_id = utils.REGEX_PLEX_ID.findall(new_item['file'])[0]
                    except IndexError:
                        LOG.debug('Comparing paths directly as a fallback')
                        identical = old_item.file == new_item['file']
                    else:
                        identical = plex_id == old_item.plex_id
                if j == 0 and identical:
                    del old[j], index[j]
                    break
                elif identical:
                    LOG.debug('Playqueue item %s moved to position %s',
                              i + j, i)
                    try:
                        PL.move_playlist_item(playqueue, i + j, i)
                    except PL.PlaylistError:
                        LOG.error('Could not modify playqueue positions')
                        LOG.error('This is likely caused by mixing audio and '
                                  'video tracks in the Kodi playqueue')
                    del old[j], index[j]
                    break
            else:
                LOG.debug('Detected new Kodi element at position %s: %s ',
                          i, new_item)
                try:
                    if playqueue.id is None:
                        PL.init_plex_playqueue(playqueue, kodi_item=new_item)
                    else:
                        PL.add_item_to_plex_playqueue(playqueue,
                                                      i,
                                                      kodi_item=new_item)
                except PL.PlaylistError:
                    # Could not add the element
                    pass
                except IndexError:
                    # This is really a hack - happens when using Addon Paths
                    # and repeatedly  starting the same element. Kodi will then
                    # not pass kodi id nor file path AND will also not
                    # start-up playback. Hence kodimonitor kicks off playback.
                    # Also see kodimonitor.py - _playlist_onadd()
                    pass
                else:
                    for j in range(i, len(index)):
                        index[j] += 1
        for i in reversed(index):
            if self.stopped():
                # Chances are that we got an empty Kodi playlist due to
                # Kodi exit
                return
            LOG.debug('Detected deletion of playqueue element at pos %s', i)
            try:
                PL.delete_playlist_item_from_PMS(playqueue, i)
            except PL.PlaylistError:
                LOG.error('Could not delete PMS element from position %s', i)
                LOG.error('This is likely caused by mixing audio and '
                          'video tracks in the Kodi playqueue')
        LOG.debug('Done comparing playqueues')

    def run(self):
        stopped = self.stopped
        suspended = self.suspended
        LOG.info("----===## Starting PlayqueueMonitor ##===----")
        while not stopped():
            while suspended():
                if stopped():
                    break
                xbmc.sleep(1000)
            with state.LOCK_PLAYQUEUES:
                for playqueue in PLAYQUEUES:
                    kodi_pl = js.playlist_get_items(playqueue.playlistid)
                    if playqueue.old_kodi_pl != kodi_pl:
                        if playqueue.id is None and (not state.DIRECT_PATHS or
                                                     state.CONTEXT_MENU_PLAY):
                            # Only initialize if directly fired up using direct
                            # paths. Otherwise let default.py do its magic
                            LOG.debug('Not yet initiating playback')
                        else:
                            # compare old and new playqueue
                            self._compare_playqueues(playqueue, kodi_pl)
                        playqueue.old_kodi_pl = list(kodi_pl)
            xbmc.sleep(200)
        LOG.info("----===## PlayqueueMonitor stopped ##===----")
