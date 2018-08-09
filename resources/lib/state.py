#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
THREAD SAFE
"""
from __future__ import absolute_import, division, unicode_literals
from threading import Lock, RLock


# LOCKS
####################
# Need to lock all methods and functions messing with Plex Companion subscribers
LOCK_SUBSCRIBER = RLock()
# Need to lock everything messing with Kodi/PKC playqueues
LOCK_PLAYQUEUES = RLock()
# Necessary to temporarily hold back librarysync/websocket listener when doing
# a full sync
LOCK_PLAYLISTS = Lock()

# Quit PKC
STOP_PKC = False


# Usually triggered by another Python instance - will have to be set (by
# polling window) through e.g. librarysync thread
SUSPEND_LIBRARY_THREAD = False
# Set if user decided to cancel sync
STOP_SYNC = False
# Set e.g. during media playback if PKC should not do any syncs. Will NOT
# suspend synching of playstate progress
SUSPEND_SYNC = False
# Could we access the paths?
PATH_VERIFIED = False
# Set if a Plex-Kodi DB sync is being done - along with
# window('plex_dbScan') set to 'true'
DB_SCAN = False
# Plex Media Server Status - along with window('plex_serverStatus')
PMS_STATUS = False
# When the userclient needs to wait
SUSPEND_USER_CLIENT = False
# Plex home user? Then "False". Along with window('plex_restricteduser')
RESTRICTED_USER = False
# Direct Paths (True) or Addon Paths (False)? Along with
# window('useDirectPaths')
DIRECT_PATHS = False
# Shall we replace custom user ratings with the number of versions available?
INDICATE_MEDIA_VERSIONS = False
# Do we need to run a special library scan?
RUN_LIB_SCAN = None
# Number of items to fetch and display in widgets
FETCH_PMS_ITEM_NUMBER = None
# Hack to force Kodi widget for "in progress" to show up if it was empty before
FORCE_RELOAD_SKIN = True

# Stemming from the PKC settings.xml
# Shall we show Kodi dialogs when synching?
SYNC_DIALOG = True
# Shall Kodi show dialogs for syncing/caching images? (e.g. images left to sync)
IMAGE_SYNC_NOTIFICATIONS = True
# Only sync specific Plex playlists to Kodi?
SYNC_SPECIFIC_PLEX_PLAYLISTS = False
# Only sync specific Kodi playlists to Plex?
SYNC_SPECIFIC_KODI_PLAYLISTS = False
# Is synching of Plex music enabled?
ENABLE_MUSIC = True
# How often shall we sync?
FULL_SYNC_INTERVALL = 0
# Background Sync disabled?
BACKGROUND_SYNC_DISABLED = False
# How long shall we wait with synching a new item to make sure Plex got all
# metadata?
BACKGROUNDSYNC_SAFTYMARGIN = 0
# How many threads to download Plex metadata on sync?
SYNC_THREAD_NUMBER = 0
# What's the time offset between the PMS and Kodi?
KODI_PLEX_TIME_OFFSET = 0.0

# Path remapping mechanism (e.g. smb paths)
# Do we replace \\myserver\path to smb://myserver/path?
REPLACE_SMB_PATH = False
# Do we generally remap?
REMAP_PATH = False
# Mappings for REMAP_PATH:
remapSMBmovieOrg = None
remapSMBmovieNew = None
remapSMBtvOrg = None
remapSMBtvNew = None
remapSMBmusicOrg = None
remapSMBmusicNew = None
remapSMBphotoOrg = None
remapSMBphotoNew = None

# Shall we verify SSL certificates?
VERIFY_SSL_CERT = False
# Do we have an ssl certificate for PKC we need to use?
SSL_CERT_PATH = None
# Along with window('plex_authenticated')
AUTHENTICATED = False
# plex.tv username
PLEX_USERNAME = None
# Token for that user for plex.tv
PLEX_TOKEN = None
# Plex token for the active PMS for the active user
# (might be diffent to PLEX_TOKEN)
PMS_TOKEN = None
# Plex ID of that user (e.g. for plex.tv) as a STRING
PLEX_USER_ID = None
# Token passed along, e.g. if playback initiated by Plex Companion. Might be
# another user playing something! Token identifies user
PLEX_TRANSIENT_TOKEN = None

# Plex Companion Queue()
COMPANION_QUEUE = None
# Command Pipeline Queue()
COMMAND_PIPELINE_QUEUE = None
# Websocket_client queue to communicate with librarysync
WEBSOCKET_QUEUE = None

# Which Kodi player is/has been active? (either int 1, 2 or 3)
ACTIVE_PLAYERS = set()
# Failsafe for throwing an empty video back to Kodi's setResolvedUrl to set
# up our own playlist from the very beginning
PKC_CAUSED_STOP = False
# Flag if the 0 length PKC video has already failed so we can start resolving
# playback (set in player.py)
PKC_CAUSED_STOP_DONE = True

# Kodi player states - here, initial values are set
PLAYER_STATES = {
    0: {},
    1: {},
    2: {}
}
# The LAST playstate once playback is finished
OLD_PLAYER_STATES = {
    0: {},
    1: {},
    2: {}
}
# "empty" dict for the PLAYER_STATES above. Use copy.deepcopy to duplicate!
PLAYSTATE = {
    'type': None,
    'time': {
        'hours': 0,
        'minutes': 0,
        'seconds': 0,
        'milliseconds': 0},
    'totaltime': {
        'hours': 0,
        'minutes': 0,
        'seconds': 0,
        'milliseconds': 0},
    'speed': 0,
    'shuffled': False,
    'repeat': 'off',
    'position': None,
    'playlistid': None,
    'currentvideostream': -1,
    'currentaudiostream': -1,
    'subtitleenabled': False,
    'currentsubtitle': -1,
    'file': None,
    'kodi_id': None,
    'kodi_type': None,
    'plex_id': None,
    'plex_type': None,
    'container_key': None,
    'volume': 100,
    'muted': False,
    'playmethod': None,
    'playcount': None
}
PLAYED_INFO = {}
# Set by SpecialMonitor - did user choose to resume playback or start from the
# beginning?
RESUME_PLAYBACK = False
# Was the playback initiated by the user using the Kodi context menu?
CONTEXT_MENU_PLAY = False
# Set by context menu - shall we force-transcode the next playing item?
FORCE_TRANSCODE = False

# Kodi webserver details
WEBSERVER_PORT = 8080
WEBSERVER_USERNAME = 'kodi'
WEBSERVER_PASSWORD = ''
WEBSERVER_HOST = 'localhost'
