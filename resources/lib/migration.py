#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from builtins import str
from logging import getLogger

from . import variables as v
from . import utils
###############################################################################

LOG = getLogger('PLEX.migration')


def check_migration():
    LOG.info('Checking whether we need to migrate something')
    last_migration = utils.settings('last_migrated_PKC_version')
    # Ensure later migration if user downgraded PKC!
    utils.settings('last_migrated_PKC_version', value=v.ADDON_VERSION)

    if last_migration == '':
        LOG.info('New, clean PKC installation - no migration necessary')
        return
    elif last_migration == v.ADDON_VERSION:
        LOG.info('Already migrated to PKC version %s' % v.ADDON_VERSION)
        return

    if not utils.compare_version(last_migration, '1.8.2'):
        LOG.info('Migrating to version 1.8.1')
        # Set the new PKC theMovieDB key
        utils.settings('themoviedbAPIKey',
                       value='19c90103adb9e98f2172c6a6a3d85dc4')

    if not utils.compare_version(last_migration, '2.0.25'):
        LOG.info('Migrating to version 2.0.24')
        # Need to re-connect with PMS to pick up on plex.direct URIs
        utils.settings('ipaddress', value='')
        utils.settings('port', value='')

    if not utils.compare_version(last_migration, '2.7.6'):
        LOG.info('Migrating to version 2.7.5')
        from .library_sync.sections import delete_files
        delete_files()

    if not utils.compare_version(last_migration, '2.8.3'):
        LOG.info('Migrating to version 2.8.2')
        from .library_sync import sections
        sections.clear_window_vars()
        sections.delete_videonode_files()

    if not utils.compare_version(last_migration, '2.8.7'):
        LOG.info('Migrating to version 2.8.6')
        # Need to delete the UNIQUE index that prevents creating several
        # playlist entries with the same kodi_hash
        from .plex_db import PlexDB
        with PlexDB() as plexdb:
            plexdb.cursor.execute('DROP INDEX IF EXISTS ix_playlists_3')
            # Index will be automatically recreated on next PKC startup

    if not utils.compare_version(last_migration, '2.8.9'):
        LOG.info('Migrating to version 2.8.8')
        from .library_sync import sections
        sections.clear_window_vars()
        sections.delete_videonode_files()

    if not utils.compare_version(last_migration, '2.9.3'):
        LOG.info('Migrating to version 2.9.2')
        # Re-sync all playlists to Kodi
        from .playlists import remove_synced_playlists
        remove_synced_playlists()

    if not utils.compare_version(last_migration, '2.9.7'):
        LOG.info('Migrating to version 2.9.6')
        # Allow for a new "Direct Stream" setting (number 2), so shift the
        # last setting for "force transcoding"
        current_playback_type = utils.cast(int, utils.settings('playType')) or 0
        if current_playback_type == 2:
            current_playback_type = 3
        utils.settings('playType', value=str(current_playback_type))

    if not utils.compare_version(last_migration, '2.9.8'):
        LOG.info('Migrating to version 2.9.7')
        # Force-scan every single item in the library - seems like we could
        # loose some recently added items otherwise
        # Caused by 65a921c3cc2068c4a34990d07289e2958f515156
        from . import library_sync
        library_sync.force_full_sync()

    if not utils.compare_version(last_migration, '2.11.3'):
        LOG.info('Migrating to version 2.11.2')
        # Re-sync all playlists to Kodi
        from .playlists import remove_synced_playlists
        remove_synced_playlists()

    if not utils.compare_version(last_migration, '2.12.2'):
        LOG.info('Migrating to version 2.12.1')
        # Sign user out to make sure he needs to sign in again
        utils.settings('username', value='')
        utils.settings('userid', value='')
        utils.settings('plex_restricteduser', value='')
        utils.settings('accessToken', value='')
        utils.settings('plexAvatar', value='')

    utils.settings('last_migrated_PKC_version', value=v.ADDON_VERSION)
