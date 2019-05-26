#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Monitors the Kodi playqueue and adjusts the Plex playqueue accordingly
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import copy

from .common import PlayqueueError, PlaylistItem, PLAYQUEUES
from .. import backgroundthread, json_rpc as js, utils, app


LOG = getLogger('PLEX.playqueue_monitor')


class PlayqueueMonitor(backgroundthread.KillableThread):
    """
    Unfortunately, Kodi does not tell if items within a Kodi playqueue
    (playlist) are swapped. This is what this monitor is for. Don't replace
    this mechanism till Kodi's implementation of playlists has improved
    """
    def _compare_playqueues(self, playqueue, new_kodi_playqueue):
        """
        Used to poll the Kodi playqueue and update the Plex playqueue if needed
        """
        old = list(playqueue.items)
        # We might append to new_kodi_playqueue but will need the original
        # still back in the main loop
        new = copy.deepcopy(new_kodi_playqueue)
        index = list(range(0, len(old)))
        LOG.debug('Comparing new Kodi playqueue %s with our play queue %s',
                  new, old)
        for i, new_item in enumerate(new):
            if (new_item['file'].startswith('plugin://') and
                    not new_item['file'].startswith(PLUGIN)):
                # Ignore new media added by other addons
                continue
            for j, old_item in enumerate(old):
                if self.isCanceled():
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
                        plex_id = int(utils.REGEX_PLEX_ID.findall(new_item['file'])[0])
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
                        playqueue.plex_move_item(i + j, i)
                    except PlayqueueError:
                        LOG.error('Could not modify playqueue positions')
                        LOG.error('This is likely caused by mixing audio and '
                                  'video tracks in the Kodi playqueue')
                    del old[j], index[j]
                    break
            else:
                playlistitem = PlaylistItem(kodi_item=new_item)
                LOG.debug('Detected new Kodi element at position %s: %s ',
                          i, playlistitem)
                try:
                    if playqueue.id is None:
                        playqueue.init(playlistitem)
                    else:
                        playqueue.plex_add_item(playlistitem, i)
                except PlayqueueError:
                    LOG.warn('Couldnt add new item to Plex: %s', playlistitem)
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
            if self.isCanceled():
                # Chances are that we got an empty Kodi playlist due to
                # Kodi exit
                return
            LOG.debug('Detected deletion of playqueue element at pos %s', i)
            try:
                playqueue.plex_remove_item(i)
            except PlayqueueError:
                LOG.error('Could not delete PMS element from position %s', i)
                LOG.error('This is likely caused by mixing audio and '
                          'video tracks in the Kodi playqueue')
        LOG.debug('Done comparing playqueues')

    def run(self):
        LOG.info("----===## Starting PlayqueueMonitor ##===----")
        app.APP.register_thread(self)
        try:
            self._run()
        finally:
            app.APP.deregister_thread(self)
            LOG.info("----===## PlayqueueMonitor stopped ##===----")

    def _run(self):
        while not self.isCanceled():
            if self.wait_while_suspended():
                return
            with app.APP.lock_playqueues:
                for playqueue in PLAYQUEUES:
                    kodi_pl = js.playlist_get_items(playqueue.playlistid)
                    playqueue.old_kodi_pl = list(kodi_pl)
                    continue
                    if playqueue.old_kodi_pl != kodi_pl:
                        if playqueue.id is None and (not app.SYNC.direct_paths or
                                                     app.PLAYSTATE.context_menu_play):
                            # Only initialize if directly fired up using direct
                            # paths. Otherwise let default.py do its magic
                            LOG.debug('Not yet initiating playback')
                        else:
                            # compare old and new playqueue
                            self._compare_playqueues(playqueue, kodi_pl)
            app.APP.monitor.waitForAbort(0.2)
