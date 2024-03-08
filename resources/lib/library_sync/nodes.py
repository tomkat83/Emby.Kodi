#!/usr/bin/env python
# -*- coding: utf-8 -*-
from urllib.parse import urlencode

import xml.etree.ElementTree as etree
from .. import variables as v, utils

ICON_PATH = 'special://home/addons/plugin.video.plexkodiconnect/icon.png'
RECOMMENDED_SCORE_LOWER_BOUND = 7

# Logic of the following nodes:
# Note that node_type will be used to construct the nodes library xml by the
# function node_<node_type> below
# (node_type,
#  label/node name,
#  args for PKC add-on callback,
#  Kodi "content",
#  )
NODE_TYPES = {
    v.PLEX_TYPE_MOVIE: (
        ('plex_ondeck',
         utils.lang(39500),  # "On Deck"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/onDeck',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('ondeck',
         utils.lang(39502),  # "PKC On Deck (faster)"
         {},
         v.CONTENT_TYPE_MOVIE),
        ('recent',
         utils.lang(30174),  # "Recently Added"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/recentlyAdded',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('all',
         '{self.name}',  # We're using this section's name
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/all',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('recommended',
         utils.lang(30230),  # "Recommended"
         {
              'mode': 'browseplex',
              'key': ('/library/sections/{self.section_id}&%s'
                      % urlencode({'sort': 'rating:desc'})),
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('genres',
         utils.lang(135),  # "Genres"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/genre',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('sets',
         utils.lang(39501),  # "Collections"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/collection',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('random',
         utils.lang(30227),  # "Random"
         {
              'mode': 'browseplex',
              'key': ('/library/sections/{self.section_id}&%s'
                      % urlencode({'sort': 'random'})),
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('lastplayed',
         utils.lang(568),  # "Last played"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/recentlyViewed',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('watchlist',
         utils.lang(39212),  # "Watchlist"
         {
              'mode': 'watchlist',
              'key': '/library/sections/{self.section_id}/watchlist',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('browse',
         utils.lang(39702),  # "Browse by folder"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/folder',
              'plex_type': '{self.section_type}',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_MOVIE),
        ('more',
         utils.lang(22082),  # "More..."
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_FILE),
    ),
    ###########################################################
    v.PLEX_TYPE_SHOW: (
        ('plex_ondeck',
         utils.lang(39500),  # "On Deck"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/onDeck',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_EPISODE),
        ('recent',
         utils.lang(30174),  # "Recently Added"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/recentlyAdded',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_EPISODE),
        ('all',
         '{self.name}',  # We're using this section's name
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/all',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_SHOW),
        ('recommended',
         utils.lang(30230),  # "Recommended"
         {
              'mode': 'browseplex',
              'key': ('/library/sections/{self.section_id}&%s'
                      % urlencode({'sort': 'rating:desc'})),
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_SHOW),
        ('genres',
         utils.lang(135),  # "Genres"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/genre',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_SHOW),
        ('plex_sets',
         utils.lang(39501),  # "Collections"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/collection',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_SHOW),  # There are no sets/collections for shows with Kodi
        ('random',
         utils.lang(30227),  # "Random"
         {
              'mode': 'browseplex',
              'key': ('/library/sections/{self.section_id}&%s'
                      % urlencode({'sort': 'random'})),
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_SHOW),
        ('lastplayed',
         utils.lang(568),  # "Last played"
         {
              'mode': 'browseplex',
              'key': ('/library/sections/{self.section_id}/recentlyViewed&%s'
                      % urlencode({'type': v.PLEX_TYPE_NUMBER_FROM_PLEX_TYPE[v.PLEX_TYPE_EPISODE]})),
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_EPISODE),
        ('watchlist',
         utils.lang(39212),  # "Watchlist"
         {
              'mode': 'watchlist',
              'key': '/library/sections/{self.section_id}/watchlist',
              'section_id': '{self.section_id}'
         },
         v.CONTENT_TYPE_SHOW),
        ('browse',
         utils.lang(39702),  # "Browse by folder"
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}/folder',
              'section_id': '{self.section_id}',
         },
         v.CONTENT_TYPE_EPISODE),
        ('more',
         utils.lang(22082),  # "More..."
         {
              'mode': 'browseplex',
              'key': '/library/sections/{self.section_id}',
              'section_id': '{self.section_id}',
         },
         v.CONTENT_TYPE_FILE),
    ),
}


def node_ondeck(section, node_name, args=None):
    """
    For movies only - returns in-progress movies sorted by last played
    """
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    etree.SubElement(xml, 'rule', attrib={'field': 'inprogress',
                                          'operator': 'true'})
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml, 'limit').text = utils.settings('widgetLimit')
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'descending'}).text = 'lastplayed'
    return xml


def node_recent(section, node_name, args=None):
    xml = etree.Element('node',
                        attrib={'order': str(section.order),
                                'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    if ((section.section_type == v.PLEX_TYPE_SHOW and
            utils.settings('TVShowWatched') == 'false') or
        (section.section_type == v.PLEX_TYPE_MOVIE and
            utils.settings('MovieShowWatched') == 'false')):
        # Adds an additional rule if user deactivated the PKC setting
        # "Recently Added: Also show already watched episodes"
        # or
        # "Recently Added: Also show already watched episodes"
        rule = etree.SubElement(xml, 'rule', attrib={'field': 'playcount',
                                                     'operator': 'is'})
        etree.SubElement(rule, 'value').text = '0'
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml, 'limit').text = utils.settings('widgetLimit')
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'descending'}).text = 'dateadded'
    return xml


def node_all(section, node_name, args=None):
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'ascending'}).text = 'sorttitle'
    return xml


def node_recommended(section, node_name, args=None):
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    # rule = etree.SubElement(xml, 'rule', attrib={'field': 'rating',
    #                                              'operator': 'greaterthan'})
    # etree.SubElement(rule, 'value').text = unicode(RECOMMENDED_SCORE_LOWER_BOUND)
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml, 'limit').text = utils.settings('widgetLimit')
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'descending'}).text = 'rating'
    return xml


def node_genres(section, node_name, args=None):
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'ascending'}).text = 'sorttitle'
    etree.SubElement(xml, 'group').text = 'genres'
    return xml


def node_sets(section, node_name, args=None):
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    # "Collections"
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'ascending'}).text = 'sorttitle'
    etree.SubElement(xml, 'group').text = 'sets'
    return xml


def node_random(section, node_name, args=None):
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml, 'limit').text = utils.settings('widgetLimit')
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'ascending'}).text = 'random'
    return xml


def node_lastplayed(section, node_name, args=None):
    xml = etree.Element('node', attrib={'order': str(section.order),
                                        'type': 'filter'})
    etree.SubElement(xml, 'match').text = 'all'
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'tag',
                                                 'operator': 'is'})
    etree.SubElement(rule, 'value').text = section.name
    rule = etree.SubElement(xml, 'rule', attrib={'field': 'playcount',
                                                 'operator': 'greaterthan'})
    etree.SubElement(rule, 'value').text = '0'
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml, 'limit').text = utils.settings('widgetLimit')
    etree.SubElement(xml,
                     'order',
                     attrib={'direction':
                             'descending'}).text = 'lastplayed'
    return xml


def _folder_template(section, node_name, args):
    """
    Template for type=folder, see https://kodi.wiki/view/Video_nodes
    Idea is that the path points back to plugin://...
    """
    xml = etree.Element('node',
                        attrib={'order': str(section.order),
                                'type': 'folder'})
    etree.SubElement(xml, 'label').text = node_name
    etree.SubElement(xml, 'icon').text = ICON_PATH
    etree.SubElement(xml, 'content').text = section.content
    etree.SubElement(xml, 'path').text = section.addon_path(args)
    return xml


def node_plex_ondeck(section, node_name, args):
    return _folder_template(section, node_name, args)


def node_browse(section, node_name, args):
    return _folder_template(section, node_name, args)


def node_more(section, node_name, args):
    return _folder_template(section, node_name, args)


def node_plex_sets(section, node_name, args):
    return _folder_template(section, node_name, args)


def node_watchlist(section, node_name, args):
    return _folder_template(section, node_name, args)

