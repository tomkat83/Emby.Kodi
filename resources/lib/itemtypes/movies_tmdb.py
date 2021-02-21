#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
import logging
import os
import sys

import xbmcvfs
import xbmcaddon

# Import the existing Kodi add-on metadata.themoviedb.org.python
__ADDON__ = xbmcaddon.Addon(id='metadata.themoviedb.org.python')
__TEMP_PATH__ = os.path.join(__ADDON__.getAddonInfo('path').decode('utf-8'),
                             'python',
                             'lib')
__BASE__ = xbmcvfs.translatePath(__TEMP_PATH__.encode('utf-8')).decode('utf-8')
sys.path.append(__BASE__)
import tmdbscraper.tmdb as tmdb

logger = logging.getLogger('PLEX.movies_tmdb')


def get_tmdb_scraper(settings):
    language = settings.getSettingString('language').decode('utf-8')
    certcountry = settings.getSettingString('tmdbcertcountry').decode('utf-8')
    return tmdb.TMDBMovieScraper(__ADDON__, language, certcountry)


# Instantiate once in order to prevent having to re-read the add-on settings
# for every single movie
__SCRAPER__ = get_tmdb_scraper(__ADDON__)


def get_tmdb_details(unique_ids):
    details = __SCRAPER__.get_details(unique_ids)
    LOG.error('details type. %s', type(details))
    if 'error' in details:
        logger.debug('Could not get tmdb details for %s. Error: %s',
                     unique_ids, details)
    return details
