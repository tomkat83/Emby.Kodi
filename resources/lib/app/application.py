#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import queue
from threading import Lock, RLock

import xbmc

from .. import utils

LOG = getLogger('PLEX.app')


class App(object):
    """
    This class is used to store variables across PKC modules
    """
    def __init__(self, entrypoint=False):
        self.fetch_pms_item_number = None
        # All thread instances
        self.threads = []
        if entrypoint:
            self.load_entrypoint()
        else:
            self.reload()
            # Quit PKC?
            self.stop_pkc = False
            # This will suspend the main thread also
            self.suspend = False
            # Update Kodi widgets
            self.update_widgets = False
            # Need to lock all methods and functions messing with Plex Companion subscribers
            self.lock_subscriber = RLock()
            # Need to lock everything messing with Kodi/PKC playqueues
            self.lock_playqueues = RLock()
            # Necessary to temporarily hold back librarysync/websocket listener when doing
            # a full sync
            self.lock_playlists = Lock()

            # Plex Companion Queue()
            self.companion_queue = queue.Queue(maxsize=100)
            # Websocket_client queue to communicate with librarysync
            self.websocket_queue = queue.Queue()
            # xbmc.Monitor() instance from kodimonitor.py
            self.monitor = None
            # xbmc.Player() instance
            self.player = None
            # Instance of MetadataThread()
            self.metadata_thread = None
            # Instance of ImageCachingThread()
            self.caching_thread = None
            # Dialog to skip markers such as intros and credits
            self.skip_markers_dialog = None

    @property
    def is_playing(self):
        return self.player.isPlaying() == 1

    @property
    def is_playing_video(self):
        return self.player.isPlayingVideo() == 1

    def register_metadata_thread(self, thread):
        self.metadata_thread = thread
        self.threads.append(thread)

    def deregister_metadata_thread(self, thread):
        self.metadata_thread.unblock_callers()
        self.metadata_thread = None
        self.threads.remove(thread)

    def suspend_metadata_thread(self, block=True):
        try:
            self.metadata_thread.suspend(block=block)
        except AttributeError:
            pass

    def resume_metadata_thread(self):
        try:
            self.metadata_thread.resume()
        except AttributeError:
            pass

    def register_caching_thread(self, thread):
        self.caching_thread = thread
        self.threads.append(thread)

    def deregister_caching_thread(self, thread):
        self.caching_thread.unblock_callers()
        self.caching_thread = None
        self.threads.remove(thread)

    def suspend_caching_thread(self, block=True):
        try:
            self.caching_thread.suspend(block=block)
        except AttributeError:
            pass

    def resume_caching_thread(self):
        try:
            self.caching_thread.resume()
        except AttributeError:
            pass

    def register_thread(self, thread):
        """
        Hit with thread [backgroundthread.Killablethread instance] to register
        any and all threads
        """
        self.threads.append(thread)

    def deregister_thread(self, thread):
        """
        Sync thread has done it's work and is e.g. about to die
        """
        thread.unblock_callers()
        self.threads.remove(thread)

    def suspend_threads(self, block=True):
        """
        Suspend all threads' activity with or without blocking.
        Returns True only if PKC shutdown requested
        """
        LOG.debug('Suspending threads: %s', self.threads)
        for thread in self.threads:
            thread.suspend()
        if block:
            while True:
                for thread in self.threads:
                    if not thread.is_suspended():
                        LOG.debug('Waiting for thread to suspend: %s', thread)
                        # Send suspend signal again in case self.threads
                        # changed
                        thread.suspend(block=True)
                else:
                    break
        return self.monitor.abortRequested()

    def resume_threads(self):
        """
        Resume all thread activity with or without blocking.
        Returns True only if PKC shutdown requested
        """
        LOG.debug('Resuming threads: %s', self.threads)
        for thread in self.threads:
            thread.resume()
        return self.monitor.abortRequested()

    def stop_threads(self, block=True):
        """
        Stop all threads. Will block until all threads are stopped
        Will NOT quit if PKC should exit!
        """
        LOG.debug('Killing threads: %s', self.threads)
        for thread in self.threads:
            thread.cancel()
        if block:
            while self.threads:
                LOG.debug('Waiting for threads to exit: %s', self.threads)
                if xbmc.sleep(100):
                    return True

    def reload(self):
        # Number of items to fetch and display in widgets
        self.fetch_pms_item_number = int(utils.settings('fetch_pms_item_number'))

    def load_entrypoint(self):
        self.fetch_pms_item_number = int(utils.settings('fetch_pms_item_number'))
