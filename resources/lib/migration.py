from logging import getLogger
import variables as v
from utils import compare_version, settings
###############################################################################

log = getLogger("PLEX."+__name__)


def check_migration():
    log.info('Checking whether we need to migrate something')
    last_migration = settings('last_migrated_PKC_version')
    if last_migration == v.ADDON_VERSION:
        log.info('Already migrated to PKC version %s' % v.ADDON_VERSION)
        # Ensure later migration if user downgraded PKC!
        settings('last_migrated_PKC_version', value=v.ADDON_VERSION)
        return

    if not compare_version(v.ADDON_VERSION, '1.8.2'):
        log.info('Migrating to version 1.8.1')
        # Set the new PKC theMovieDB key
        settings('themoviedbAPIKey', value='19c90103adb9e98f2172c6a6a3d85dc4')

    if not compare_version(v.ADDON_VERSION, '2.0.25'):
        log.info('Migrating to version 2.0.24')
        # Need to re-connect with PMS to pick up on plex.direct URIs
        settings('ipaddress', value='')
        settings('port', value='')

    settings('last_migrated_PKC_version', value=v.ADDON_VERSION)
