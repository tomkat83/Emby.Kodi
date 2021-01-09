#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .common import ItemBase
from ..plex_api import API
from .. import app, variables as v, plex_functions as PF

LOG = getLogger('PLEX.movies')


class Movie(ItemBase):
    """
    Used for plex library-type movies
    """
    def add_update(self, xml, section_name=None, section_id=None,
                   children=None):
        """
        Process single movie
        """
        api = API(xml)
        if not self.sync_this_item(section_id or api.library_section_id()):
            LOG.debug('Skipping sync of %s %s: %s - section %s not synched to '
                      'Kodi', api.plex_type, api.plex_id, api.title(),
                      section_id or api.library_section_id())
            return
        plex_id = api.plex_id
        movie = self.plexdb.movie(plex_id)
        if movie:
            update_item = True
            kodi_id = movie['kodi_id']
            old_kodi_fileid = movie['kodi_fileid']
            kodi_pathid = movie['kodi_pathid']
        else:
            update_item = False
            kodi_id = self.kodidb.new_movie_id()

        fullpath, path, filename = api.fullpath()
        if app.SYNC.direct_paths and not fullpath.startswith('http'):
            kodi_pathid = self.kodidb.add_path(path,
                                               content='movies',
                                               scraper='metadata.local')
        else:
            kodi_pathid = self.kodidb.get_path(path)

        if update_item:
            LOG.info('UPDATE movie plex_id: %s - %s', plex_id, api.title())
            file_id = self.kodidb.modify_file(filename,
                                              kodi_pathid,
                                              api.date_created())
            if file_id != old_kodi_fileid:
                self.kodidb.remove_file(old_kodi_fileid)
            rating_id = self.kodidb.update_ratings(kodi_id,
                                                   v.KODI_TYPE_MOVIE,
                                                   "default",
                                                   api.rating(),
                                                   api.votecount())
            unique_id = self.update_provider_ids(api, kodi_id)
            self.kodidb.modify_people(kodi_id,
                                      v.KODI_TYPE_MOVIE,
                                      api.people())
            if app.SYNC.artwork:
                self.kodidb.modify_artwork(api.artwork(),
                                           kodi_id,
                                           v.KODI_TYPE_MOVIE)
        else:
            LOG.info("ADD movie plex_id: %s - %s", plex_id, api.title())
            file_id = self.kodidb.add_file(filename,
                                           kodi_pathid,
                                           api.date_created())
            rating_id = self.kodidb.add_ratings(kodi_id,
                                                v.KODI_TYPE_MOVIE,
                                                "default",
                                                api.rating(),
                                                api.votecount())
            unique_id = self.add_provider_ids(api, kodi_id)
            self.kodidb.add_people(kodi_id,
                                   v.KODI_TYPE_MOVIE,
                                   api.people())
            if app.SYNC.artwork:
                self.kodidb.add_artwork(api.artwork(),
                                        kodi_id,
                                        v.KODI_TYPE_MOVIE)

        unique_id = self._prioritize_provider_id(unique_id)

        # Update Kodi's main entry
        self.kodidb.add_movie(kodi_id,
                              file_id,
                              api.title(),
                              api.plot(),
                              api.shortplot(),
                              api.tagline(),
                              api.votecount(),
                              rating_id,
                              api.list_to_string(api.writers()),
                              api.year(),
                              unique_id,
                              api.sorttitle(),
                              api.runtime(),
                              api.content_rating(),
                              api.list_to_string(api.genres()),
                              api.list_to_string(api.directors()),
                              api.title(),
                              api.list_to_string(api.studios()),
                              api.trailer(),
                              api.list_to_string(api.countries()),
                              fullpath,
                              kodi_pathid,
                              api.premiere_date(),
                              api.userrating())

        self.kodidb.modify_countries(kodi_id,
                                     v.KODI_TYPE_MOVIE,
                                     api.countries())
        self.kodidb.modify_genres(kodi_id, v.KODI_TYPE_MOVIE, api.genres())

        self.kodidb.modify_streams(file_id, api.mediastreams(), api.runtime())
        self.kodidb.modify_studios(kodi_id, v.KODI_TYPE_MOVIE, api.studios())
        tags = [section_name]
        self._process_collections(api, tags, kodi_id, section_id, children)
        self.kodidb.modify_tags(kodi_id, v.KODI_TYPE_MOVIE, tags)
        # Process playstate
        self.kodidb.set_resume(file_id,
                               api.resume_point(),
                               api.runtime(),
                               api.viewcount(),
                               api.lastplayed())
        self.plexdb.add_movie(plex_id=plex_id,
                              checksum=api.checksum(),
                              section_id=section_id,
                              kodi_id=kodi_id,
                              kodi_fileid=file_id,
                              kodi_pathid=kodi_pathid,
                              last_sync=self.last_sync)

    def remove(self, plex_id, plex_type=None):
        """
        Remove a movie with all references and all orphaned associated entries
        from the Kodi DB
        """
        movie = self.plexdb.movie(plex_id)
        try:
            kodi_id = movie['kodi_id']
            file_id = movie['kodi_fileid']
            kodi_type = v.KODI_TYPE_MOVIE
            LOG.debug('Removing movie with plex_id %s, kodi_id: %s',
                      plex_id, kodi_id)
        except TypeError:
            LOG.error('Movie with plex_id %s not found - cannot delete',
                      plex_id)
            return
        # Remove the plex reference
        self.plexdb.remove(plex_id, v.PLEX_TYPE_MOVIE)
        # Remove artwork
        self.kodidb.delete_artwork(kodi_id, kodi_type)
        set_id = self.kodidb.get_set_id(kodi_id)
        self.kodidb.modify_countries(kodi_id, kodi_type)
        self.kodidb.modify_people(kodi_id, kodi_type)
        self.kodidb.modify_genres(kodi_id, kodi_type)
        self.kodidb.modify_studios(kodi_id, kodi_type)
        self.kodidb.modify_tags(kodi_id, kodi_type)
        # Delete kodi movie and file
        self.kodidb.remove_file(file_id)
        self.kodidb.remove_movie(kodi_id)
        if set_id:
            self.kodidb.delete_possibly_empty_set(set_id)
        self.kodidb.remove_uniqueid(kodi_id, kodi_type)
        self.kodidb.remove_ratings(kodi_id, kodi_type)
        LOG.debug('Deleted movie %s from kodi database', plex_id)

    def update_userdata(self, xml_element, plex_type):
        """
        Updates the Kodi watched state of the item from PMS. Also retrieves
        Plex resume points for movies in progress.

        Returns True if successful, False otherwise (e.g. item missing)
        """
        api = API(xml_element)
        # Get key and db entry on the Kodi db side
        db_item = self.plexdb.item_by_id(api.plex_id, plex_type)
        if not db_item:
            LOG.info('Item not yet synced: %s', xml_element.attrib)
            return False
        # Write to Kodi DB
        self.kodidb.set_resume(db_item['kodi_fileid'],
                               api.resume_point(),
                               api.runtime(),
                               api.viewcount(),
                               api.lastplayed())
        self.kodidb.update_userrating(db_item['kodi_id'],
                                      db_item['kodi_type'],
                                      api.userrating())
        return True

    def _process_collections(self, api, tags, kodi_id, section_id, children):
        for _, set_name in api.collections():
            tags.append(set_name)
        for plex_set_id, set_name in api.collections(): 
            set_api = None
            # Add any sets from Plex collection tags
            kodi_set_id = self.kodidb.create_collection(set_name)
            self.kodidb.assign_collection(kodi_set_id, kodi_id)
            if not app.SYNC.artwork:
                # Rest below is to get collection artwork
                # TODO: continue instead of break (see TODO/break below)
                break
            if children is None:
                # e.g. when added via websocket
                LOG.debug('Costly looking up Plex collection %s: %s',
                          plex_set_id, set_name)
                for index, coll_plex_id in api.collections_match(section_id):
                    # Get Plex artwork for collections - a pain
                    if index == plex_set_id:
                        set_xml = PF.GetPlexMetadata(coll_plex_id)
                        try:
                            set_xml.attrib
                        except AttributeError:
                            LOG.error('Could not get set metadata %s',
                                      coll_plex_id)
                            continue
                        set_api = API(set_xml[0])
                        break
            elif plex_set_id in children:
                # Provided by get_metadata thread
                set_api = API(children[plex_set_id][0])
            if set_api:
                self.kodidb.modify_artwork(set_api.artwork(),
                                           kodi_set_id,
                                           v.KODI_TYPE_SET)
            # TODO: Once Kodi (19?) supports SEVERAL sets/collections per
            # movie, support that. For now, we only take the very first
            # collection/set that Plex returns
            break

    @staticmethod
    def _prioritize_provider_id(unique_ids):
        """
        Prioritize which ID ends up in the SHOW table (there can only be 1)
        tvdb > imdb > tmdb
        """
        return unique_ids.get('imdb',
                              unique_ids.get('tmdb',
                                             unique_ids.get('tvdb')))
