#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

from ..kodi_db import KodiVideoDB, KodiMusicDB
from ..downloadutils import DownloadUtils as DU
from .. import utils, variables as v, app

from . import fanart_lookup

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
            artwork = f'{artwork}?width={width}&height={height}'
        artwork = (f'{app.CONN.server}/photo/:/transcode?width=1920&height=1920&'
                   f'minSize=1&upscale=0&url={utils.quote(artwork)}')
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
                media_id = self.guids.get('imdb')
            elif media_type == v.PLEX_TYPE_SHOW:
                media_id = self.guids.get('tvdb')
            if media_id is not None:
                return media_id, None, None
            LOG.info('Plex did not provide ID for IMDB or TVDB. Start '
                     'lookup process')
        else:
            LOG.debug('Start movie set/collection lookup on themoviedb with %s',
                      item.get('title', ''))
        return fanart_lookup.external_item_id(self.title(),
                                              self.year(),
                                              self.plex_type,
                                              collection)

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
        data = DU().downloadUrl(url,
                                authenticate=False,
                                timeout=15,
                                return_response=True)
        if data in (None, 401) or not data.ok:
            LOG.debug('Could not download data from FanartTV')
            return artworks
        data = data.json()

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
