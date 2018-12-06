#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from . import utils
from .plex_api import API
from . import variables as v

###############################################################################
LOG = getLogger('PLEX.music')
###############################################################################


def excludefromscan_music_folders(xml):
    """
    Gets a complete list of paths for music libraries from the PMS. Sets them
    to be excluded in the advancedsettings.xml from being scanned by Kodi.
    Existing keys will be replaced
    xml: etree XML PMS answer containing all library sections

    Reboots Kodi if new library detected
    """
    paths = []
    reboot = False
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
        with utils.XmlKodiSetting(
                'advancedsettings.xml',
                force_create=True,
                top_element='advancedsettings') as xml_file:
            parent = xml_file.set_setting(['audio', 'excludefromscan'])
            for path in paths:
                for element in parent:
                    if element.text == path:
                        # Path already excluded
                        break
                else:
                    LOG.info('New Plex music library detected: %s', path)
                    xml_file.set_setting(['audio', 'excludefromscan', 'regexp'],
                                         value=path,
                                         append=True)
            if paths:
                # We only need to reboot if we ADD new paths!
                reboot = xml_file.write_xml
            # Delete obsolete entries
            # Make sure we're not saving an empty audio-excludefromscan
            xml_file.write_xml = reboot
            for element in parent:
                for path in paths:
                    if element.text == path:
                        break
                else:
                    LOG.info('Deleting music library from advancedsettings: %s',
                             element.text)
                    parent.remove(element)
                    xml_file.write_xml = True
    except (utils.ParseError, IOError):
        LOG.error('Could not adjust advancedsettings.xml')
    if reboot is True:
        #  'New Plex music library detected. Sorry, but we need to
        #  restart Kodi now due to the changes made.'
        utils.reboot_kodi(utils.lang(39711))


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
