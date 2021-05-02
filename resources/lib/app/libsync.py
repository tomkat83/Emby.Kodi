#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .. import utils


def remove_trailing_slash(path):
    """
    Removes trailing slashes or backslashes from path [unicode], and is NOT
    dependent on os.path
    """
    if '/' in path:
        path = path[:-1] if path.endswith('/') else path
    else:
        path = path[:-1] if path.endswith('\\') else path
    return path


class Sync(object):
    def __init__(self, entrypoint=False):
        # Direct Paths (True) or Addon Paths (False)?
        self.direct_paths = None
        # Is synching of Plex music enabled?
        self.enable_music = None
        # Do we sync artwork from the PMS to Kodi?
        self.artwork = None
        # Path remapping mechanism (e.g. smb paths)
        # Do we replace \\myserver\path to smb://myserver/path?
        self.replace_smb_path = None
        # Do we generally remap?
        self.remap_path = None
        self.force_transcode_pix = None
        # Mappings for REMAP_PATH:
        self.remapSMBmovieOrg = None
        self.remapSMBmovieNew = None
        self.remapSMBtvOrg = None
        self.remapSMBtvNew = None
        self.remapSMBmusicOrg = None
        self.remapSMBmusicNew = None
        self.remapSMBphotoOrg = None
        self.remapSMBphotoNew = None
        # Escape path?
        self.escape_path = None
        self.escape_path_safe_chars = None
        # Shall we replace custom user ratings with the number of versions available?
        self.indicate_media_versions = None
        # Will sync movie trailer differently: either play trailer directly or show
        # all the Plex extras for the user to choose
        self.show_extras_instead_of_playing_trailer = None
        # Only sync specific Plex playlists to Kodi?
        self.sync_specific_plex_playlists = None
        # Only sync specific Kodi playlists to Plex?
        self.sync_specific_kodi_playlists = None
        # Shall we show Kodi dialogs when synching?
        self.sync_dialog = None

        # How often shall we sync?
        self.full_sync_intervall = None
        # How long shall we wait with synching a new item to make sure Plex got all
        # metadata?
        self.backgroundsync_saftymargin = None
        # How many threads to download Plex metadata on sync?
        self.sync_thread_number = None

        # Shall Kodi show dialogs for syncing/caching images? (e.g. images left
        # to sync)
        self.image_sync_notifications = None

        # Do we need to run a special library scan?
        self.run_lib_scan = None
        # Set if user decided to cancel sync
        self.stop_sync = False
        # Do we check whether we can access a media file?
        self.check_media_file_existence = False
        # Could we access the paths?
        self.path_verified = False

        # List of Section() items representing Plex library sections
        self._sections = []
        # List of section_ids we're synching to Kodi - will be automatically
        # re-built if sections are set a-new
        self.section_ids = set()

        self.load()

    @property
    def sections(self):
        return self._sections

    @sections.setter
    def sections(self, sections):
        self._sections = sections
        # Sets are faster when using "in" test than lists
        self.section_ids = set([x.section_id for x in sections if x.sync_to_kodi])

    def load(self):
        self.direct_paths = utils.settings('useDirectPaths') == '1'
        self.check_media_file_existence = \
            utils.settings('check_media_file_existence') == '1'
        self.enable_music = utils.settings('enableMusic') == 'true'
        self.artwork = utils.settings('usePlexArtwork') == 'true'
        self.replace_smb_path = utils.settings('replaceSMB') == 'true'
        self.remap_path = utils.settings('remapSMB') == 'true'
        self.remapSMBmovieOrg = remove_trailing_slash(utils.settings('remapSMBmovieOrg'))
        self.remapSMBmovieNew = remove_trailing_slash(utils.settings('remapSMBmovieNew'))
        self.remapSMBtvOrg = remove_trailing_slash(utils.settings('remapSMBtvOrg'))
        self.remapSMBtvNew = remove_trailing_slash(utils.settings('remapSMBtvNew'))
        self.remapSMBmusicOrg = remove_trailing_slash(utils.settings('remapSMBmusicOrg'))
        self.remapSMBmusicNew = remove_trailing_slash(utils.settings('remapSMBmusicNew'))
        self.remapSMBphotoOrg = remove_trailing_slash(utils.settings('remapSMBphotoOrg'))
        self.remapSMBphotoNew = remove_trailing_slash(utils.settings('remapSMBphotoNew'))
        self.escape_path = utils.settings('escapePath') == 'true'
        self.escape_path_safe_chars = utils.settings('escapePathSafeChars')
        self.indicate_media_versions = utils.settings('indicate_media_versions') == "true"
        self.sync_specific_plex_playlists = utils.settings('syncSpecificPlexPlaylists') == 'true'
        self.sync_specific_kodi_playlists = utils.settings('syncSpecificKodiPlaylists') == 'true'
        self.sync_thread_number = int(utils.settings('syncThreadNumber'))
        self.reload()

    def reload(self):
        """
        Any settings unrelated to syncs to the Kodi database - can thus be
        safely reset without a Kodi reboot
        """
        self.sync_dialog = utils.settings('dbSyncIndicator') == 'true'
        self.full_sync_intervall = int(utils.settings('fullSyncInterval')) * 60
        self.backgroundsync_saftymargin = int(utils.settings('backgroundsync_saftyMargin'))

        self.image_sync_notifications = utils.settings('imageSyncNotifications') == 'true'

        self.force_transcode_pix = utils.settings('force_transcode_pix') == 'true'
        # Trailers in Kodi DB will remain UNTIL DB is reset!
        self.show_extras_instead_of_playing_trailer = utils.settings('showExtrasInsteadOfTrailer') == 'true'
