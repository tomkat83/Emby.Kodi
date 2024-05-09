#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import os
import sys

import xbmcvfs
import xbmcaddon

from ..plex_api import API
from ..kodi_db import KodiVideoDB
from ..plex_db import PlexDB
from .. import itemtypes, plex_functions as PF, utils, variables as v

# Import the existing Kodi add-on metadata.themoviedb.org.python
__ADDON__ = xbmcaddon.Addon(id='metadata.themoviedb.org.python')
__TEMP_PATH__ = os.path.join(__ADDON__.getAddonInfo('path'), 'python', 'lib')
__BASE__ = xbmcvfs.translatePath(__TEMP_PATH__)
sys.path.append(__BASE__)
import tmdbscraper.tmdb as tmdb

logger = logging.getLogger('PLEX.metadata_movies')
PREFER_KODI_COLLECTION_ART = utils.settings('PreferKodiCollectionArt') == 'false'
TMDB_SUPPORTED_IDS = ('tmdb', 'imdb')


def get_tmdb_scraper(settings):
    language = settings.getSettingString('language')
    certcountry = settings.getSettingString('tmdbcertcountry')
    # Simplify this in the future
    # See https://github.com/croneter/PlexKodiConnect/issues/1657
    search_language = settings.getSettingString('searchlanguage')
    if search_language:
        return tmdb.TMDBMovieScraper(settings, language, certcountry, search_language)
    else:
        return tmdb.TMDBMovieScraper(settings, language, certcountry)


def get_tmdb_details(unique_ids):
    settings = xbmcaddon.Addon(id='metadata.themoviedb.org.python')
    details = get_tmdb_scraper(settings).get_details(unique_ids)
    if 'error' in details:
        logger.debug('Could not get tmdb details for %s. Error: %s',
                     unique_ids, details)
    return details


def process_trailers(plex_id, plex_type, refresh=False):
    done = True
    try:
        with PlexDB(lock=False) as plexdb:
            db_item = plexdb.item_by_id(plex_id, plex_type)
        if not db_item:
            logger.error('Could not get Kodi id for %s %s', plex_type, plex_id)
            done = False
            return
        with KodiVideoDB(lock=False) as kodidb:
            trailer = kodidb.get_trailer(db_item['kodi_id'],
                                         db_item['kodi_type'])
        if trailer and (trailer.startswith(f'plugin://{v.ADDON_ID}') or
                        not refresh):
            # No need to get a trailer
            return
        logger.debug('Processing trailer for %s %s', plex_type, plex_id)
        xml = PF.GetPlexMetadata(plex_id)
        try:
            xml[0].attrib
        except (TypeError, IndexError, AttributeError):
            logger.warn('Could not get metadata for %s. Skipping that %s '
                     'for now', plex_id, plex_type)
            done = False
            return
        api = API(xml[0])
        if (not api.guids or
                not [x for x in api.guids if x in TMDB_SUPPORTED_IDS]):
            logger.debug('No unique ids found for %s %s, cannot get a trailer',
                         plex_type, api.title())
            return
        trailer = get_tmdb_details(api.guids)
        trailer = trailer.get('info', {}).get('trailer')
        if trailer:
            with KodiVideoDB() as kodidb:
                kodidb.set_trailer(db_item['kodi_id'],
                                   db_item['kodi_type'],
                                   trailer)
            logger.debug('Found a new trailer for %s %s: %s',
                         plex_type, api.title(), trailer)
        else:
            logger.debug('No trailer found for %s %s', plex_type, api.title())
    finally:
        if done is True:
            with PlexDB() as plexdb:
                plexdb.set_trailer_synced(plex_id, plex_type)


def process_fanart(plex_id, plex_type, refresh=False):
    """
    Will look for additional fanart for the plex_type item with plex_id.
    Will check if we already got all artwork and only look if some are indeed
    missing.
    Will set the fanart_synced flag in the Plex DB if successful.
    """
    done = True
    try:
        artworks = None
        with PlexDB(lock=False) as plexdb:
            db_item = plexdb.item_by_id(plex_id, plex_type)
        if not db_item:
            logger.error('Could not get Kodi id for %s %s', plex_type, plex_id)
            done = False
            return
        if not refresh:
            with KodiVideoDB(lock=False) as kodidb:
                artworks = kodidb.get_art(db_item['kodi_id'],
                                          db_item['kodi_type'])
            # Check if we even need to get additional art
            for key in v.ALL_KODI_ARTWORK:
                if key not in artworks:
                    break
            else:
                return
        xml = PF.GetPlexMetadata(plex_id)
        try:
            xml[0].attrib
        except (TypeError, IndexError, AttributeError):
            logger.debug('Could not get metadata for %s %s. Skipping that '
                         'item for now', plex_type, plex_id)
            done = False
            return
        api = API(xml[0])
        if artworks is None:
            artworks = api.artwork()
        # Get additional missing artwork from fanart artwork sites
        artworks = api.fanart_artwork(artworks)
        with itemtypes.ITEMTYPE_FROM_PLEXTYPE[plex_type](None) as context:
            context.set_fanart(artworks,
                               db_item['kodi_id'],
                               db_item['kodi_type'])
        # Additional fanart for sets/collections
        if plex_type == v.PLEX_TYPE_MOVIE:
            for _, setname in api.collections():
                logger.debug('Getting artwork for movie set %s', setname)
                with KodiVideoDB() as kodidb:
                    setid = kodidb.create_collection(setname)
                external_set_artwork = api.set_artwork()
                if external_set_artwork and PREFER_KODI_COLLECTION_ART:
                    kodi_artwork = api.artwork(kodi_id=setid,
                                               kodi_type=v.KODI_TYPE_SET)
                    for art in kodi_artwork:
                        if art in external_set_artwork:
                            del external_set_artwork[art]
                with itemtypes.Movie(None) as movie:
                    movie.kodidb.modify_artwork(external_set_artwork,
                                                setid,
                                                v.KODI_TYPE_SET)
    finally:
        if done is True:
            with PlexDB() as plexdb:
                plexdb.set_fanart_synced(plex_id, plex_type)
