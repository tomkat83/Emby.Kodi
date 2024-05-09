#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import re
import os
import string

from .common import ItemBase
from ..plex_api import API
from .. import app, variables as v, plex_functions as PF
from ..path_ops import append_os_sep

LOG = getLogger('PLEX.movies')

# Tolerance in years if comparing videos as equal
VIDEOYEAR_TOLERANCE = 1
PUNCTUATION_TRANSLATION = {ord(char): None for char in string.punctuation}
# Punctuation removed in original strings!!
# Matches '2010 The Year We Make Contact 1984'
# from '2010 The Year We Make Contact 1984 720p webrip'
REGEX_MOVIENAME_AND_YEAR = re.compile(
    r'''(.+)((?:19|20)\d{2}).*(?!((19|20)\d{2}))''')


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
            if api.subtype:
                # E.g. homevideos, which have "subtype" flag set
                # Homevideo directories need to be flat by Plex' instructions
                library_path, video_path = path, path
            else:
                # Normal movie libraries
                library_path, video_path, filename = split_movie_path(fullpath)
            if library_path == video_path:
                # "Flat" folder structure where e.g. movies lie all in 1 dir
                # E.g.
                #   'C:\\Movies\\Pulp Fiction (1994).mkv'
                kodi_pathid = self.kodidb.add_path(library_path,
                                                   content='movies',
                                                   scraper='metadata.local')
                path = library_path
                kodi_parent_pathid = kodi_pathid
            else:
                # Plex library contains folders named identical to the
                # video file, e.g.
                #   'C:\\Movies\\Pulp Fiction (1994)\\Pulp Fiction (1994).mkv'
                # Add the "parent" path for the Plex library
                kodi_parent_pathid = self.kodidb.add_path(
                    library_path,
                    content='movies',
                    scraper='metadata.local')
                # Add this movie's path
                kodi_pathid = self.kodidb.add_path(
                    video_path,
                    id_parent_path=kodi_parent_pathid)
                path = video_path
        else:
            kodi_pathid = self.kodidb.get_path(path)
            kodi_parent_pathid = kodi_pathid

        if update_item:
            LOG.info('UPDATE movie plex_id: %s - %s', plex_id, api.title())
            file_id = self.kodidb.modify_file(filename,
                                              kodi_pathid,
                                              api.date_created())
            if file_id != old_kodi_fileid:
                self.kodidb.remove_file(old_kodi_fileid)
            rating_id = self.kodidb.update_ratings(kodi_id,
                                                   v.KODI_TYPE_MOVIE,
                                                   api.ratingtype(),
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
                                                api.ratingtype(),
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
                              path,
                              kodi_parent_pathid,
                              api.premiere_date(),
                              api.userrating())

        self.kodidb.modify_countries(kodi_id,
                                     v.KODI_TYPE_MOVIE,
                                     api.countries())
        self.kodidb.modify_genres(kodi_id, v.KODI_TYPE_MOVIE, api.genres())

        self.kodidb.modify_streams(file_id, api.mediastreams(), api.runtime())
        self.kodidb.modify_studios(kodi_id, v.KODI_TYPE_MOVIE, api.studios())
        # Process tags: section, PMS labels, PMS collection tags
        tags = [section_name]
        tags.extend(api.labels())
        self._process_collections(api, tags, kodi_id, section_id, children)
        self.kodidb.modify_tags(kodi_id, v.KODI_TYPE_MOVIE, tags)
        # Process playstate
        self.kodidb.set_resume(file_id,
                               api.resume_point(),
                               api.runtime(),
                               api.viewcount(),
                               api.lastplayed())
        self.plexdb.add_movie(plex_id=plex_id,
                              plex_guid=api.plex_guid,
                              checksum=api.checksum(),
                              section_id=section_id,
                              kodi_id=kodi_id,
                              kodi_fileid=file_id,
                              kodi_pathid=kodi_pathid,
                              trailer_synced=bool(api.trailer()),
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


def split_movie_path(path):
    """
    Implements Plex' video naming convention for movies:
    https://support.plex.tv/articles/naming-and-organizing-your-movie-media-files/

    Splits a video's path into its librarypath, potential video folder, and
    filename.
    E.g. path = 'C:\\Movies\\Pulp Fiction (1994)\\Pulp Fiction (1994).mkv'
    returns the tuple
        ('C:\\Movies\\',
         'C:\\Movies\\Pulp Fiction (1994)\\',
         'Pulp Fiction (1994).mkv')

    E.g. path = 'C:\\Movies\\Pulp Fiction (1994).mkv'
    returns the tuple
        ('C:\\Movies\\',
         'C:\\Movies\\',
         'Pulp Fiction (1994).mkv')
    """
    basename, filename = os.path.split(path)
    library_path, videofolder = os.path.split(basename)

    clean_filename = _clean_name(os.path.splitext(filename)[0])
    clean_videofolder = _clean_name(videofolder)

    try:
        parsed_filename = _parse_videoname_and_year(clean_filename)
    except (TypeError, IndexError):
        LOG.warn('Could not parse video path, be sure to follow the Plex '
                 'naming guidelines!! We failed to parse this path: %s', path)
        # Be on the safe side and assume that the movie folder structure is
        # flat
        return append_os_sep(basename), append_os_sep(basename), filename
    try:
        parsed_videofolder = _parse_videoname_and_year(clean_videofolder)
    except (TypeError, IndexError):
        # e.g. no year to parse => flat structure
        return append_os_sep(basename), append_os_sep(basename), filename
    if _parsed_names_alike(parsed_filename, parsed_videofolder):
        # e.g.
        # filename = The Master.(2012).720p.Blu-ray.axed.mkv
        # videofolder = The Master 2012
        # or
        # filename = National Lampoon's Christmas Vacation (1989)
        #       [x264-Bluray-1080p DTS-2.0]
        # videofolder = Christmas Vacation 1989
        return append_os_sep(library_path), append_os_sep(basename), filename
    else:
        # Flat movie file-stuctrue, all movies in one big directory
        return append_os_sep(basename), append_os_sep(basename), filename


def _parsed_names_alike(name1, name2):
    return (abs(name2[1] - name1[1]) <= VIDEOYEAR_TOLERANCE and
            (name1[0] in name2[0] or name2[0] in name1[0]))


def _clean_name(name):
    """
    Returns name with all whitespaces (regex "\\s") and punctuation
    (string.punctuation) characters removed; all characters in lowercase
    """
    return re.sub('\\s', '', name).translate(PUNCTUATION_TRANSLATION).lower()


def _parse_videoname_and_year(name):
    parsed = REGEX_MOVIENAME_AND_YEAR.search(name)
    return parsed[1], int(parsed[2])
