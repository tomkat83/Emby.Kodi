#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import os
import sys

import xbmcvfs
import xbmcaddon

# Import the existing Kodi add-on metadata.themoviedb.org.python
__ADDON__ = xbmcaddon.Addon(id='metadata.themoviedb.org.python')
__TEMP_PATH__ = os.path.join(__ADDON__.getAddonInfo('path'), 'python', 'lib')
__BASE__ = xbmcvfs.translatePath(__TEMP_PATH__)
sys.path.append(__BASE__)
import tmdbscraper.tmdb as tmdb

logger = logging.getLogger('PLEX.movies_tmdb')


def get_tmdb_scraper(settings):
    language = settings.getSettingString('language')
    certcountry = settings.getSettingString('tmdbcertcountry')
    return tmdb.TMDBMovieScraper(__ADDON__, language, certcountry)


# Instantiate once in order to prevent having to re-read the add-on settings
# for every single movie
__SCRAPER__ = get_tmdb_scraper(__ADDON__)

def get_tmdb_details(unique_ids):
    details = __SCRAPER__.get_details(unique_ids)
    if 'error' in details:
        logger.debug('Could not get tmdb details for %s. Error: %s',
                     unique_ids, details)
    return details
