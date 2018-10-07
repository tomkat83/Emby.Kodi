#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from ntpath import dirname
from datetime import datetime

from . import artwork
from . import utils
from . import plexdb_functions as plexdb
from . import kodidb_functions as kodidb
from .plex_api import API
from . import plex_functions as PF
from . import variables as v
from . import state
###############################################################################

LOG = getLogger('PLEX.itemtypes')

# Note: always use same order of URL arguments, NOT urlencode:
#   plex_id=<plex_id>&plex_type=<plex_type>&mode=play

###############################################################################


class Items(object):
    """
    Items to be called with "with Items() as xxx:" to ensure that __enter__
    method is called (opens db connections)

    Input:
        kodiType:       optional argument; e.g. 'video' or 'music'
    """
    def __init__(self):
        self.artwork = artwork.Artwork()
        self.server = utils.window('pms_server')
        self.plexconn = None
        self.plexcursor = None
        self.kodiconn = None
        self.kodicursor = None
        self.plex_db = None
        self.kodi_db = None

    def __enter__(self):
        """
        Open DB connections and cursors
        """
        self.plexconn = utils.kodi_sql('plex')
        self.plexcursor = self.plexconn.cursor()
        self.kodiconn = utils.kodi_sql('video')
        self.kodicursor = self.kodiconn.cursor()
        self.plex_db = plexdb.Plex_DB_Functions(self.plexcursor)
        self.kodi_db = kodidb.KodiDBMethods(self.kodicursor)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Make sure DB changes are committed and connection to DB is closed.
        """
        self.plexconn.commit()
        self.kodiconn.commit()
        self.plexconn.close()
        self.kodiconn.close()
        return self

    def set_fanart(self, artworks, kodi_id, kodi_type):
        """
        Writes artworks [dict containing only set artworks] to the Kodi art DB
        """
        self.artwork.modify_artwork(artworks,
                                    kodi_id,
                                    kodi_type,
                                    self.kodicursor)

    def updateUserdata(self, xml):
        """
        Updates the Kodi watched state of the item from PMS. Also retrieves
        Plex resume points for movies in progress.

        viewtag and viewid only serve as dummies
        """
        for mediaitem in xml:
            api = API(mediaitem)
            # Get key and db entry on the Kodi db side
            db_item = self.plex_db.getItem_byId(api.plex_id())
            try:
                fileid = db_item[1]
            except TypeError:
                continue
            # Grab the user's viewcount, resume points etc. from PMS' answer
            userdata = api.userdata()
            # Write to Kodi DB
            self.kodi_db.set_resume(fileid,
                                    userdata['Resume'],
                                    userdata['Runtime'],
                                    userdata['PlayCount'],
                                    userdata['LastPlayedDate'],
                                    api.plex_type())
            if v.KODIVERSION >= 17:
                self.kodi_db.update_userrating(db_item[0],
                                               db_item[4],
                                               userdata['UserRating'])

    def updatePlaystate(self, mark_played, view_count, resume, duration,
                        file_id, lastViewedAt, plex_type):
        """
        Use with websockets, not xml
        """
        # If the playback was stopped, check whether we need to increment the
        # playcount. PMS won't tell us the playcount via websockets
        LOG.debug('Playstate file_id %s: viewcount: %s, resume: %s, type: %s',
                  file_id, view_count, resume, plex_type)
        if mark_played:
            LOG.info('Marking as completely watched in Kodi')
            try:
                view_count += 1
            except TypeError:
                view_count = 1
            resume = 0
        # Do the actual update
        self.kodi_db.set_resume(file_id,
                                resume,
                                duration,
                                view_count,
                                lastViewedAt,
                                plex_type)


class Movies(Items):
    """
    Used for plex library-type movies
    """
    @utils.catch_exceptions(warnuser=True)
    def add_update(self, item, viewtag=None, viewid=None):
        """
        Process single movie
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        api = API(item)

        # If the item already exist in the local Kodi DB we'll perform a full
        # item update
        # If the item doesn't exist, we'll add it to the database
        update_item = True
        itemid = api.plex_id()
        LOG.debug('Adding movie with plex_id %s', itemid)
        # Cannot parse XML, abort
        if not itemid:
            LOG.error("Cannot parse XML data for movie")
            return
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            movieid = plex_dbitem[0]
            old_fileid = plex_dbitem[1]
            pathid = plex_dbitem[2]

        except TypeError:
            # movieid
            update_item = False
            kodicursor.execute("select coalesce(max(idMovie),0) from movie")
            movieid = kodicursor.fetchone()[0] + 1

        else:
            # Verification the item is still in Kodi
            query = "SELECT * FROM movie WHERE idMovie = ?"
            kodicursor.execute(query, (movieid,))
            try:
                kodicursor.fetchone()[0]
            except TypeError:
                # item is not found, let's recreate it.
                update_item = False
                LOG.info("movieid: %s missing from Kodi, repairing the entry.",
                         movieid)

        # fileId information
        checksum = api.checksum()
        dateadded = api.date_created()
        userdata = api.userdata()
        playcount = userdata['PlayCount']
        dateplayed = userdata['LastPlayedDate']
        resume = userdata['Resume']
        runtime = userdata['Runtime']

        # item details
        people = api.people()
        writer = api.list_to_string(people['Writer'])
        director = api.list_to_string(people['Director'])
        genres = api.genre_list()
        genre = api.list_to_string(genres)
        title, sorttitle = api.titles()
        plot = api.plot()
        shortplot = None
        tagline = api.tagline()
        votecount = None
        collections = api.collection_list()

        rating = userdata['Rating']
        year = api.year()
        premieredate = api.premiere_date()
        imdb = api.provider('imdb')
        mpaa = api.content_rating()
        countries = api.country_list()
        country = api.list_to_string(countries)
        studios = api.music_studio_list()
        try:
            studio = studios[0]
        except IndexError:
            studio = None
        trailer = api.trailers()

        # GET THE FILE AND PATH #####
        do_indirect = not state.DIRECT_PATHS
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            playurl = api.file_path(force_first_media=True)
            if playurl is None:
                # Something went wrong, trying to use non-direct paths
                do_indirect = True
            else:
                playurl = api.validate_playurl(playurl, api.plex_type())
                if playurl is None:
                    return False
                if "\\" in playurl:
                    # Local path
                    filename = playurl.rsplit("\\", 1)[1]
                else:
                    # Network share
                    filename = playurl.rsplit("/", 1)[1]
                path = playurl.replace(filename, "")
                pathid = self.kodi_db.add_video_path(path,
                                                     content='movies',
                                                     scraper='metadata.local')
        if do_indirect:
            # Set plugin path and media flags using real filename
            filename = api.file_name(force_first_media=True)
            path = 'plugin://%s.movies/' % v.ADDON_ID
            filename = ('%s?plex_id=%s&plex_type=%s&mode=play&filename=%s'
                        % (path, itemid, v.PLEX_TYPE_MOVIE, filename))
            playurl = filename
            pathid = self.kodi_db.get_path(path)

        # movie table:
        # c22 - playurl
        # c23 - pathid
        # This information is used later by file browser.

        # add/retrieve pathid and fileid
        # if the path or file already exists, the calls return current value
        fileid = self.kodi_db.add_file(filename, pathid, dateadded)

        # UPDATE THE MOVIE #####
        if update_item:
            LOG.info("UPDATE movie itemid: %s - Title: %s", itemid, title)
            if fileid != old_fileid:
                LOG.debug('Removing old file entry: %s', old_fileid)
                self.kodi_db.remove_file(old_fileid)
            # Update the movie entry
            if v.KODIVERSION >= 17:
                # update new ratings Kodi 17
                rating_id = self.kodi_db.get_ratingid(movieid,
                                                      v.KODI_TYPE_MOVIE)
                self.kodi_db.update_ratings(movieid,
                                            v.KODI_TYPE_MOVIE,
                                            "default",
                                            rating,
                                            votecount,
                                            rating_id)
                # update new uniqueid Kodi 17
                if imdb is not None:
                    uniqueid = self.kodi_db.get_uniqueid(movieid,
                                                         v.KODI_TYPE_MOVIE)
                    self.kodi_db.update_uniqueid(movieid,
                                                 v.KODI_TYPE_MOVIE,
                                                 imdb,
                                                 "imdb",
                                                 uniqueid)
                else:
                    self.kodi_db.remove_uniqueid(movieid, v.KODI_TYPE_MOVIE)
                    uniqueid = -1
                query = '''
                    UPDATE movie
                    SET c00 = ?, c01 = ?, c02 = ?, c03 = ?, c04 = ?, c05 = ?,
                        c06 = ?, c07 = ?, c09 = ?, c10 = ?, c11 = ?, c12 = ?,
                        c14 = ?, c15 = ?, c16 = ?, c18 = ?, c19 = ?, c21 = ?,
                        c22 = ?, c23 = ?, idFile=?, premiered = ?,
                        userrating = ?
                    WHERE idMovie = ?
                '''
                kodicursor.execute(query, (title, plot, shortplot, tagline,
                    votecount, rating_id, writer, year, uniqueid, sorttitle,
                    runtime, mpaa, genre, director, title, studio, trailer,
                    country, playurl, pathid, fileid, premieredate,
                    userdata['UserRating'], movieid))
            else:
                query = '''
                    UPDATE movie
                    SET c00 = ?, c01 = ?, c02 = ?, c03 = ?, c04 = ?, c05 = ?,
                        c06 = ?, c07 = ?, c09 = ?, c10 = ?, c11 = ?, c12 = ?,
                        c14 = ?, c15 = ?, c16 = ?, c18 = ?, c19 = ?, c21 = ?,
                        c22 = ?, c23 = ?, idFile=?
                    WHERE idMovie = ?
                '''
                kodicursor.execute(query, (title, plot, shortplot, tagline,
                    votecount, rating, writer, year, imdb, sorttitle, runtime,
                    mpaa, genre, director, title, studio, trailer, country,
                    playurl, pathid, fileid, movieid))

        # OR ADD THE MOVIE #####
        else:
            LOG.info("ADD movie itemid: %s - Title: %s", itemid, title)
            if v.KODIVERSION >= 17:
                # add new ratings Kodi 17
                rating_id = self.kodi_db.get_ratingid(movieid,
                                                      v.KODI_TYPE_MOVIE)
                self.kodi_db.add_ratings(rating_id,
                                         movieid,
                                         v.KODI_TYPE_MOVIE,
                                         "default",
                                         rating,
                                         votecount)
                # add new uniqueid Kodi 17
                if imdb is not None:
                    uniqueid = self.kodi_db.get_uniqueid(movieid,
                                                         v.KODI_TYPE_MOVIE)
                    self.kodi_db.add_uniqueid(uniqueid,
                                              movieid,
                                              v.KODI_TYPE_MOVIE,
                                              imdb,
                                              "imdb")
                else:
                    uniqueid = -1
                query = '''
                    INSERT INTO movie(idMovie, idFile, c00, c01, c02, c03,
                        c04, c05, c06, c07, c09, c10, c11, c12, c14, c15, c16,
                        c18, c19, c21, c22, c23, premiered, userrating)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?)
                '''
                kodicursor.execute(query, (movieid, fileid, title, plot,
                    shortplot, tagline, votecount, rating_id, writer, year,
                    uniqueid, sorttitle, runtime, mpaa, genre, director,
                    title, studio, trailer, country, playurl, pathid, premieredate,
                    userdata['UserRating']))
            else:
                query = '''
                    INSERT INTO movie(idMovie, idFile, c00, c01, c02, c03,
                        c04, c05, c06, c07, c09, c10, c11, c12, c14, c15, c16,
                        c18, c19, c21, c22, c23)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?)
                '''
                kodicursor.execute(query, (movieid, fileid, title, plot,
                    shortplot, tagline, votecount, rating, writer, year, imdb,
                    sorttitle, runtime, mpaa, genre, director, title, studio,
                    trailer, country, playurl, pathid))

        # Create or update the reference in plex table Add reference is
        # idempotent; the call here updates also fileid and pathid when item is
        # moved or renamed
        plex_db.addReference(itemid,
                             v.PLEX_TYPE_MOVIE,
                             movieid,
                             v.KODI_TYPE_MOVIE,
                             kodi_fileid=fileid,
                             kodi_pathid=pathid,
                             parent_id=None,
                             checksum=checksum,
                             view_id=viewid)
        # Process countries
        self.kodi_db.modify_countries(movieid, v.KODI_TYPE_MOVIE, countries)
        # Process cast
        self.kodi_db.modify_people(movieid,
                                   v.KODI_TYPE_MOVIE,
                                   api.people_list())
        # Process genres
        self.kodi_db.modify_genres(movieid, v.KODI_TYPE_MOVIE, genres)
        # Process artwork
        artwork.modify_artwork(api.artwork(),
                               movieid,
                               v.KODI_TYPE_MOVIE,
                               kodicursor)
        # Process stream details
        self.kodi_db.modify_streams(fileid, api.mediastreams(), runtime)
        # Process studios
        self.kodi_db.modify_studios(movieid, v.KODI_TYPE_MOVIE, studios)
        tags = [viewtag]
        if userdata['Favorite']:
            tags.append("Favorite movies")
        if collections:
            collections_match = api.collections_match()
            for plex_set_id, set_name in collections:
                tags.append(set_name)
                # Add any sets from Plex collection tags
                kodi_set_id = self.kodi_db.create_collection(set_name)
                self.kodi_db.assign_collection(kodi_set_id, movieid)
                for index, plex_id in collections_match:
                    # Get Plex artwork for collections - a pain
                    if index == plex_set_id:
                        set_xml = PF.GetPlexMetadata(plex_id)
                        try:
                            set_xml.attrib
                        except AttributeError:
                            LOG.error('Could not get set metadata %s', plex_id)
                            continue
                        set_api = API(set_xml[0])
                        artwork.modify_artwork(set_api.artwork(),
                                               kodi_set_id,
                                               v.KODI_TYPE_SET,
                                               kodicursor)
                        break
        self.kodi_db.modify_tags(movieid, v.KODI_TYPE_MOVIE, tags)
        # Process playstates
        self.kodi_db.set_resume(fileid,
                                resume,
                                runtime,
                                playcount,
                                dateplayed,
                                v.PLEX_TYPE_MOVIE)

    def remove(self, plex_id):
        """
        Remove a movie with all references and all orphaned associated entries
        from the Kodi DB
        """
        plex_dbitem = self.plex_db.getItem_byId(plex_id)
        try:
            kodi_id = plex_dbitem[0]
            file_id = plex_dbitem[1]
            kodi_type = plex_dbitem[4]
            LOG.debug('Removing %sid: %s file_id: %s',
                      kodi_type, kodi_id, file_id)
        except TypeError:
            LOG.error('Movie with plex_id %s not found in DB - cannot delete',
                      plex_id)
            return

        # Remove the plex reference
        self.plex_db.removeItem(plex_id)
        # Remove artwork
        self.artwork.delete_artwork(kodi_id, kodi_type, self.kodicursor)
        if kodi_type == v.KODI_TYPE_MOVIE:
            set_id = self.kodi_db.get_set_id(kodi_id)
            self.kodi_db.modify_countries(kodi_id, kodi_type)
            self.kodi_db.modify_people(kodi_id, kodi_type)
            self.kodi_db.modify_genres(kodi_id, kodi_type)
            self.kodi_db.modify_studios(kodi_id, kodi_type)
            self.kodi_db.modify_tags(kodi_id, kodi_type)
            # Delete kodi movie and file
            self.kodi_db.remove_file(file_id)
            self.kodicursor.execute("DELETE FROM movie WHERE idMovie = ?",
                                    (kodi_id,))
            if set_id:
                self.kodi_db.delete_possibly_empty_set(set_id)
            if v.KODIVERSION >= 17:
                self.kodi_db.remove_uniqueid(kodi_id, kodi_type)
                self.kodi_db.remove_ratings(kodi_id, kodi_type)
        elif kodi_type == v.KODI_TYPE_SET:
            # Delete kodi boxset
            boxset_movies = self.plex_db.getItem_byParentId(kodi_id,
                                                            v.KODI_TYPE_MOVIE)
            for movie in boxset_movies:
                plexid = movie[0]
                movieid = movie[1]
                self.kodi_db.remove_from_set(movieid)
                # Update plex reference
                self.plex_db.updateParentId(plexid, None)
            self.kodicursor.execute("DELETE FROM sets WHERE idSet = ?",
                                    (kodi_id,))
        LOG.debug("Deleted %s %s from kodi database", kodi_type, plex_id)


class TVShows(Items):
    """
    For Plex library-type TV shows
    """
    @utils.catch_exceptions(warnuser=True)
    def add_update(self, item, viewtag=None, viewid=None):
        """
        Process a single show
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        api = API(item)
        update_item = True
        itemid = api.plex_id()
        LOG.debug('Adding show with plex_id %s', itemid)
        if not itemid:
            LOG.error("Cannot parse XML data for TV show")
            return
        update_item = True
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            showid = plex_dbitem[0]
            pathid = plex_dbitem[2]
        except TypeError:
            update_item = False
            kodicursor.execute("select coalesce(max(idShow),0) from tvshow")
            showid = kodicursor.fetchone()[0] + 1
        else:
            # Verification the item is still in Kodi
            query = "SELECT * FROM tvshow WHERE idShow = ?"
            kodicursor.execute(query, (showid,))
            try:
                kodicursor.fetchone()[0]
            except TypeError:
                # item is not found, let's recreate it.
                update_item = False
                LOG.info("showid: %s missing from Kodi, repairing the entry.",
                         showid)

        # fileId information
        checksum = api.checksum()
        # item details
        genres = api.genre_list()
        title, sorttitle = api.titles()
        plot = api.plot()
        rating = api.audience_rating()
        votecount = None
        premieredate = api.premiere_date()
        tvdb = api.provider('tvdb')
        mpaa = api.content_rating()
        genre = api.list_to_string(genres)
        studios = api.music_studio_list()
        collections = api.collection_list()
        try:
            studio = studios[0]
        except IndexError:
            studio = None

        # GET THE FILE AND PATH #####
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            playurl = api.validate_playurl(api.tv_show_path(),
                                           api.plex_type(),
                                           folder=True)
            if playurl is None:
                return
            if "\\" in playurl:
                # Local path
                path = "%s\\" % playurl
                toplevelpath = "%s\\" % dirname(dirname(path))
            else:
                # Network path
                path = "%s/" % playurl
                toplevelpath = "%s/" % dirname(dirname(path))
            toppathid = self.kodi_db.add_video_path(
                toplevelpath,
                content='tvshows',
                scraper='metadata.local')
        else:
            # Set plugin path
            toplevelpath = "plugin://%s.tvshows/" % v.ADDON_ID
            path = "%s%s/" % (toplevelpath, itemid)
            # Do NOT set a parent id because addon-path cannot be "stacked"
            toppathid = None

        pathid = self.kodi_db.add_video_path(path,
                                             date_added=api.date_created(),
                                             id_parent_path=toppathid)
        # UPDATE THE TVSHOW #####
        if update_item:
            LOG.info("UPDATE tvshow itemid: %s - Title: %s", itemid, title)
            # Add reference is idempotent; the call here updates also fileid
            # and pathid when item is moved or renamed
            plex_db.addReference(itemid,
                                 v.PLEX_TYPE_SHOW,
                                 showid,
                                 v.KODI_TYPE_SHOW,
                                 kodi_pathid=pathid,
                                 checksum=checksum,
                                 view_id=viewid)
            if v.KODIVERSION >= 17:
                # update new ratings Kodi 17
                rating_id = self.kodi_db.get_ratingid(showid, v.KODI_TYPE_SHOW)
                self.kodi_db.update_ratings(showid,
                                            v.KODI_TYPE_SHOW,
                                            "default",
                                            rating,
                                            votecount,
                                            rating_id)
                # update new uniqueid Kodi 17
                if tvdb is not None:
                    uniqueid = self.kodi_db.get_uniqueid(showid,
                                                         v.KODI_TYPE_SHOW)
                    self.kodi_db.update_uniqueid(showid,
                                                 v.KODI_TYPE_SHOW,
                                                 tvdb,
                                                 "unknown",
                                                 uniqueid)
                else:
                    self.kodi_db.remove_uniqueid(showid, v.KODI_TYPE_SHOW)
                    uniqueid = -1
                # Update the tvshow entry
                query = '''
                    UPDATE tvshow
                    SET c00 = ?, c01 = ?, c04 = ?, c05 = ?, c08 = ?, c09 = ?,
                        c12 = ?, c13 = ?, c14 = ?, c15 = ?
                    WHERE idShow = ?
                '''
                kodicursor.execute(query, (title, plot, rating_id,
                                           premieredate, genre, title,
                                           uniqueid, mpaa, studio, sorttitle,
                                           showid))
            else:
                # Update the tvshow entry
                query = '''
                    UPDATE tvshow
                    SET c00 = ?, c01 = ?, c04 = ?, c05 = ?, c08 = ?, c09 = ?,
                        c12 = ?, c13 = ?, c14 = ?, c15 = ?
                    WHERE idShow = ?
                '''
                kodicursor.execute(query, (title, plot, rating, premieredate,
                                           genre, title, tvdb, mpaa, studio,
                                           sorttitle, showid))

        # OR ADD THE TVSHOW #####
        else:
            LOG.info("ADD tvshow itemid: %s - Title: %s", itemid, title)
            # Link the path
            query = "INSERT INTO tvshowlinkpath(idShow, idPath) values (?, ?)"
            kodicursor.execute(query, (showid, pathid))
            # Create the reference in plex table
            plex_db.addReference(itemid,
                                 v.PLEX_TYPE_SHOW,
                                 showid,
                                 v.KODI_TYPE_SHOW,
                                 kodi_pathid=pathid,
                                 checksum=checksum,
                                 view_id=viewid)
            if v.KODIVERSION >= 17:
                # add new ratings Kodi 17
                rating_id = self.kodi_db.get_ratingid(showid, v.KODI_TYPE_SHOW)
                self.kodi_db.add_ratings(rating_id,
                                         showid,
                                         v.KODI_TYPE_SHOW,
                                         "default",
                                         rating,
                                         votecount)
                # add new uniqueid Kodi 17
                if tvdb is not None:
                    uniqueid = self.kodi_db.get_uniqueid(showid,
                                                         v.KODI_TYPE_SHOW)
                    self.kodi_db.add_uniqueid(uniqueid,
                                              showid,
                                              v.KODI_TYPE_SHOW,
                                              tvdb,
                                              "unknown")
                else:
                    uniqueid = -1
                # Create the tvshow entry
                query = '''
                    INSERT INTO tvshow(
                        idShow, c00, c01, c04, c05, c08, c09, c12, c13, c14,
                        c15)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                kodicursor.execute(query, (showid, title, plot, rating_id,
                                           premieredate, genre, title,
                                           uniqueid, mpaa, studio, sorttitle))
            else:
                # Create the tvshow entry
                query = '''
                    INSERT INTO tvshow(
                        idShow, c00, c01, c04, c05, c08, c09, c12, c13, c14,
                        c15)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                kodicursor.execute(query, (showid, title, plot, rating,
                                           premieredate, genre, title, tvdb,
                                           mpaa, studio, sorttitle))

        self.kodi_db.modify_people(showid, v.KODI_TYPE_SHOW, api.people_list())
        self.kodi_db.modify_genres(showid, v.KODI_TYPE_SHOW, genres)
        artwork.modify_artwork(api.artwork(),
                               showid,
                               v.KODI_TYPE_SHOW,
                               kodicursor)
        # Process studios
        self.kodi_db.modify_studios(showid, v.KODI_TYPE_SHOW, studios)
        # Process tags: view, PMS collection tags
        tags = [viewtag]
        tags.extend([i for _, i in collections])
        self.kodi_db.modify_tags(showid, v.KODI_TYPE_SHOW, tags)

    @utils.catch_exceptions(warnuser=True)
    def add_updateSeason(self, item, viewtag=None, viewid=None):
        """
        Process a single season of a certain tv show
        """
        api = API(item)
        plex_id = api.plex_id()
        LOG.debug('Adding season with plex_id %s', plex_id)
        if not plex_id:
            LOG.error('Error getting plex_id for season, skipping')
            return
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        seasonnum = api.season_number()
        # Get parent tv show Plex id
        plexshowid = api.parent_plex_id()
        # Get Kodi showid
        plex_dbitem = plex_db.getItem_byId(plexshowid)
        try:
            showid = plex_dbitem[0]
        except TypeError:
            LOG.error('Could not find parent tv show for season %s. '
                      'Skipping season for now.', plex_id)
            return
        seasonid = self.kodi_db.add_season(showid, seasonnum)
        checksum = api.checksum()
        # Check whether Season already exists
        plex_dbitem = plex_db.getItem_byId(plex_id)
        update_item = False if plex_dbitem is None else True
        artwork.modify_artwork(api.artwork(),
                               seasonid,
                               v.KODI_TYPE_SEASON,
                               kodicursor)
        if update_item:
            # Update a reference: checksum in plex table
            plex_db.updateReference(plex_id, checksum)
        else:
            # Create the reference in plex table
            plex_db.addReference(plex_id,
                                 v.PLEX_TYPE_SEASON,
                                 seasonid,
                                 v.KODI_TYPE_SEASON,
                                 parent_id=showid,
                                 view_id=viewid,
                                 checksum=checksum)

    @utils.catch_exceptions(warnuser=True)
    def add_updateEpisode(self, item, viewtag=None, viewid=None):
        """
        Process single episode
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        api = API(item)
        update_item = True
        itemid = api.plex_id()
        LOG.debug('Adding episode with plex_id %s', itemid)
        if not itemid:
            LOG.error('Error getting itemid for episode, skipping')
            return
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            episodeid = plex_dbitem[0]
            old_fileid = plex_dbitem[1]
            pathid = plex_dbitem[2]
        except TypeError:
            update_item = False
            # episodeid
            kodicursor.execute('SELECT COALESCE(MAX(idEpisode),0) FROM episode')
            episodeid = kodicursor.fetchone()[0] + 1
        else:
            # Verification the item is still in Kodi
            query = 'SELECT * FROM episode WHERE idEpisode = ?'
            kodicursor.execute(query, (episodeid,))
            try:
                kodicursor.fetchone()[0]
            except TypeError:
                # item is not found, let's recreate it.
                update_item = False
                LOG.info('episodeid: %s missing from Kodi, repairing entry.',
                         episodeid)

        # fileId information
        checksum = api.checksum()
        dateadded = api.date_created()
        userdata = api.userdata()
        playcount = userdata['PlayCount']
        dateplayed = userdata['LastPlayedDate']
        tvdb = api.provider('tvdb')
        votecount = None

        # item details
        peoples = api.people()
        director = api.list_to_string(peoples['Director'])
        writer = api.list_to_string(peoples['Writer'])
        title, _ = api.titles()
        plot = api.plot()
        rating = userdata['Rating']
        resume, runtime = api.resume_runtime()
        premieredate = api.premiere_date()

        # episode details
        series_id, _, season, episode = api.episode_data()

        if season is None:
            season = -1
        if episode is None:
            episode = -1
        airs_before_season = "-1"
        airs_before_episode = "-1"

        # Get season id
        show = plex_db.getItem_byId(series_id)
        try:
            showid = show[0]
        except TypeError:
            LOG.error("Parent tvshow now found, skip item")
            return False
        seasonid = self.kodi_db.add_season(showid, season)

        # GET THE FILE AND PATH #####
        do_indirect = not state.DIRECT_PATHS
        if state.DIRECT_PATHS:
            playurl = api.file_path(force_first_media=True)
            if playurl is None:
                do_indirect = True
            else:
                playurl = api.validate_playurl(playurl, v.PLEX_TYPE_EPISODE)
                if "\\" in playurl:
                    # Local path
                    filename = playurl.rsplit("\\", 1)[1]
                else:
                    # Network share
                    filename = playurl.rsplit("/", 1)[1]
                path = playurl.replace(filename, "")
                parent_path_id = self.kodi_db.parent_path_id(path)
                pathid = self.kodi_db.add_video_path(path,
                                                     id_parent_path=parent_path_id)
        if do_indirect:
            # Set plugin path - do NOT use "intermediate" paths for the show
            # as with direct paths!
            filename = api.file_name(force_first_media=True)
            path = 'plugin://%s.tvshows/%s/' % (v.ADDON_ID, series_id)
            filename = ('%s?plex_id=%s&plex_type=%s&mode=play&filename=%s'
                        % (path, itemid, v.PLEX_TYPE_EPISODE, filename))
            playurl = filename
            # Root path tvshows/ already saved in Kodi DB
            pathid = self.kodi_db.add_video_path(path)

        # add/retrieve pathid and fileid
        # if the path or file already exists, the calls return current value
        fileid = self.kodi_db.add_file(filename, pathid, dateadded)

        # UPDATE THE EPISODE #####
        if update_item:
            LOG.info("UPDATE episode itemid: %s", itemid)
            if fileid != old_fileid:
                LOG.debug('Removing old file entry: %s', old_fileid)
                self.kodi_db.remove_file(old_fileid)
            # Update the movie entry
            if v.KODIVERSION >= 17:
                # update new ratings Kodi 17
                ratingid = self.kodi_db.get_ratingid(episodeid,
                                                     v.KODI_TYPE_EPISODE)
                self.kodi_db.update_ratings(episodeid,
                                            v.KODI_TYPE_EPISODE,
                                            "default",
                                            rating,
                                            votecount,
                                            ratingid)
                # update new uniqueid Kodi 17
                uniqueid = self.kodi_db.get_uniqueid(episodeid,
                                                     v.KODI_TYPE_EPISODE)
                self.kodi_db.update_uniqueid(episodeid,
                                             v.KODI_TYPE_EPISODE,
                                             tvdb,
                                             "tvdb",
                                             uniqueid)
                query = '''
                    UPDATE episode
                    SET c00 = ?, c01 = ?, c03 = ?, c04 = ?, c05 = ?, c09 = ?,
                        c10 = ?, c12 = ?, c13 = ?, c14 = ?, c15 = ?, c16 = ?,
                        c18 = ?, c19 = ?, idFile=?, idSeason = ?,
                        userrating = ?
                    WHERE idEpisode = ?
                '''
                kodicursor.execute(query, (title, plot, ratingid, writer,
                    premieredate, runtime, director, season, episode, title,
                    airs_before_season, airs_before_episode, playurl, pathid,
                    fileid, seasonid, userdata['UserRating'], episodeid))
            else:
                # Kodi Jarvis
                query = '''
                    UPDATE episode
                    SET c00 = ?, c01 = ?, c03 = ?, c04 = ?, c05 = ?, c09 = ?,
                        c10 = ?, c12 = ?, c13 = ?, c14 = ?, c15 = ?, c16 = ?,
                        c18 = ?, c19 = ?, idFile=?, idSeason = ?
                    WHERE idEpisode = ?
                '''
                kodicursor.execute(query, (title, plot, rating, writer,
                    premieredate, runtime, director, season, episode, title,
                    airs_before_season, airs_before_episode, playurl, pathid,
                    fileid, seasonid, episodeid))
            # Update parentid reference
            plex_db.updateParentId(itemid, seasonid)

        # OR ADD THE EPISODE #####
        else:
            LOG.info("ADD episode itemid: %s - Title: %s", itemid, title)
            # Create the episode entry
            if v.KODIVERSION >= 17:
                # add new ratings Kodi 17
                rating_id = self.kodi_db.get_ratingid(episodeid,
                                                      v.KODI_TYPE_EPISODE)
                self.kodi_db.add_ratings(rating_id,
                                         episodeid,
                                         v.KODI_TYPE_EPISODE,
                                         "default",
                                         rating,
                                         votecount)
                # add new uniqueid Kodi 17
                uniqueid = self.kodi_db.get_uniqueid(episodeid,
                                                     v.KODI_TYPE_EPISODE)
                self.kodi_db.add_uniqueid(uniqueid,
                                          episodeid,
                                          v.KODI_TYPE_EPISODE,
                                          tvdb,
                                          "tvdb")
                query = '''
                    INSERT INTO episode( idEpisode, idFile, c00, c01, c03, c04,
                        c05, c09, c10, c12, c13, c14, idShow, c15, c16, c18,
                        c19, idSeason, userrating)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?)
                '''
                kodicursor.execute(query, (episodeid, fileid, title, plot,
                    rating_id, writer, premieredate, runtime, director, season,
                    episode, title, showid, airs_before_season,
                    airs_before_episode, playurl, pathid, seasonid,
                    userdata['UserRating']))
            else:
                # Kodi Jarvis
                query = '''
                    INSERT INTO episode( idEpisode, idFile, c00, c01, c03, c04,
                        c05, c09, c10, c12, c13, c14, idShow, c15, c16, c18,
                        c19, idSeason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?)
                    '''
                kodicursor.execute(query, (episodeid, fileid, title, plot,
                    rating, writer, premieredate, runtime, director, season,
                    episode, title, showid, airs_before_season,
                    airs_before_episode, playurl, pathid, seasonid))

        # Create or update the reference in plex table Add reference is
        # idempotent; the call here updates also fileid and pathid when item is
        # moved or renamed
        plex_db.addReference(itemid,
                             v.PLEX_TYPE_EPISODE,
                             episodeid,
                             v.KODI_TYPE_EPISODE,
                             kodi_fileid=fileid,
                             kodi_pathid=pathid,
                             parent_id=seasonid,
                             checksum=checksum,
                             view_id=viewid)
        self.kodi_db.modify_people(episodeid,
                                   v.KODI_TYPE_EPISODE,
                                   api.people_list())
        artwork.modify_artwork(api.artwork(),
                               episodeid,
                               v.KODI_TYPE_EPISODE,
                               kodicursor)
        streams = api.mediastreams()
        self.kodi_db.modify_streams(fileid, streams, runtime)
        self.kodi_db.set_resume(fileid,
                                resume,
                                runtime,
                                playcount,
                                dateplayed,
                                None)  # Do send None, we check here
        if not state.DIRECT_PATHS:
            # need to set a SECOND file entry for a path without plex show id
            filename = api.file_name(force_first_media=True)
            path = 'plugin://%s.tvshows/' % v.ADDON_ID
            # Filename is exactly the same, WITH plex show id!
            filename = ('%s%s/?plex_id=%s&plex_type=%s&mode=play&filename=%s'
                        % (path, series_id, itemid, v.PLEX_TYPE_EPISODE,
                           filename))
            pathid = self.kodi_db.add_video_path(path)
            fileid = self.kodi_db.add_file(filename, pathid, dateadded)
            self.kodi_db.set_resume(fileid,
                                    resume,
                                    runtime,
                                    playcount,
                                    dateplayed,
                                    None)  # Do send None - 2nd entry

    @utils.catch_exceptions(warnuser=True)
    def remove(self, plex_id):
        """
        Remove the entire TV shows object (show, season or episode) including
        all associated entries from the Kodi DB.
        """
        plex_dbitem = self.plex_db.getItem_byId(plex_id)
        if plex_dbitem is None:
            LOG.debug('Cannot delete plex_id %s - not found in DB', plex_id)
            return
        kodi_id = plex_dbitem[0]
        file_id = plex_dbitem[1]
        parent_id = plex_dbitem[3]
        kodi_type = plex_dbitem[4]
        LOG.info("Removing %s with kodi_id: %s file_id: %s parent_id: %s",
                 kodi_type, kodi_id, file_id, parent_id)

        # Remove the plex reference
        self.plex_db.removeItem(plex_id)

        ##### EPISODE #####
        if kodi_type == v.KODI_TYPE_EPISODE:
            # Delete episode, verify season and tvshow
            self.remove_episode(kodi_id, file_id)
            # Season verification
            season = self.plex_db.getItem_byKodiId(parent_id,
                                                   v.KODI_TYPE_SEASON)
            if season is not None:
                if not self.plex_db.getItem_byParentId(parent_id,
                                                       v.KODI_TYPE_EPISODE):
                    # No episode left for season - so delete the season
                    self.remove_season(parent_id)
                    self.plex_db.removeItem(season[0])
                show = self.plex_db.getItem_byKodiId(season[1],
                                                     v.KODI_TYPE_SHOW)
                if show is not None:
                    if not self.plex_db.getItem_byParentId(season[1],
                                                           v.KODI_TYPE_SEASON):
                        # No seasons for show left - so delete entire show
                        self.remove_show(season[1])
                        self.plex_db.removeItem(show[0])
                else:
                    LOG.error('No show found in Plex DB for season %s', season)
            else:
                LOG.error('No season found in Plex DB!')
        ##### SEASON #####
        elif kodi_type == v.KODI_TYPE_SEASON:
            # Remove episodes, season, verify tvshow
            for episode in self.plex_db.getItem_byParentId(
                    kodi_id, v.KODI_TYPE_EPISODE):
                self.remove_episode(episode[1], episode[2])
                self.plex_db.removeItem(episode[0])
            # Remove season
            self.remove_season(kodi_id)
            # Show verification
            if not self.plex_db.getItem_byParentId(parent_id,
                                                   v.KODI_TYPE_SEASON):
                # There's no other season left, delete the show
                self.remove_show(parent_id)
                self.plex_db.removeItem_byKodiId(parent_id, v.KODI_TYPE_SHOW)
        ##### TVSHOW #####
        elif kodi_type == v.KODI_TYPE_SHOW:
            # Remove episodes, seasons and the tvshow itself
            for season in self.plex_db.getItem_byParentId(kodi_id,
                                                          v.KODI_TYPE_SEASON):
                for episode in self.plex_db.getItem_byParentId(
                        season[1], v.KODI_TYPE_EPISODE):
                    self.remove_episode(episode[1], episode[2])
                    self.plex_db.removeItem(episode[0])
                self.remove_season(season[1])
                self.plex_db.removeItem(season[0])
            self.remove_show(kodi_id)

        LOG.debug("Deleted %s %s from Kodi database", kodi_type, plex_id)

    def remove_show(self, kodi_id):
        """
        Remove a TV show, and only the show, no seasons or episodes
        """
        self.kodi_db.modify_genres(kodi_id, v.KODI_TYPE_SHOW)
        self.kodi_db.modify_studios(kodi_id, v.KODI_TYPE_SHOW)
        self.kodi_db.modify_tags(kodi_id, v.KODI_TYPE_SHOW)
        self.artwork.delete_artwork(kodi_id,
                                    v.KODI_TYPE_SHOW,
                                    self.kodicursor)
        self.kodicursor.execute("DELETE FROM tvshow WHERE idShow = ?",
                                (kodi_id,))
        if v.KODIVERSION >= 17:
            self.kodi_db.remove_uniqueid(kodi_id, v.KODI_TYPE_SHOW)
            self.kodi_db.remove_ratings(kodi_id, v.KODI_TYPE_SHOW)
        LOG.debug("Removed tvshow: %s", kodi_id)

    def remove_season(self, kodi_id):
        """
        Remove a season, and only a season, not the show or episodes
        """
        self.artwork.delete_artwork(kodi_id,
                                    v.KODI_TYPE_SEASON,
                                    self.kodicursor)
        self.kodicursor.execute("DELETE FROM seasons WHERE idSeason = ?",
                                (kodi_id,))
        LOG.debug("Removed season: %s", kodi_id)

    def remove_episode(self, kodi_id, file_id):
        """
        Remove an episode, and episode only from the Kodi DB (not Plex DB)
        """
        self.kodi_db.modify_people(kodi_id, v.KODI_TYPE_EPISODE)
        self.kodi_db.remove_file(file_id, plex_type=v.PLEX_TYPE_EPISODE)
        self.artwork.delete_artwork(kodi_id,
                                    v.KODI_TYPE_EPISODE,
                                    self.kodicursor)
        self.kodicursor.execute("DELETE FROM episode WHERE idEpisode = ?",
                                (kodi_id,))
        if v.KODIVERSION >= 17:
            self.kodi_db.remove_uniqueid(kodi_id, v.KODI_TYPE_EPISODE)
            self.kodi_db.remove_ratings(kodi_id, v.KODI_TYPE_EPISODE)
        LOG.debug("Removed episode: %s", kodi_id)


class Music(Items):
    """
    For Plex library-type music. Also works for premium music libraries
    """
    def __enter__(self):
        """
        OVERWRITE this method, because we need to open another DB.
        Open DB connections and cursors
        """
        self.plexconn = utils.kodi_sql('plex')
        self.plexcursor = self.plexconn.cursor()
        # Here it is, not 'video' but 'music'
        self.kodiconn = utils.kodi_sql('music')
        self.kodicursor = self.kodiconn.cursor()
        self.plex_db = plexdb.Plex_DB_Functions(self.plexcursor)
        self.kodi_db = kodidb.KodiDBMethods(self.kodicursor)
        return self

    @utils.catch_exceptions(warnuser=True)
    def add_updateArtist(self, item, viewtag=None, viewid=None):
        """
        Adds a single artist
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        api = API(item)

        update_item = True
        itemid = api.plex_id()
        LOG.debug('Adding artist with plex_id %s', itemid)
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            artistid = plex_dbitem[0]
        except TypeError:
            update_item = False

        # The artist details #####
        lastScraped = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dateadded = api.date_created()
        checksum = api.checksum()

        name, _ = api.titles()
        # musicBrainzId = api.provider('MusicBrainzArtist')
        musicBrainzId = None
        genres = ' / '.join(api.genre_list())
        bio = api.plot()

        # Associate artwork
        artworks = api.artwork()
        if 'poster' in artworks:
            thumb = "<thumb>%s</thumb>" % artworks['poster']
        else:
            thumb = None
        if 'fanart' in artworks:
            fanart = "<fanart>%s</fanart>" % artworks['fanart']
        else:
            fanart = None

        # UPDATE THE ARTIST #####
        if update_item:
            LOG.info("UPDATE artist itemid: %s - Name: %s", itemid, name)
            # Update the checksum in plex table
            plex_db.updateReference(itemid, checksum)

        # OR ADD THE ARTIST #####
        else:
            LOG.info("ADD artist itemid: %s - Name: %s", itemid, name)
            # safety checks: It looks like plex supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            artistid = self.kodi_db.add_artist(name, musicBrainzId)
            # Create the reference in plex table
            plex_db.addReference(itemid,
                                 v.PLEX_TYPE_ARTIST,
                                 artistid,
                                 v.KODI_TYPE_ARTIST,
                                 view_id=viewid,
                                 checksum=checksum)

        # Process the artist
        if v.KODIVERSION >= 16:
            query = '''
                UPDATE artist
                SET strGenres = ?, strBiography = ?, strImage = ?,
                    strFanart = ?, lastScraped = ?
                WHERE idArtist = ?
            '''
            kodicursor.execute(query, (genres, bio, thumb, fanart,
                                       lastScraped, artistid))
        else:
            query = '''
                UPDATE artist
                SET strGenres = ?, strBiography = ?, strImage = ?,
                    strFanart = ?, lastScraped = ?, dateAdded = ?
                WHERE idArtist = ?
            '''
            kodicursor.execute(query, (genres, bio, thumb, fanart, lastScraped,
                                       dateadded, artistid))

        # Update artwork
        artwork.modify_artwork(artworks,
                               artistid,
                               v.KODI_TYPE_ARTIST,
                               kodicursor)

    @utils.catch_exceptions(warnuser=True)
    def add_updateAlbum(self, item, viewtag=None, viewid=None, children=None,
                        scan_children=True):
        """
        Adds a single music album
            children: list of child xml's, so in this case songs
            scan_children: set to False if you don't want to add children
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        api = API(item)

        update_item = True
        plex_id = api.plex_id()
        LOG.debug('Adding album with plex_id %s', plex_id)
        if not plex_id:
            LOG.error('Error processing Album, skipping')
            return
        plex_dbitem = plex_db.getItem_byId(plex_id)
        try:
            album_id = plex_dbitem[0]
        except TypeError:
            update_item = False

        # The album details #####
        lastScraped = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        userdata = api.userdata()
        checksum = api.checksum()

        name, _ = api.titles()
        # musicBrainzId = api.provider('MusicBrainzAlbum')
        musicBrainzId = None
        year = api.year()
        self.genres = api.genre_list()
        self.genre = ' / '.join(self.genres)
        bio = api.plot()
        rating = userdata['UserRating']
        studio = api.music_studio()
        artistname = item.attrib.get('parentTitle')
        if not artistname:
            artistname = item.attrib.get('originalTitle')
        # See if we have a compilation - Plex does NOT feature a compilation
        # flag for albums
        self.compilation = 0
        for child in children:
            if child.attrib.get('originalTitle') is not None:
                self.compilation = 1
                break
        # Associate artwork
        artworks = api.artwork()
        if 'poster' in artworks:
            thumb = "<thumb>%s</thumb>" % artworks['poster']
        else:
            thumb = None

        # UPDATE THE ALBUM #####
        if update_item:
            LOG.info("UPDATE album plex_id: %s - Name: %s", plex_id, name)
            # Update the checksum in plex table
            plex_db.updateReference(plex_id, checksum)

        # OR ADD THE ALBUM #####
        else:
            LOG.info("ADD album plex_id: %s - Name: %s", plex_id, name)
            # safety checks: It looks like plex supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            album_id = self.kodi_db.add_album(name, musicBrainzId)
            # Create the reference in plex table
            plex_db.addReference(plex_id,
                                 v.PLEX_TYPE_ALBUM,
                                 album_id,
                                 v.KODI_TYPE_ALBUM,
                                 view_id=viewid,
                                 checksum=checksum)

        # Process the album info
        if v.KODIVERSION >= 18:
            # Kodi Leia
            query = '''
                UPDATE album
                SET strArtistDisp = ?, iYear = ?, strGenres = ?, strReview = ?,
                    strImage = ?, iUserrating = ?, lastScraped = ?,
                    strReleaseType = ?, strLabel = ?, bCompilation = ?
                WHERE idAlbum = ?
            '''
            kodicursor.execute(query, (artistname, year, self.genre, bio,
                                       thumb, rating, lastScraped,
                                       v.KODI_TYPE_ALBUM, studio,
                                       self.compilation, album_id))
        elif v.KODIVERSION == 17:
            # Kodi Krypton
            query = '''
                UPDATE album
                SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?,
                    strImage = ?, iUserrating = ?, lastScraped = ?,
                    strReleaseType = ?, strLabel = ?, bCompilation = ?
                WHERE idAlbum = ?
            '''
            kodicursor.execute(query, (artistname, year, self.genre, bio,
                                       thumb, rating, lastScraped,
                                       v.KODI_TYPE_ALBUM, studio,
                                       self.compilation, album_id))
        elif v.KODIVERSION == 16:
            # Kodi Jarvis
            query = '''
                UPDATE album
                SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?,
                    strImage = ?, iRating = ?, lastScraped = ?,
                    strReleaseType = ?, strLabel = ?, bCompilation = ?
                WHERE idAlbum = ?
            '''
            kodicursor.execute(query, (artistname, year, self.genre, bio,
                                       thumb, rating, lastScraped,
                                       v.KODI_TYPE_ALBUM, studio,
                                       self.compilation, album_id))

        # Associate the parentid for plex reference
        parent_id = api.parent_plex_id()
        artist_id = None
        if parent_id is not None:
            try:
                artist_id = plex_db.getItem_byId(parent_id)[0]
            except TypeError:
                LOG.info('Artist %s does not yet exist in Plex DB', parent_id)
                artist = PF.GetPlexMetadata(parent_id)
                try:
                    artist[0].attrib
                except (TypeError, IndexError, AttributeError):
                    LOG.error('Could not get artist xml for %s', parent_id)
                else:
                    self.add_updateArtist(artist[0])
                    plex_dbartist = plex_db.getItem_byId(parent_id)
                    try:
                        artist_id = plex_dbartist[0]
                    except TypeError:
                        LOG.error('Adding artist failed for %s', parent_id)
        # Update plex reference with the artist_id
        plex_db.updateParentId(plex_id, artist_id)
        # Add artist to album
        query = '''
            INSERT OR REPLACE INTO album_artist(idArtist, idAlbum, strArtist)
            VALUES (?, ?, ?)
        '''
        kodicursor.execute(query, (artist_id, album_id, artistname))
        # Update discography
        query = '''
            INSERT OR REPLACE INTO discography(idArtist, strAlbum, strYear)
            VALUES (?, ?, ?)
        '''
        kodicursor.execute(query, (artist_id, name, year))
        if v.KODIVERSION < 18:
            self.kodi_db.add_music_genres(album_id,
                                          self.genres,
                                          v.KODI_TYPE_ALBUM)
        # Update artwork
        artwork.modify_artwork(artworks,
                               album_id,
                               v.KODI_TYPE_ALBUM,
                               kodicursor)
        # Add all children - all tracks
        if scan_children:
            for child in children:
                self.add_updateSong(child, viewtag, viewid, item)

    @utils.catch_exceptions(warnuser=True)
    def add_updateSong(self, item, viewtag=None, viewid=None, album_xml=None):
        """
        Process single song
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        api = API(item)
        update_item = True
        itemid = api.plex_id()
        LOG.debug('Adding song with plex_id %s', itemid)
        if not itemid:
            LOG.error('Error processing Song; skipping')
            return
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            songid = plex_dbitem[0]
            pathid = plex_dbitem[2]
            albumid = plex_dbitem[3]
        except TypeError:
            # Songid not found
            update_item = False
            kodicursor.execute("select coalesce(max(idSong),0) from song")
            songid = kodicursor.fetchone()[0] + 1

        # The song details #####
        checksum = api.checksum()
        dateadded = api.date_created()
        userdata = api.userdata()
        playcount = userdata['PlayCount']
        if playcount is None:
            # This is different to Video DB!
            playcount = 0
        dateplayed = userdata['LastPlayedDate']

        # item details
        title, _ = api.titles()
        # musicBrainzId = api.provider('MusicBrainzTrackId')
        musicBrainzId = None
        try:
            genres = self.genres
            genre = self.genre
        except AttributeError:
            # No parent album - hence no genre information from Plex
            genres = None
            genre = None
        try:
            if self.compilation == 0:
                artists = api.grandparent_title()
            else:
                artists = item.attrib.get('originalTitle')
        except AttributeError:
            # compilation not set
            artists = item.attrib.get('originalTitle', api.grandparent_title())
        tracknumber = int(item.attrib.get('index', 0))
        disc = int(item.attrib.get('parentIndex', 1))
        if disc == 1:
            track = tracknumber
        else:
            track = disc * 2 ** 16 + tracknumber
        year = api.year()
        if not year and album_xml:
            # Plex did not pass year info - get it from the parent album
            album_api = API(album_xml)
            year = album_api.year()
        _, duration = api.resume_runtime()
        rating = userdata['UserRating']
        comment = None
        # Moods
        moods = []
        for entry in item:
            if entry.tag == 'Mood':
                moods.append(entry.attrib['tag'])
        mood = ' / '.join(moods)

        # GET THE FILE AND PATH #####
        do_indirect = not state.DIRECT_PATHS
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            playurl = api.file_path(force_first_media=True)
            if playurl is None:
                # Something went wrong, trying to use non-direct paths
                do_indirect = True
            else:
                playurl = api.validate_playurl(playurl, api.plex_type())
                if playurl is None:
                    return False
                if "\\" in playurl:
                    # Local path
                    filename = playurl.rsplit("\\", 1)[1]
                else:
                    # Network share
                    filename = playurl.rsplit("/", 1)[1]
                path = playurl.replace(filename, "")
        if do_indirect:
            # Plex works a bit differently
            path = "%s%s" % (self.server, item[0][0].attrib.get('key'))
            path = api.attach_plex_token_to_url(path)
            filename = path.rsplit('/', 1)[1]
            path = path.replace(filename, '')

        # UPDATE THE SONG #####
        if update_item:
            LOG.info("UPDATE song itemid: %s - Title: %s with path: %s",
                     itemid, title, path)
            # Update path
            # Use dummy strHash '123' for Kodi
            query = "UPDATE path SET strPath = ?, strHash = ? WHERE idPath = ?"
            kodicursor.execute(query, (path, '123', pathid))

            # Update the song entry
            if v.KODIVERSION >= 18:
                # Kodi Leia
                query = '''
                    UPDATE song
                    SET idAlbum = ?, strArtistDisp = ?, strGenres = ?,
                        strTitle = ?, iTrack = ?, iDuration = ?, iYear = ?,
                        strFilename = ?, iTimesPlayed = ?, lastplayed = ?,
                        rating = ?, comment = ?, mood = ?
                    WHERE idSong = ?
                '''
                kodicursor.execute(query, (albumid, artists, genre, title,
                                           track, duration, year, filename,
                                           playcount, dateplayed, rating,
                                           comment, mood, songid))
            else:
                query = '''
                    UPDATE song
                    SET idAlbum = ?, strArtists = ?, strGenres = ?,
                        strTitle = ?, iTrack = ?, iDuration = ?, iYear = ?,
                        strFilename = ?, iTimesPlayed = ?, lastplayed = ?,
                        rating = ?, comment = ?, mood = ?
                    WHERE idSong = ?
                '''
                kodicursor.execute(query, (albumid, artists, genre, title,
                                           track, duration, year, filename,
                                           playcount, dateplayed, rating,
                                           comment, mood, songid))

            # Update the checksum in plex table
            plex_db.updateReference(itemid, checksum)

        # OR ADD THE SONG #####
        else:
            LOG.info("ADD song itemid: %s - Title: %s", itemid, title)

            # Add path
            pathid = self.kodi_db.add_music_path(path, hash_string="123")

            try:
                # Get the album
                plex_dbalbum = plex_db.getItem_byId(api.parent_plex_id())
                albumid = plex_dbalbum[0]
            except KeyError:
                # Verify if there's an album associated.
                album_name = item.get('parentTitle')
                if album_name:
                    LOG.info("Creating virtual music album for song: %s.",
                             itemid)
                    albumid = self.kodi_db.add_album(
                        album_name,
                        api.provider('MusicBrainzAlbum'))
                    plex_db.addReference("%salbum%s" % (itemid, albumid),
                                         v.PLEX_TYPE_ALBUM,
                                         albumid,
                                         v.KODI_TYPE_ALBUM,
                                         view_id=viewid)
                else:
                    # No album Id associated to the song.
                    LOG.error("Song itemid: %s has no albumId associated.",
                              itemid)
                    return False

            except TypeError:
                # No album found. Let's create it
                LOG.info("Album database entry missing.")
                plex_album_id = api.parent_plex_id()
                album = PF.GetPlexMetadata(plex_album_id)
                if album is None or album == 401:
                    LOG.error('Could not download album, abort')
                    return
                self.add_updateAlbum(album[0],
                                     children=[item],
                                     scan_children=False)
                plex_dbalbum = plex_db.getItem_byId(plex_album_id)
                try:
                    albumid = plex_dbalbum[0]
                    LOG.debug("Found albumid: %s", albumid)
                except TypeError:
                    # No album found, create a single's album
                    LOG.info("Failed to add album. Creating singles.")
                    kodicursor.execute(
                        "select coalesce(max(idAlbum),0) from album")
                    albumid = kodicursor.fetchone()[0] + 1
                    if v.KODIVERSION >= 16:
                        # Kodi Jarvis
                        query = '''
                            INSERT INTO album(
                                idAlbum, strGenres, iYear, strReleaseType)
                            VALUES (?, ?, ?, ?)
                        '''
                        kodicursor.execute(query,
                                           (albumid, genre, year, "single"))
                    elif v.KODIVERSION == 15:
                        # Kodi Isengard
                        query = '''
                            INSERT INTO album(
                                idAlbum, strGenres, iYear, dateAdded,
                                strReleaseType)
                            VALUES (?, ?, ?, ?, ?)
                        '''
                        kodicursor.execute(query, (albumid, genre, year,
                                                   dateadded, "single"))
                    else:
                        # Kodi Helix
                        query = '''
                            INSERT INTO album(
                                idAlbum, strGenres, iYear, dateAdded)
                            VALUES (?, ?, ?, ?)
                        '''
                        kodicursor.execute(query, (albumid, genre, year,
                                                   dateadded))

            # Create the song entry
            if v.KODIVERSION >= 18:
                # Kodi Leia
                query = '''
                    INSERT INTO song(
                        idSong, idAlbum, idPath, strArtistDisp, strGenres,
                        strTitle, iTrack, iDuration, iYear, strFileName,
                        strMusicBrainzTrackID, iTimesPlayed, lastplayed,
                        rating, iStartOffset, iEndOffset, mood)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                kodicursor.execute(
                    query, (songid, albumid, pathid, artists, genre, title,
                            track, duration, year, filename, musicBrainzId,
                            playcount, dateplayed, rating, 0, 0, mood))
            else:
                query = '''
                    INSERT INTO song(
                        idSong, idAlbum, idPath, strArtists, strGenres,
                        strTitle, iTrack, iDuration, iYear, strFileName,
                        strMusicBrainzTrackID, iTimesPlayed, lastplayed,
                        rating, iStartOffset, iEndOffset, mood)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                kodicursor.execute(
                    query, (songid, albumid, pathid, artists, genre, title,
                            track, duration, year, filename, musicBrainzId,
                            playcount, dateplayed, rating, 0, 0, mood))

            # Create the reference in plex table
            plex_db.addReference(itemid,
                                 v.PLEX_TYPE_SONG,
                                 songid,
                                 v.KODI_TYPE_SONG,
                                 kodi_pathid=pathid,
                                 parent_id=albumid,
                                 checksum=checksum,
                                 view_id=viewid)
        if v.KODIVERSION < 18:
            # Link song to album
            query = '''
                INSERT OR REPLACE INTO albuminfosong(
                    idAlbumInfoSong, idAlbumInfo, iTrack, strTitle, iDuration)
                VALUES (?, ?, ?, ?, ?)
            '''
            kodicursor.execute(query,
                               (songid, albumid, track, title, duration))
        # Link song to artists
        artist_loop = [{
            'Name': api.grandparent_title(),
            'Id': api.grandparent_id()
        }]
        # for index, artist in enumerate(item['ArtistItems']):
        for index, artist in enumerate(artist_loop):

            artist_name = artist['Name']
            artist_eid = artist['Id']
            artist_edb = plex_db.getItem_byId(artist_eid)
            try:
                artistid = artist_edb[0]
            except TypeError:
                # Artist is missing from plex database, add it.
                artist_xml = PF.GetPlexMetadata(artist_eid)
                if artist_xml is None or artist_xml == 401:
                    LOG.error('Error getting artist, abort')
                    return
                self.add_updateArtist(artist_xml[0])
                artist_edb = plex_db.getItem_byId(artist_eid)
                artistid = artist_edb[0]
            finally:
                if v.KODIVERSION >= 17:
                    # Kodi Krypton
                    query = '''
                        INSERT OR REPLACE INTO song_artist(
                            idArtist, idSong, idRole, iOrder, strArtist)
                        VALUES (?, ?, ?, ?, ?)
                    '''
                    kodicursor.execute(query, (artistid, songid, 1, index,
                                               artist_name))
                    # May want to look into only doing this once?
                    query = '''
                        INSERT OR REPLACE INTO role(idRole, strRole)
                        VALUES (?, ?)
                    '''
                    kodicursor.execute(query, (1, 'Composer'))
                else:
                    query = '''
                        INSERT OR REPLACE INTO song_artist(
                            idArtist, idSong, iOrder, strArtist)
                        VALUES (?, ?, ?, ?)
                    '''
                    kodicursor.execute(query, (artistid, songid, index,
                                               artist_name))
        # Add genres
        if genres:
            self.kodi_db.add_music_genres(songid, genres, v.KODI_TYPE_SONG)
        artworks = api.artwork()
        artwork.modify_artwork(artworks, songid, v.KODI_TYPE_SONG, kodicursor)
        if item.get('parentKey') is None:
            # Update album artwork
            artwork.modify_artwork(artworks,
                                   albumid,
                                   v.KODI_TYPE_ALBUM,
                                   kodicursor)

    @utils.catch_exceptions(warnuser=True)
    def remove(self, plex_id):
        """
        Completely remove the item with plex_id from the Kodi and Plex DBs.
        Orphaned entries will also be deleted.
        """
        plex_dbitem = self.plex_db.getItem_byId(plex_id)
        try:
            kodi_id = plex_dbitem[0]
            file_id = plex_dbitem[1]
            path_id = plex_dbitem[2]
            parent_id = plex_dbitem[3]
            kodi_type = plex_dbitem[4]
            LOG.debug('Removing plex_id %s with kodi_type %s, kodi_id %s, '
                      'parent_id %s, file_id %s, pathid %s',
                      plex_id, kodi_type, kodi_id, parent_id, file_id, path_id)
        except TypeError:
            LOG.debug('Cannot delete item with plex id %s from Kodi', plex_id)
            return
        # Remove the plex reference
        self.plex_db.removeItem(plex_id)
        ##### SONG #####
        if kodi_type == v.KODI_TYPE_SONG:
            # Delete song and orphaned artists and albums
            self._remove_song(kodi_id, path_id=path_id)
            # Album verification
            album = self.plex_db.getItem_byKodiId(parent_id,
                                                  v.KODI_TYPE_ALBUM)
            if not self.plex_db.getItem_byParentId(parent_id,
                                                   v.KODI_TYPE_SONG):
                # No song left for album - so delete the album
                self.plex_db.removeItem(album[0])
                self._remove_album(parent_id)
        ##### ALBUM #####
        elif kodi_type == v.KODI_TYPE_ALBUM:
            # Delete songs, album
            songs = self.plex_db.getItem_byParentId(kodi_id,
                                                    v.KODI_TYPE_SONG)
            for song in songs:
                self._remove_song(song[1], path_id=song[2])
            # Remove songs from Plex table
            self.plex_db.removeItems_byParentId(kodi_id,
                                                v.KODI_TYPE_SONG)
            # Remove the album and associated orphaned entries
            self._remove_album(kodi_id)
        ##### IF ARTIST #####
        elif kodi_type == v.KODI_TYPE_ARTIST:
            # Delete songs, album, artist
            albums = self.plex_db.getItem_byParentId(kodi_id,
                                                     v.KODI_TYPE_ALBUM)
            for album in albums:
                songs = self.plex_db.getItem_byParentId(album[1],
                                                        v.KODI_TYPE_SONG)
                for song in songs:
                    self._remove_song(song[1], path_id=song[2])
                # Remove entries for the songs in the Plex db
                self.plex_db.removeItems_byParentId(album[1], v.KODI_TYPE_SONG)
                # Remove kodi album
                self._remove_album(album[1])
            # Remove album entries in the Plex db
            self.plex_db.removeItems_byParentId(kodi_id, v.KODI_TYPE_ALBUM)
            # Remove artist
            self._remove_artist(kodi_id)
        LOG.debug("Deleted plex_id %s from kodi database", plex_id)

    def _remove_song(self, kodi_id, path_id=None):
        """
        Remove song, orphaned artists and orphaned paths
        """
        if not path_id:
            query = 'SELECT idPath FROM song WHERE idSong = ? LIMIT 1'
            self.kodicursor.execute(query, (kodi_id, ))
            try:
                path_id = self.kodicursor.fetchone()[0]
            except TypeError:
                pass
        artist_to_delete = self.kodi_db.delete_song_from_song_artist(kodi_id)
        if artist_to_delete:
            # Delete the artist reference in the Plex table
            artist = self.plex_db.getItem_byKodiId(artist_to_delete,
                                                   v.KODI_TYPE_ARTIST)
            try:
                plex_id = artist[0]
            except TypeError:
                pass
            else:
                self.plex_db.removeItem(plex_id)
            self._remove_artist(artist_to_delete)
        self.kodicursor.execute('DELETE FROM song WHERE idSong = ?',
                                (kodi_id, ))
        # Check whether we have orphaned path entries
        query = 'SELECT idPath FROM song WHERE idPath = ? LIMIT 1'
        self.kodicursor.execute(query, (path_id, ))
        if not self.kodicursor.fetchone():
            self.kodicursor.execute('DELETE FROM path WHERE idPath = ?',
                                    (path_id, ))
        if v.KODIVERSION < 18:
            self.kodi_db.delete_song_from_song_genre(kodi_id)
            query = 'DELETE FROM albuminfosong WHERE idAlbumInfoSong = ?'
            self.kodicursor.execute(query, (kodi_id, ))
        self.artwork.delete_artwork(kodi_id, v.KODI_TYPE_SONG, self.kodicursor)

    def _remove_album(self, kodi_id):
        '''
        Remove an album
        '''
        self.kodi_db.delete_album_from_discography(kodi_id)
        if v.KODIVERSION < 18:
            self.kodi_db.delete_album_from_album_genre(kodi_id)
            query = 'DELETE FROM albuminfosong WHERE idAlbumInfo = ?'
            self.kodicursor.execute(query, (kodi_id, ))
        self.kodicursor.execute('DELETE FROM album_artist WHERE idAlbum = ?',
                                (kodi_id, ))
        self.kodicursor.execute('DELETE FROM album WHERE idAlbum = ?',
                                (kodi_id, ))
        self.artwork.delete_artwork(kodi_id, v.KODI_TYPE_ALBUM, self.kodicursor)

    def _remove_artist(self, kodi_id):
        '''
        Remove an artist and associated songs and albums
        '''
        self.kodicursor.execute('DELETE FROM album_artist WHERE idArtist = ?',
                                (kodi_id, ))
        self.kodicursor.execute('DELETE FROM artist WHERE idArtist = ?',
                                (kodi_id, ))
        self.kodicursor.execute('DELETE FROM song_artist WHERE idArtist = ?',
                                (kodi_id, ))
        self.kodicursor.execute('DELETE FROM discography WHERE idArtist = ?',
                                (kodi_id, ))
        self.artwork.delete_artwork(kodi_id,
                                    v.KODI_TYPE_ARTIST,
                                    self.kodicursor)
