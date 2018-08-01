#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import Queue
import time

from ..watchdog import events
from ..watchdog.observers import Observer
from ..watchdog.utils.bricks import OrderedSetQueue

from .. import path_ops
from .. import variables as v
###############################################################################
LOG = getLogger('PLEX.playlists.common')

# These filesystem events are considered similar
SIMILAR_EVENTS = (events.EVENT_TYPE_CREATED, events.EVENT_TYPE_MODIFIED)
###############################################################################


class PlaylistError(Exception):
    """
    The one main exception thrown if anything goes awry
    """
    pass


class Playlist(object):
    """
    Class representing a synced Playlist with info for both Kodi and Plex.
    Attributes:
    Plex:
        plex_id: unicode
        plex_name: unicode
        plex_updatedat: unicode

    Kodi:
        kodi_path: unicode
        kodi_filename: unicode
        kodi_extension: unicode
        kodi_type: unicode
        kodi_hash: unicode

    Testing for a Playlist() returns ONLY True if all the following attributes
    are set; 2 playlists are only equal if all attributes are equal:
        plex_id
        plex_name
        plex_updatedat
        kodi_path
        kodi_filename
        kodi_type
        kodi_hash
    """
    def __init__(self):
        # Plex
        self.plex_id = None
        self.plex_name = None
        self.plex_updatedat = None
        # Kodi
        self._kodi_path = None
        self.kodi_filename = None
        self.kodi_extension = None
        self.kodi_type = None
        self.kodi_hash = None

    def __repr__(self):
        return ("{{"
                "'plex_id': {self.plex_id}, "
                "'plex_name': '{self.plex_name}', "
                "'kodi_type': '{self.kodi_type}', "
                "'kodi_filename': '{self.kodi_filename}', "
                "'kodi_path': '{self._kodi_path}', "
                "'plex_updatedat': {self.plex_updatedat}, "
                "'kodi_hash': '{self.kodi_hash}'"
                "}}").format(self=self)

    def __str__(self):
        return self.__repr__()

    def __bool__(self):
        return (self.plex_id and self.plex_updatedat and self.plex_name and
                self._kodi_path and self.kodi_filename and self.kodi_type and
                self.kodi_hash)

    # Used for comparison of playlists
    @property
    def key(self):
        return (self.plex_id, self.plex_updatedat, self.plex_name,
                self._kodi_path, self.kodi_filename, self.kodi_type,
                self.kodi_hash)

    def __eq__(self, playlist):
        return self.key == playlist.key

    def __ne__(self, playlist):
        return self.key != playlist.key

    @property
    def kodi_path(self):
        return self._kodi_path

    @kodi_path.setter
    def kodi_path(self, path):
        if not isinstance(path, unicode):
            raise RuntimeError('Path not in unicode: %s' % path)
        f = path_ops.path.basename(path)
        try:
            self.kodi_filename, self.kodi_extension = f.split('.', 1)
        except ValueError:
            LOG.error('Trying to set invalid path: %s', path)
            raise PlaylistError('Invalid path: %s' % path)
        if path.startswith(v.PLAYLIST_PATH_VIDEO):
            self.kodi_type = v.KODI_TYPE_VIDEO_PLAYLIST
        elif path.startswith(v.PLAYLIST_PATH_MUSIC):
            self.kodi_type = v.KODI_TYPE_AUDIO_PLAYLIST
        else:
            LOG.error('Playlist type not supported for %s', path)
            raise PlaylistError('Playlist type not supported: %s' % path)
        if not self.plex_name:
            self.plex_name = self.kodi_filename
        self._kodi_path = path


class PlaylistQueue(OrderedSetQueue):
    """
    OrderedSetQueue that drops all directory events immediately
    """
    def _put(self, item):
        if item[0].is_directory:
            self.unfinished_tasks -= 1
        else:
            # Can't use super as OrderedSetQueue is old style class
            OrderedSetQueue._put(self, item)


class PlaylistObserver(Observer):
    """
    PKC implementation, overriding the dispatcher. PKC will wait for the
    duration timeout (in seconds) AFTER receiving a filesystem event. A new
    ("non-similar") event will reset the timer.
    Creating and modifying will be regarded as equal.
    """
    def __init__(self, *args, **kwargs):
        super(PlaylistObserver, self).__init__(*args, **kwargs)
        # Drop the same events that get into the queue even if there are other
        # events in between these similar events. Ignore directory events
        # completely
        self._event_queue = PlaylistQueue()

    @staticmethod
    def _pkc_similar_events(event1, event2):
        if event1 == event2:
            return True
        elif (event1.src_path == event2.src_path and
              event1.event_type in SIMILAR_EVENTS and
              event2.event_type in SIMILAR_EVENTS):
            # Set created and modified events to equal
            return True
        return False

    def _dispatch_iterator(self, event_queue, timeout):
        """
        This iterator will block for timeout (seconds) until an event is
        received or raise Queue.Empty.
        """
        event, watch = event_queue.get(block=True, timeout=timeout)
        event_queue.task_done()
        start = time.time()
        while time.time() - start < timeout:
            try:
                new_event, new_watch = event_queue.get(block=False)
            except Queue.Empty:
                time.sleep(0.2)
            else:
                event_queue.task_done()
                start = time.time()
                if self._pkc_similar_events(new_event, event):
                    continue
                else:
                    yield event, watch
                    event, watch = new_event, new_watch
        yield event, watch

    def dispatch_events(self, event_queue, timeout):
        for event, watch in self._dispatch_iterator(event_queue, timeout):
            # This is copy-paste of original code
            with self._lock:
                # To allow unschedule/stop and safe removal of event handlers
                # within event handlers itself, check if the handler is still
                # registered after every dispatch.
                for handler in list(self._handlers.get(watch, [])):
                    if handler in self._handlers.get(watch, []):
                        handler.dispatch(event)
