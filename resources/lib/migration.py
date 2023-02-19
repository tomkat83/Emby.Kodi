#!/usr/bin/env python
# -*- coding: utf-8 -*-
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

    if not utils.compare_version(last_migration, '3.0.4'):
        LOG.info('Migrating to version 3.0.4')
        # Add an additional column `trailer_synced` in the Plex movie table
        from .plex_db import PlexDB
        with PlexDB() as plexdb:
            query = 'ALTER TABLE movie ADD trailer_synced BOOLEAN'
            plexdb.cursor.execute(query)
            # Index will be automatically recreated on next PKC startup

    if not utils.compare_version(last_migration, '3.7.0'):
        LOG.info('Migrating to version 3.7.0')
        from .library_sync import sections
        sections.delete_videonode_files()
        utils.reboot_kodi()

    utils.settings('last_migrated_PKC_version', value=v.ADDON_VERSION)
