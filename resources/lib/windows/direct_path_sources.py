#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:synopsis: Prompts the user to add network paths and username passwords for
           e.g. smb paths
"""
from logging import getLogger
import re
import socket
import xml.etree.ElementTree as etree

import xbmc

from .. import path_ops, utils

LOG = getLogger('PLEX.direct_path_sources')

SUPPORTED_PROTOCOLS = ('smb', 'nfs', 'http', 'https', 'ftp', 'sftp')
PATH = path_ops.translate_path('special://userdata/')


def get_etree(topelement):
    try:
        xml = utils.etree.parse(
            path_ops.path.join(PATH, '%s.xml' % topelement))
    except IOError:
        # Document is blank or missing
        LOG.info('%s.xml is missing or blank, creating it', topelement)
        root = etree.Element(topelement)
    except utils.ParseError:
        LOG.error('Error parsing %s', topelement)
        # "Kodi cannot parse {0}. PKC will not function correctly. Please visit
        # {1} and correct your file!"
        utils.messageDialog(utils.lang(29999), utils.lang(39716).format(
            '%s.xml' % topelement, 'http://forum.kodi.tv/'))
        return
    else:
        root = xml.getroot()
    return root


def is_valid_hostname(hostname):
    if len(hostname) > 255:
        return False
    if hostname[-1] == ".":
        # strip exactly one dot from the right, if present
        hostname = hostname[:-1]
    allowed = re.compile("(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(x) for x in hostname.split("."))


def is_valid_ip(ip):
    try:
        socket.inet_aton(ip)
        # legal
    except socket.error:
        return False
    return True


def start():
    """
    Hit this function to start entering network credentials
    """
    LOG.info('Editing sources.xml and passwords.xml')
    # Fix for:
    #   DEBUG: Activating window ID: 13000
    #   INFO: Activate of window '13000' refused because there are active modal dialogs
    #   DEBUG: Activating window ID: 13000
    xbmc.executebuiltin("Dialog.Close(all, true)")
    # "In the following window, enter the server's hostname (or IP) where your
    # Plex media resides. Mind the case!"
    utils.messageDialog(utils.lang(29999), utils.lang(30200))
    # "Enter server hostname (or IP)"
    hostname = utils.dialog('input', utils.lang(30201))
    if not hostname:
        return
    hostname = hostname.strip()
    if not is_valid_hostname(hostname) and not is_valid_ip(hostname):
        LOG.error('Entered invalid hostname or IP: %s', hostname)
        # "The hostname or IP '{0}' that you entered is not valid"
        utils.messageDialog(utils.lang(29999),
                            utils.lang(30204).format(hostname))
        return
    # "In the following window, enter the network protocol you would like to
    # use. This is likely 'smb'."
    utils.messageDialog(utils.lang(29999), utils.lang(30202))
    # "Enter network protocol"
    protocol = utils.dialog('input', utils.lang(30203))
    if not protocol:
        return
    protocol = protocol.lower().strip()
    if protocol not in SUPPORTED_PROTOCOLS:
        LOG.error('Entered invalid protocol %s', protocol)
        # "The protocol '{0}' that you entered is not supported."
        utils.messageDialog(utils.lang(29999),
                            utils.lang(30205).format(protocol))
        return
    path = '%s://%s' % (protocol, hostname)
    # Trailing slash at the end
    paths = (path, '%s/' % path)
    # Add hostname to sources.xml, if not already there
    LOG.info('Hostname we are adding to sources.xml and passwords.xml: %s',
             path)
    try:
        with utils.XmlKodiSetting('sources.xml',
                                  force_create=True,
                                  top_element='sources') as xml:
            files = xml.root.find('files')
            if files is None:
                files = etree.SubElement(xml.root, 'files')
                etree.SubElement(files,
                                 'default',
                                 attrib={'pathversion': '1'})
            for source in files:
                entry = source.find('path')
                if entry is None:
                    LOG.debug('Entry is None')
                    continue
                LOG.debug('entry found: %s', entry.text)
                if entry.text in paths:
                    LOG.debug('Already have %s in sources.xml', path)
                    break
            else:
                # Need to add an element for our hostname
                LOG.debug('Adding subelement to sources.xml for %s', hostname)
                source = etree.SubElement(files, 'source')
                etree.SubElement(source, 'name').text = 'PKC %s' % hostname
                etree.SubElement(source,
                                 'path',
                                 attrib={'pathversion': '1'}).text = '%s/' % path
                etree.SubElement(source, 'allowsharing').text = 'false'
                xml.write_xml = True
    except utils.ParseError:
        return
    # Add or change username and password in passwords.xml
    try:
        with utils.XmlKodiSetting('passwords.xml',
                                  force_create=True,
                                  top_element='passwords') as xml:
            for entry in xml.root:
                source = entry.find('from')
                if source is None:
                    continue
                if source.text in paths:
                    LOG.debug('Found an existing passwords.xml entry for %s, '
                              'replacing it',
                              path)
                    xml.root.remove(entry)
            entry = etree.SubElement(xml.root, 'path')
            # "Username"
            user = utils.dialog('input', utils.lang(1014))
            if user is None:
                xml.write_xml = False
                return
            user = user.strip()
            user = utils.quote(user)
            # "Password"
            # May also be blank!! (=user aborts dialog)
            password = utils.dialog('input',
                                    utils.lang(733),
                                    '',
                                    type='{alphanum}',
                                    option='{hide}')
            password = utils.quote(password)
            etree.SubElement(entry,
                             'from',
                             attrib={'pathversion': '1'}).text = f'{path}/'
            login = f'{protocol}://{user}:{password}@{hostname}/'
            etree.SubElement(entry,
                             'to',
                             attrib={'pathversion': '1'}).text = login
            xml.write_xml = True
    except utils.ParseError:
        return
    LOG.info('Successfully completed editing sources.xml and passwords.xml')
