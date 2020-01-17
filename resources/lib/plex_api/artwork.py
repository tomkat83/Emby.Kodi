#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from builtins import str
from builtins import object
from logging import getLogger
from re import sub

from ..kodi_db import KodiVideoDB, KodiMusicDB
from ..downloadutils import DownloadUtils as DU
from .. import utils, variables as v, app

LOG = getLogger('PLEX.api')


class Artwork(object):
    def one_artwork(self, art_kind, aspect=None):
        """
        aspect can be: 'square', '16:9', 'poster'. Defaults to 'poster'
        """
        aspect = 'poster' if not aspect else aspect
        if aspect == 'poster':
            width = 1000
            height = 1500
        elif aspect == '16:9':
            width = 1920
            height = 1080
        elif aspect == 'square':
            width = 1000
            height = 1000
        else:
            raise NotImplementedError('aspect ratio not yet implemented: %s'
                                      % aspect)
        artwork = self.xml.get(art_kind)
        if not artwork or artwork.startswith('http'):
            return artwork
        if '/composite/' in artwork:
            try:
                # e.g. Plex collections where artwork already contains width and
                # height. Need to upscale for better resolution
                artwork, args = artwork.split('?')
                args = dict(utils.parse_qsl(args))
                width = int(args.get('width', 400))
                height = int(args.get('height', 400))
                # Adjust to 4k resolution 1920x1080
                scaling = 1920.0 / float(max(width, height))
                width = int(scaling * width)
                height = int(scaling * height)
            except ValueError:
                # e.g. playlists
                pass
            artwork = '%s?width=%s&height=%s' % (artwork, width, height)
        artwork = ('%s/photo/:/transcode?width=1920&height=1920&'
                   'minSize=1&upscale=0&url=%s'
                   % (app.CONN.server, utils.quote(artwork)))
        artwork = self.attach_plex_token_to_url(artwork)
        return artwork

    def artwork_episode(self, full_artwork):
        """
        Episodes are special, they only get the thumb, because all the other
        artwork will be saved under season and show EXCEPT if you're
        constructing a listitem and the item has NOT been synched to the Kodi db
        """
        artworks = {}
        # Item is currently NOT in the Kodi DB
        art = self.one_artwork('thumb')
        if art:
            artworks['thumb'] = art
        if not full_artwork:
            # For episodes, only get the thumb. Everything else stemms from
            # either the season or the show
            return artworks
        for kodi_artwork, plex_artwork in \
                v.KODI_TO_PLEX_ARTWORK_EPISODE.items():
            art = self.one_artwork(plex_artwork)
            if art:
                artworks[kodi_artwork] = art
        return artworks

    def artwork(self, kodi_id=None, kodi_type=None, full_artwork=False):
        """
        Gets the URLs to the Plex artwork. Dict keys will be missing if there
        is no corresponding artwork.
        Pass kodi_id and kodi_type to grab the artwork saved in the Kodi DB
        (thus potentially more artwork, e.g. clearart, discart).

        Output ('max' version)
        {
            'thumb'
            'poster'
            'banner'
            'clearart'
            'clearlogo'
            'fanart'
        }
        'landscape' and 'icon' might be implemented later
        Passing full_artwork=True returns ALL the artwork for the item, so not
        just 'thumb' for episodes, but also season and show artwork
        """
        if self.plex_type == v.PLEX_TYPE_EPISODE:
            return self.artwork_episode(full_artwork)
        artworks = {}
        if kodi_id:
            # in Kodi database, potentially with additional e.g. clearart
            if self.plex_type in v.PLEX_VIDEOTYPES:
                with KodiVideoDB(lock=False) as kodidb:
                    return kodidb.get_art(kodi_id, kodi_type)
            else:
                with KodiMusicDB(lock=False) as kodidb:
                    return kodidb.get_art(kodi_id, kodi_type)

        for kodi_artwork, plex_artwork in v.KODI_TO_PLEX_ARTWORK.items():
            art = self.one_artwork(plex_artwork)
            if art:
                artworks[kodi_artwork] = art
        if self.plex_type in (v.PLEX_TYPE_SONG, v.PLEX_TYPE_ALBUM):
            # Get parent item artwork if the main item is missing artwork
            if 'fanart' not in artworks:
                art = self.one_artwork('parentArt')
                if art:
                    artworks['fanart1'] = art
            if 'poster' not in artworks:
                art = self.one_artwork('parentThumb')
                if art:
                    artworks['poster'] = art
        if self.plex_type in (v.PLEX_TYPE_SONG,
                              v.PLEX_TYPE_ALBUM,
                              v.PLEX_TYPE_ARTIST):
            # need to set poster also as thumb
            art = self.one_artwork('thumb')
            if art:
                artworks['thumb'] = art
        if self.plex_type == v.PLEX_TYPE_PLAYLIST:
            art = self.one_artwork('composite')
            if art:
                artworks['thumb'] = art
        return artworks

    def fanart_artwork(self, artworks):
        """
        Downloads additional fanart from third party sources (well, link to
        fanart only).
        """
        external_id = self.retrieve_external_item_id()
        if external_id is not None:
            artworks = self.lookup_fanart_tv(external_id[0], artworks)
        return artworks

    def set_artwork(self):
        """
        Gets the URLs to the Plex artwork, or empty string if not found.
        Only call on movies!
        """
        artworks = {}
        # Plex does not get much artwork - go ahead and get the rest from
        # fanart tv only for movie or tv show
        external_id = self.retrieve_external_item_id(collection=True)
        if external_id is not None:
            external_id, poster, background = external_id
            if poster is not None:
                artworks['poster'] = poster
            if background is not None:
                artworks['fanart'] = background
            artworks = self.lookup_fanart_tv(external_id, artworks)
        else:
            LOG.info('Did not find a set/collection ID on TheMovieDB using %s.'
                     ' Artwork will be missing.', self.title())
        return artworks

    def retrieve_external_item_id(self, collection=False):
        """
        Returns the set
            media_id [unicode]:     the item's IMDB id for movies or tvdb id for
                                    TV shows
            poster [unicode]:       path to the item's poster artwork
            background [unicode]:   path to the item's background artwork

        The last two might be None if not found. Generally None is returned
        if unsuccessful.

        If not found in item's Plex metadata, check themovidedb.org.
        """
        item = self.xml.attrib
        media_type = self.plex_type
        media_id = None
        # Return the saved Plex id's, if applicable
        # Always seek collection's ids since not provided by PMS
        if collection is False:
            if media_type == v.PLEX_TYPE_MOVIE:
                media_id = self.provider('imdb')
            elif media_type == v.PLEX_TYPE_SHOW:
                media_id = self.provider('tvdb')
            if media_id is not None:
                return media_id, None, None
            LOG.info('Plex did not provide ID for IMDB or TVDB. Start '
                     'lookup process')
        else:
            LOG.debug('Start movie set/collection lookup on themoviedb with %s',
                      item.get('title', ''))

        api_key = utils.settings('themoviedbAPIKey')
        if media_type == v.PLEX_TYPE_SHOW:
            media_type = 'tv'
        title = self.title()
        # if the title has the year in remove it as tmdb cannot deal with it...
        # replace e.g. 'The Americans (2015)' with 'The Americans'
        title = sub(r'\s*\(\d{4}\)$', '', title, count=1)
        url = 'https://api.themoviedb.org/3/search/%s' % media_type
        parameters = {
            'api_key': api_key,
            'language': v.KODILANGUAGE,
            'query': title.encode('utf-8')
        }
        data = DU().downloadUrl(url,
                                authenticate=False,
                                parameters=parameters,
                                timeout=7)
        try:
            data.get('test')
        except AttributeError:
            LOG.warning('Could not download data from FanartTV')
            return
        if not data.get('results'):
            LOG.info('No match found on themoviedb for type: %s, title: %s',
                     media_type, title)
            return

        year = item.get('year')
        match_found = None
        # find year match
        if year:
            for entry in data['results']:
                if year in entry.get('first_air_date', ''):
                    match_found = entry
                    break
                elif year in entry.get('release_date', ''):
                    match_found = entry
                    break
        # find exact match based on title, if we haven't found a year match
        if match_found is None:
            LOG.info('No themoviedb match found using year %s', year)
            replacements = (
                ' ',
                '-',
                '&',
                ',',
                ':',
                ';'
            )
            for entry in data['results']:
                name = entry.get('name', entry.get('title', ''))
                original_name = entry.get('original_name', '')
                title_alt = title.lower()
                name_alt = name.lower()
                org_name_alt = original_name.lower()
                for replace_string in replacements:
                    title_alt = title_alt.replace(replace_string, '')
                    name_alt = name_alt.replace(replace_string, '')
                    org_name_alt = org_name_alt.replace(replace_string, '')
                if name == title or original_name == title:
                    # match found for exact title name
                    match_found = entry
                    break
                elif (name.split(' (')[0] == title or title_alt == name_alt or
                      title_alt == org_name_alt):
                    # match found with substituting some stuff
                    match_found = entry
                    break

        # if a match was not found, we accept the closest match from TMDB
        if match_found is None and data.get('results'):
            LOG.info('Using very first match from themoviedb')
            match_found = entry = data.get('results')[0]

        if match_found is None:
            LOG.info('Still no themoviedb match for type: %s, title: %s, '
                     'year: %s', media_type, title, year)
            LOG.debug('themoviedb answer was %s', data['results'])
            return

        LOG.info('Found themoviedb match for %s: %s',
                 item.get('title'), match_found)

        tmdb_id = str(entry.get('id', ''))
        if tmdb_id == '':
            LOG.error('No themoviedb ID found, aborting')
            return

        if media_type == 'multi' and entry.get('media_type'):
            media_type = entry.get('media_type')
        name = entry.get('name', entry.get('title'))
        # lookup external tmdb_id and perform artwork lookup on fanart.tv
        parameters = {'api_key': api_key}
        if media_type == 'movie':
            url = 'https://api.themoviedb.org/3/movie/%s' % tmdb_id
            parameters['append_to_response'] = 'videos'
        elif media_type == 'tv':
            url = 'https://api.themoviedb.org/3/tv/%s' % tmdb_id
            parameters['append_to_response'] = 'external_ids,videos'
        media_id, poster, background = None, None, None
        for language in [v.KODILANGUAGE, 'en']:
            parameters['language'] = language
            data = DU().downloadUrl(url,
                                    authenticate=False,
                                    parameters=parameters,
                                    timeout=7)
            try:
                data.get('test')
            except AttributeError:
                LOG.warning('Could not download %s with parameters %s',
                            url, parameters)
                continue
            if collection is False:
                if data.get('imdb_id'):
                    media_id = str(data.get('imdb_id'))
                    break
                if (data.get('external_ids') and
                        data['external_ids'].get('tvdb_id')):
                    media_id = str(data['external_ids']['tvdb_id'])
                    break
            else:
                if not data.get('belongs_to_collection'):
                    continue
                media_id = data.get('belongs_to_collection').get('id')
                if not media_id:
                    continue
                media_id = str(media_id)
                LOG.debug('Retrieved collections tmdb id %s for %s',
                          media_id, title)
                url = 'https://api.themoviedb.org/3/collection/%s' % media_id
                data = DU().downloadUrl(url,
                                        authenticate=False,
                                        parameters=parameters,
                                        timeout=7)
                try:
                    data.get('poster_path')
                except AttributeError:
                    LOG.debug('Could not find TheMovieDB poster paths for %s'
                              ' in the language %s', title, language)
                    continue
                if not poster and data.get('poster_path'):
                    poster = ('https://image.tmdb.org/t/p/original%s' %
                              data.get('poster_path'))
                if not background and data.get('backdrop_path'):
                    background = ('https://image.tmdb.org/t/p/original%s' %
                                  data.get('backdrop_path'))
        return media_id, poster, background

    def lookup_fanart_tv(self, media_id, artworks):
        """
        perform artwork lookup on fanart.tv

        media_id: IMDB id for movies, tvdb id for TV shows
        """
        api_key = utils.settings('FanArtTVAPIKey')
        typus = self.plex_type
        if typus == v.PLEX_TYPE_SHOW:
            typus = 'tv'

        if typus == v.PLEX_TYPE_MOVIE:
            url = 'http://webservice.fanart.tv/v3/movies/%s?api_key=%s' \
                % (media_id, api_key)
        elif typus == 'tv':
            url = 'http://webservice.fanart.tv/v3/tv/%s?api_key=%s' \
                % (media_id, api_key)
        else:
            # Not supported artwork
            return artworks
        data = DU().downloadUrl(url, authenticate=False, timeout=15)
        try:
            data.get('test')
        except AttributeError:
            LOG.error('Could not download data from FanartTV')
            return artworks

        fanart_tv_types = list(v.FANART_TV_TO_KODI_TYPE)

        if typus == v.PLEX_TYPE_ARTIST:
            fanart_tv_types.append(("thumb", "folder"))
        else:
            fanart_tv_types.append(("thumb", "thumb"))

        prefixes = (
            "hd" + typus,
            "hd",
            typus,
            "",
        )
        for fanart_tv_type, kodi_type in fanart_tv_types:
            # Skip the ones we already have
            if kodi_type in artworks:
                continue
            for prefix in prefixes:
                fanarttvimage = prefix + fanart_tv_type
                if fanarttvimage not in data:
                    continue
                # select image in preferred language
                for entry in data[fanarttvimage]:
                    if entry.get("lang") == v.KODILANGUAGE:
                        artworks[kodi_type] = \
                            entry.get("url", "").replace(' ', '%20')
                        break
                # just grab the first english OR undefinded one as fallback
                # (so we're actually grabbing the more popular one)
                if kodi_type not in artworks:
                    for entry in data[fanarttvimage]:
                        if entry.get("lang") in ("en", "00"):
                            artworks[kodi_type] = \
                                entry.get("url", "").replace(' ', '%20')
                            break

        # grab extrafanarts in list
        fanartcount = 1 if 'fanart' in artworks else ''
        for prefix in prefixes:
            fanarttvimage = prefix + 'background'
            if fanarttvimage not in data:
                continue
            for entry in data[fanarttvimage]:
                if entry.get("url") is None:
                    continue
                artworks['fanart%s' % fanartcount] = \
                    entry['url'].replace(' ', '%20')
                try:
                    fanartcount += 1
                except TypeError:
                    fanartcount = 1
                if fanartcount >= v.MAX_BACKGROUND_COUNT:
                    break
        return artworks
