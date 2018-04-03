# -*- coding: utf-8 -*-
from logging import getLogger
from re import compile as re_compile
from xml.etree.ElementTree import ParseError

from utils import XmlKodiSetting, reboot_kodi, language as lang
from PlexFunctions import get_plex_sections
from PlexAPI import API
import variables as v

###############################################################################
LOG = getLogger("PLEX." + __name__)

REGEX_MUSICPATH = re_compile(r'''^\^(.+)\$$''')
###############################################################################


def excludefromscan_music_folders():
    """
    Gets a complete list of paths for music libraries from the PMS. Sets them
    to be excluded in the advancedsettings.xml from being scanned by Kodi.
    Existing keys will be replaced

    Reboots Kodi if new library detected
    """
    xml = get_plex_sections()
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not get Plex sections')
        return
    # Build paths
    paths = []
    api = API(item=None)
    for library in xml:
        if library.attrib['type'] != v.PLEX_TYPE_ARTIST:
            # Only look at music libraries
            continue
        for location in library:
            if location.tag == 'Location':
                path = api.validate_playurl(location.attrib['path'],
                                            typus=v.PLEX_TYPE_ARTIST,
                                            omit_check=True)
                paths.append(__turn_to_regex(path))
    try:
        with XmlKodiSetting('advancedsettings.xml',
                            force_create=True,
                            top_element='advancedsettings') as xml:
            parent = xml.set_setting(['audio', 'excludefromscan'])
            for path in paths:
                for element in parent:
                    if element.text == path:
                        # Path already excluded
                        break
                else:
                    LOG.info('New Plex music library detected: %s', path)
                    xml.set_setting(['audio', 'excludefromscan', 'regexp'],
                                    value=path, append=True)
            # We only need to reboot if we ADD new paths!
            reboot = xml.write_xml
            # Delete obsolete entries
            for element in parent:
                for path in paths:
                    if element.text == path:
                        break
                else:
                    LOG.info('Deleting music library from advancedsettings: %s',
                             element.text)
                    parent.remove(element)
    except (ParseError, IOError):
        LOG.error('Could not adjust advancedsettings.xml')
        reboot = False
    if reboot is True:
        #  'New Plex music library detected. Sorry, but we need to
        #  restart Kodi now due to the changes made.'
        reboot_kodi(lang(39711))


def __turn_to_regex(path):
    """
    Turns a path into regex expression to be fed to Kodi's advancedsettings.xml
    """
    # Make sure we have a slash or backslash at the end of the path
    if '/' in path:
        if not path.endswith('/'):
            path = '%s/' % path
    else:
        if not path.endswith('\\'):
            path = '%s\\' % path
    # Need to escape backslashes
    path = path.replace('\\', '\\\\')
    # Beginning of path only needs to be similar
    return '^%s' % path
