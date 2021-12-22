#!/usr/bin/env python
# -*- coding: utf-8 -*-
import xml.etree.ElementTree as etree

from . import utils


def pkc_sources_hack():
    # Hack to make PKC Kodi master lock compatible
    try:
        with utils.XmlKodiSetting('sources.xml',
                                  force_create=True,
                                  top_element='sources') as xml:
            changed = False
            for extension in ('smb://', 'nfs://'):
                root = xml.set_setting(['video'])
                changed = add_source(root, extension) or changed
            if changed:
                xml.write_xml = True
    except utils.ParseError:
        pass
    return changed


def add_source(root, source_path):
    changed = False
    # Originally, 2 sources were necessary for the PKC Masterlock Hack
    count = 1
    for source in root.findall('.//path'):
        if source.text == source_path:
            count -= 1
        if count == 0:
            # sources already set
            break
    else:
        # Missing smb:// occurences, re-add.
        changed = True
        for _ in range(0, count):
            source = etree.SubElement(root, 'source')
            etree.SubElement(
                source,
                'name').text = "PlexKodiConnect Masterlock Hack"
            etree.SubElement(
                source,
                'path',
                {'pathversion': "1"}).text = source_path
            etree.SubElement(source, 'allowsharing').text = "true"
    return changed
