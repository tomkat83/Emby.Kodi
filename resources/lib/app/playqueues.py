#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

import xbmc

from .. import variables as v


LOG = getLogger('PLEX.playqueue')


class Playqueue(object):
    """
    PKC object to represent PMS playQueues and Kodi playlist for queueing

    playlistid = None     [int] Kodi playlist id (0, 1, 2)
    type = None           [str] Kodi type: 'audio', 'video', 'picture'
    kodi_pl = None        Kodi xbmc.PlayList object
    items = []            [list] of Playlist_Items
    id = None             [str] Plex playQueueID, unique Plex identifier
    version = None        [int] Plex version of the playQueue
    selectedItemID = None
                          [str] Plex selectedItemID, playing element in queue
    selectedItemOffset = None
                          [str] Offset of the playing element in queue
    shuffled = 0          [int] 0: not shuffled, 1: ??? 2: ???
    repeat = 0            [int] 0: not repeated, 1: ??? 2: ???

    If Companion playback is initiated by another user:
    plex_transient_token = None
    """
    kind = 'playQueue'

    def __init__(self):
        self.id = None
        self.type = None
        self.playlistid = None
        self.kodi_pl = None
        self.items = []
        self.version = None
        self.selectedItemID = None
        self.selectedItemOffset = None
        self.shuffled = 0
        self.repeat = 0
        self.plex_transient_token = None
        # Need a hack for detecting swaps of elements
        self.old_kodi_pl = []
        # Did PKC itself just change the playqueue so the PKC playqueue monitor
        # should not pick up any changes?
        self.pkc_edit = False
        # Workaround to avoid endless loops of detecting PL clears
        self._clear_list = []
        # To keep track if Kodi playback was initiated from a Kodi playlist
        # There are a couple of pitfalls, unfortunately...
        self.kodi_playlist_playback = False

    def __repr__(self):
        answ = ("{{"
                "'playlistid': {self.playlistid}, "
                "'id': {self.id}, "
                "'version': {self.version}, "
                "'type': '{self.type}', "
                "'selectedItemID': {self.selectedItemID}, "
                "'selectedItemOffset': {self.selectedItemOffset}, "
                "'shuffled': {self.shuffled}, "
                "'repeat': {self.repeat}, "
                "'kodi_playlist_playback': {self.kodi_playlist_playback}, "
                "'pkc_edit': {self.pkc_edit}, ".format(self=self))
        # Since list.__repr__ will return string, not unicode
        return answ + "'items': {self.items}}}".format(self=self)

    def is_pkc_clear(self):
        """
        Returns True if PKC has cleared the Kodi playqueue just recently.
        Then this clear will be ignored from now on
        """
        try:
            self._clear_list.pop()
        except IndexError:
            return False
        else:
            return True

    def clear(self, kodi=True):
        """
        Resets the playlist object to an empty playlist.

        Pass kodi=False in order to NOT clear the Kodi playqueue
        """
        # kodi monitor's on_clear method will only be called if there were some
        # items to begin with
        if kodi and self.kodi_pl.size() != 0:
            self._clear_list.append(None)
            self.kodi_pl.clear()  # Clear Kodi playlist object
        self.items = []
        self.id = None
        self.version = None
        self.selectedItemID = None
        self.selectedItemOffset = None
        self.shuffled = 0
        self.repeat = 0
        self.plex_transient_token = None
        self.old_kodi_pl = []
        self.kodi_playlist_playback = False
        LOG.debug('Playlist cleared: %s', self)

    def position_from_plex_id(self, plex_id):
        """
        Returns the position [int] for the very first item with plex_id [int]
        (Plex seems uncapable of adding the same element multiple times to a
        playqueue or playlist)

        Raises KeyError if not found
        """
        for position, item in enumerate(self.items):
            if item.plex_id == plex_id:
                break
        else:
            raise KeyError('Did not find plex_id %s in %s', plex_id, self)
        return position


class Playqueues(list):

    def __init__(self):
        super().__init__()
        for i, typus in enumerate((v.KODI_PLAYLIST_TYPE_AUDIO,
                                   v.KODI_PLAYLIST_TYPE_VIDEO,
                                   v.KODI_PLAYLIST_TYPE_PHOTO)):
            playqueue = Playqueue()
            playqueue.playlistid = i
            playqueue.type = typus
            # Initialize each Kodi playlist
            if typus == v.KODI_PLAYLIST_TYPE_AUDIO:
                playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
            elif typus == v.KODI_PLAYLIST_TYPE_VIDEO:
                playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            else:
                # Currently, only video or audio playqueues available
                playqueue.kodi_pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                # Overwrite 'picture' with 'photo'
                playqueue.type = v.KODI_TYPE_PHOTO
            self.append(playqueue)

    @property
    def audio(self):
        return self[0]

    @property
    def video(self):
        return self[1]

    @property
    def photo(self):
        return self[2]

    def from_kodi_playlist_type(self, kodi_playlist_type):
        """
        Returns the playqueue according to the kodi_playlist_type ('video',
        'audio', 'picture') passed in
        """
        if kodi_playlist_type == v.KODI_PLAYLIST_TYPE_AUDIO:
            return self[0]
        elif kodi_playlist_type == v.KODI_PLAYLIST_TYPE_VIDEO:
            return self[1]
        elif kodi_playlist_type == v.KODI_PLAYLIST_TYPE_PHOTO:
            return self[2]
        else:
            raise ValueError('Unknown kodi_playlist_type: %s' % kodi_playlist_type)

    def from_kodi_type(self, kodi_type):
        """
        Pass in the kodi_type (e.g. the string 'movie') to get the correct
        playqueue (either video, audio or picture)
        """
        if kodi_type == v.KODI_TYPE_VIDEO:
            return self[1]
        elif kodi_type == v.KODI_TYPE_MOVIE:
            return self[1]
        elif kodi_type == v.KODI_TYPE_EPISODE:
            return self[1]
        elif kodi_type == v.KODI_TYPE_SEASON:
            return self[1]
        elif kodi_type == v.KODI_TYPE_SHOW:
            return self[1]
        elif kodi_type == v.KODI_TYPE_CLIP:
            return self[1]
        elif kodi_type == v.KODI_TYPE_SONG:
            return self[0]
        elif kodi_type == v.KODI_TYPE_ALBUM:
            return self[0]
        elif kodi_type == v.KODI_TYPE_ARTIST:
            return self[0]
        elif kodi_type == v.KODI_TYPE_AUDIO:
            return self[0]
        elif kodi_type == v.KODI_TYPE_PHOTO:
            return self[2]
        else:
            raise ValueError('Unknown kodi_type: %s' % kodi_type)

    def from_plex_type(self, plex_type):
        """
        Pass in the plex_type (e.g. the string 'movie') to get the correct
        playqueue (either video, audio or picture)
        """
        if plex_type == v.PLEX_TYPE_VIDEO:
            return self[1]
        elif plex_type == v.PLEX_TYPE_MOVIE:
            return self[1]
        elif plex_type == v.PLEX_TYPE_EPISODE:
            return self[1]
        elif plex_type == v.PLEX_TYPE_SEASON:
            return self[1]
        elif plex_type == v.PLEX_TYPE_SHOW:
            return self[1]
        elif plex_type == v.PLEX_TYPE_CLIP:
            return self[1]
        elif plex_type == v.PLEX_TYPE_SONG:
            return self[0]
        elif plex_type == v.PLEX_TYPE_ALBUM:
            return self[0]
        elif plex_type == v.PLEX_TYPE_ARTIST:
            return self[0]
        elif plex_type == v.PLEX_TYPE_AUDIO:
            return self[0]
        elif plex_type == v.PLEX_TYPE_PHOTO:
            return self[2]
        else:
            raise ValueError('Unknown plex_type: %s' % plex_type)
