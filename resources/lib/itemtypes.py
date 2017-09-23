# -*- coding: utf-8 -*-

###############################################################################

import logging
from urllib import urlencode
from ntpath import dirname
from datetime import datetime
from xbmc import sleep

import artwork
from utils import tryEncode, tryDecode, window, kodiSQL, CatchExceptions
import plexdb_functions as plexdb
import kodidb_functions as kodidb

import PlexAPI
from PlexFunctions import GetPlexMetadata
import variables as v
import state

###############################################################################

log = logging.getLogger("PLEX."+__name__)

MARK_PLAYED_AT = 0.90
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
        self.server = window('pms_server')

    def __enter__(self):
        """
        Open DB connections and cursors
        """
        self.plexconn = kodiSQL('plex')
        self.plexcursor = self.plexconn.cursor()
        self.kodiconn = kodiSQL('video')
        self.kodicursor = self.kodiconn.cursor()
        self.plex_db = plexdb.Plex_DB_Functions(self.plexcursor)
        self.kodi_db = kodidb.Kodidb_Functions(self.kodicursor)
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

    @CatchExceptions(warnuser=True)
    def getfanart(self, plex_id, refresh=False):
        """
        Tries to get additional fanart for movies (+sets) and TV shows.

        Returns True if successful, False otherwise
        """
        with plexdb.Get_Plex_DB() as plex_db:
            db_item = plex_db.getItem_byId(plex_id)
        try:
            kodi_id = db_item[0]
            kodi_type = db_item[4]
        except TypeError:
            log.error('Could not get Kodi id for plex id %s, abort getfanart'
                      % plex_id)
            return False
        if refresh is True:
            # Leave the Plex art untouched
            allartworks = None
        else:
            with kodidb.GetKodiDB('video') as kodi_db:
                allartworks = kodi_db.existingArt(kodi_id, kodi_type)
            # Check if we even need to get additional art
            needsupdate = False
            for key, value in allartworks.iteritems():
                if not value and not key == 'BoxRear':
                    needsupdate = True
                    break
            if needsupdate is False:
                log.debug('Already got all fanart for Plex id %s' % plex_id)
                return True

        xml = GetPlexMetadata(plex_id)
        if xml is None:
            # Did not receive a valid XML - skip that item for now
            log.error("Could not get metadata for %s. Skipping that item "
                      "for now" % plex_id)
            return False
        elif xml == 401:
            log.error('HTTP 401 returned by PMS. Too much strain? '
                      'Cancelling sync for now')
            # Kill remaining items in queue (for main thread to cont.)
            return False
        API = PlexAPI.API(xml[0])
        if allartworks is None:
            allartworks = API.getAllArtwork()
        self.artwork.addArtwork(API.getFanartArtwork(allartworks),
                                kodi_id,
                                kodi_type,
                                self.kodicursor)
        # Also get artwork for collections/movie sets
        if kodi_type == v.KODI_TYPE_MOVIE:
            for setname in API.getCollections():
                log.debug('Getting artwork for movie set %s' % setname)
                setid = self.kodi_db.createBoxset(setname)
                self.artwork.addArtwork(API.getSetArtwork(),
                                        setid,
                                        v.KODI_TYPE_SET,
                                        self.kodicursor)
                self.kodi_db.assignBoxset(setid, kodi_id)
        return True

    def updateUserdata(self, xml, viewtag=None, viewid=None):
        """
        Updates the Kodi watched state of the item from PMS. Also retrieves
        Plex resume points for movies in progress.

        viewtag and viewid only serve as dummies
        """
        for mediaitem in xml:
            API = PlexAPI.API(mediaitem)
            # Get key and db entry on the Kodi db side
            db_item = self.plex_db.getItem_byId(API.getRatingKey())
            try:
                fileid = db_item[1]
            except TypeError:
                continue
            # Grab the user's viewcount, resume points etc. from PMS' answer
            userdata = API.getUserData()
            # Write to Kodi DB
            self.kodi_db.addPlaystate(fileid,
                                      userdata['Resume'],
                                      userdata['Runtime'],
                                      userdata['PlayCount'],
                                      userdata['LastPlayedDate'])
            if v.KODIVERSION >= 17:
                self.kodi_db.update_userrating(db_item[0],
                                               db_item[4],
                                               userdata['UserRating'])

    def updatePlaystate(self, item):
        """
        Use with websockets, not xml
        """
        # If the playback was stopped, check whether we need to increment the
        # playcount. PMS won't tell us the playcount via websockets
        if item['state'] in ('stopped', 'ended'):

            # If offset exceeds duration skip update
            if item['viewOffset'] > item['duration']:
                log.error("Error while updating play state, viewOffset "
                          "exceeded duration")
                return

            complete = float(item['viewOffset']) / float(item['duration'])
            log.info('Item %s stopped with completion rate %s percent.'
                     'Mark item played at %s percent.'
                     % (item['ratingKey'], str(complete), MARK_PLAYED_AT), 1)
            if complete >= MARK_PLAYED_AT:
                log.info('Marking as completely watched in Kodi')
                try:
                    item['viewCount'] += 1
                except TypeError:
                    item['viewCount'] = 1
                item['viewOffset'] = 0
        # Do the actual update
        self.kodi_db.addPlaystate(item['file_id'],
                                  item['viewOffset'],
                                  item['duration'],
                                  item['viewCount'],
                                  item['lastViewedAt'])


class Movies(Items):

    @CatchExceptions(warnuser=True)
    def add_update(self, item, viewtag=None, viewid=None):
        # Process single movie
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        # If the item already exist in the local Kodi DB we'll perform a full
        # item update
        # If the item doesn't exist, we'll add it to the database
        update_item = True
        itemid = API.getRatingKey()
        # Cannot parse XML, abort
        if not itemid:
            log.error("Cannot parse XML data for movie")
            return
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            movieid = plex_dbitem[0]
            fileid = plex_dbitem[1]
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
                log.info("movieid: %s missing from Kodi, repairing the entry."
                         % movieid)

        # fileId information
        checksum = API.getChecksum()
        dateadded = API.getDateCreated()
        userdata = API.getUserData()
        playcount = userdata['PlayCount']
        dateplayed = userdata['LastPlayedDate']
        resume = userdata['Resume']
        runtime = userdata['Runtime']

        # item details
        people = API.getPeople()
        writer = API.joinList(people['Writer'])
        director = API.joinList(people['Director'])
        genres = API.getGenres()
        genre = API.joinList(genres)
        title, sorttitle = API.getTitle()
        plot = API.getPlot()
        shortplot = None
        tagline = API.getTagline()
        votecount = None
        collections = API.getCollections()

        rating = userdata['Rating']
        year = API.getYear()
        premieredate = API.getPremiereDate()
        imdb = API.getProvider('imdb')
        mpaa = API.getMpaa()
        countries = API.getCountry()
        country = API.joinList(countries)
        studios = API.getStudios()
        try:
            studio = studios[0]
        except IndexError:
            studio = None

        # Find one trailer
        trailer = None
        extras = API.getExtras()
        for extra in extras:
            # Only get 1st trailer element
            if extra['extraType'] == 1:
                trailer = ("plugin://plugin.video.plexkodiconnect/trailer/?"
                           "id=%s&mode=play") % extra['key']
                break

        # GET THE FILE AND PATH #####
        doIndirect = not state.DIRECT_PATHS
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            playurl = API.getFilePath(forceFirstMediaStream=True)
            if playurl is None:
                # Something went wrong, trying to use non-direct paths
                doIndirect = True
            else:
                playurl = API.validatePlayurl(playurl, API.getType())
                if playurl is None:
                    return False
                if "\\" in playurl:
                    # Local path
                    filename = playurl.rsplit("\\", 1)[1]
                else:
                    # Network share
                    filename = playurl.rsplit("/", 1)[1]
                path = playurl.replace(filename, "")
        if doIndirect:
            # Set plugin path and media flags using real filename
            path = "plugin://plugin.video.plexkodiconnect/movies/"
            params = {
                'filename': API.getKey(),
                'id': itemid,
                'dbid': movieid,
                'mode': "play"
            }
            filename = "%s?%s" % (path, urlencode(params))
            playurl = filename

        # movie table:
        # c22 - playurl
        # c23 - pathid
        # This information is used later by file browser.

        # add/retrieve pathid and fileid
        # if the path or file already exists, the calls return current value
        pathid = self.kodi_db.addPath(path)
        fileid = self.kodi_db.addFile(filename, pathid)

        # UPDATE THE MOVIE #####
        if update_item:
            log.info("UPDATE movie itemid: %s - Title: %s"
                     % (itemid, title))
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
            log.info("ADD movie itemid: %s - Title: %s" % (itemid, title))
            if v.KODIVERSION >= 17:
                # add new ratings Kodi 17
                rating_id = self.kodi_db.create_entry_rating()
                self.kodi_db.add_ratings(rating_id,
                                         movieid,
                                         v.KODI_TYPE_MOVIE,
                                         "default",
                                         rating,
                                         votecount)
                # add new uniqueid Kodi 17
                if imdb is not None:
                    uniqueid = self.kodi_db.create_entry_uniqueid()
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

        # Update the path
        query = ' '.join((

            "UPDATE path",
            "SET strPath = ?, strContent = ?, strScraper = ?, noUpdate = ?",
            "WHERE idPath = ?"
        ))
        kodicursor.execute(query, (path, "movies", "metadata.local", 1, pathid))

        # Update the file
        query = ' '.join((

            "UPDATE files",
            "SET idPath = ?, strFilename = ?, dateAdded = ?",
            "WHERE idFile = ?"
        ))
        kodicursor.execute(query, (pathid, filename, dateadded, fileid))
        
        # Process countries
        self.kodi_db.addCountries(movieid, countries, "movie")
        # Process cast
        self.kodi_db.addPeople(movieid, API.getPeopleList(), "movie")
        # Process genres
        self.kodi_db.addGenres(movieid, genres, "movie")
        # Process artwork
        artwork.addArtwork(API.getAllArtwork(), movieid, "movie", kodicursor)
        # Process stream details
        self.kodi_db.addStreams(fileid, API.getMediaStreams(), runtime)
        # Process studios
        self.kodi_db.addStudios(movieid, studios, "movie")
        # Process tags: view, Plex collection tags
        tags = [viewtag]
        tags.extend(collections)
        if userdata['Favorite']:
            tags.append("Favorite movies")
        self.kodi_db.addTags(movieid, tags, "movie")
        # Add any sets from Plex collection tags
        self.kodi_db.addSets(movieid, collections, kodicursor)
        # Process playstates
        self.kodi_db.addPlaystate(fileid, resume, runtime, playcount, dateplayed)

    def remove(self, itemid):
        # Remove movieid, fileid, plex reference
        plex_db = self.plex_db
        kodicursor = self.kodicursor
        artwork = self.artwork

        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            kodi_id = plex_dbitem[0]
            file_id = plex_dbitem[1]
            kodi_type = plex_dbitem[4]
            log.info("Removing %sid: %s file_id: %s"
                     % (kodi_type, kodi_id, file_id))
        except TypeError:
            return

        # Remove the plex reference
        plex_db.removeItem(itemid)
        # Remove artwork
        artwork.deleteArtwork(kodi_id, kodi_type, kodicursor)

        if kodi_type == v.KODI_TYPE_MOVIE:
            # Delete kodi movie and file
            kodicursor.execute("DELETE FROM movie WHERE idMovie = ?",
                               (kodi_id,))
            kodicursor.execute("DELETE FROM files WHERE idFile = ?",
                               (file_id,))
            if v.KODIVERSION >= 17:
                self.kodi_db.remove_uniqueid(kodi_id, kodi_type)
                self.kodi_db.remove_ratings(kodi_id, kodi_type)
        elif kodi_type == v.KODI_TYPE_SET:
            # Delete kodi boxset
            boxset_movies = plex_db.getItem_byParentId(kodi_id,
                                                       v.KODI_TYPE_MOVIE)
            for movie in boxset_movies:
                plexid = movie[0]
                movieid = movie[1]
                self.kodi_db.removefromBoxset(movieid)
                # Update plex reference
                plex_db.updateParentId(plexid, None)
            kodicursor.execute("DELETE FROM sets WHERE idSet = ?", (kodi_id,))
        log.info("Deleted %s %s from kodi database" % (kodi_type, itemid))


class TVShows(Items):

    @CatchExceptions(warnuser=True)
    def add_update(self, item, viewtag=None, viewid=None):
        # Process single tvshow
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()

        if not itemid:
            log.error("Cannot parse XML data for TV show")
            return
        update_item = True
        force_episodes = False
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
                log.info("showid: %s missing from Kodi, repairing the entry."
                         % showid)
                # Force re-add episodes after the show is re-created.
                force_episodes = True

        # fileId information
        checksum = API.getChecksum()

        # item details
        genres = API.getGenres()
        title, sorttitle = API.getTitle()
        plot = API.getPlot()
        rating = API.getAudienceRating()
        votecount = None
        premieredate = API.getPremiereDate()
        tvdb = API.getProvider('tvdb')
        mpaa = API.getMpaa()
        genre = API.joinList(genres)
        studios = API.getStudios()
        collections = API.getCollections()
        try:
            studio = studios[0]
        except IndexError:
            studio = None

        # GET THE FILE AND PATH #####
        doIndirect = not state.DIRECT_PATHS
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            playurl = API.getTVShowPath()
            if playurl is None:
                # Something went wrong, trying to use non-direct paths
                doIndirect = True
            else:
                playurl = API.validatePlayurl(playurl,
                                              API.getType(),
                                              folder=True)
                if playurl is None:
                    return False
                if "\\" in playurl:
                    # Local path
                    path = "%s\\" % playurl
                    toplevelpath = "%s\\" % dirname(dirname(path))
                else:
                    # Network path
                    path = "%s/" % playurl
                    toplevelpath = "%s/" % dirname(dirname(path))
        if doIndirect:
            # Set plugin path
            toplevelpath = "plugin://plugin.video.plexkodiconnect/tvshows/"
            path = "%s%s/" % (toplevelpath, itemid)

        # Add top path
        toppathid = self.kodi_db.addPath(toplevelpath)
        # add/retrieve pathid and fileid
        # if the path or file already exists, the calls return current value
        pathid = self.kodi_db.addPath(path)
        # UPDATE THE TVSHOW #####
        if update_item:
            log.info("UPDATE tvshow itemid: %s - Title: %s"
                     % (itemid, title))
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
            log.info("ADD tvshow itemid: %s - Title: %s" % (itemid, title))
            query = '''
                UPDATE path
                SET strPath = ?, strContent = ?, strScraper = ?, noUpdate = ?
                WHERE idPath = ?
            '''
            kodicursor.execute(query, (toplevelpath,
                                       "tvshows",
                                       "metadata.local",
                                       1,
                                       toppathid))
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
                rating_id = self.kodi_db.create_entry_rating()
                self.kodi_db.add_ratings(rating_id,
                                         showid,
                                         v.KODI_TYPE_SHOW,
                                         "default",
                                         rating,
                                         votecount)
                # add new uniqueid Kodi 17
                if tvdb is not None:
                    uniqueid = self.kodi_db.create_entry_uniqueid()
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
        # Update the path
        query = '''
            UPDATE path
            SET strPath = ?, strContent = ?, strScraper = ?, noUpdate = ?,
            idParentPath = ?
            WHERE idPath = ?
        '''
        kodicursor.execute(query, (path, None, None, 1, toppathid, pathid))

        # Process cast
        people = API.getPeopleList()
        self.kodi_db.addPeople(showid, people, "tvshow")
        # Process genres
        self.kodi_db.addGenres(showid, genres, "tvshow")
        # Process artwork
        allartworks = API.getAllArtwork()
        artwork.addArtwork(allartworks, showid, "tvshow", kodicursor)
        # Process studios
        self.kodi_db.addStudios(showid, studios, "tvshow")
        # Process tags: view, PMS collection tags
        tags = [viewtag]
        tags.extend(collections)
        self.kodi_db.addTags(showid, tags, "tvshow")

    @CatchExceptions(warnuser=True)
    def add_updateSeason(self, item, viewtag=None, viewid=None):
        API = PlexAPI.API(item)
        plex_id = API.getRatingKey()
        if not plex_id:
            log.error('Error getting plex_id for season, skipping')
            return
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        seasonnum = API.getIndex()
        # Get parent tv show Plex id
        plexshowid = item.attrib.get('parentRatingKey')
        # Get Kodi showid
        plex_dbitem = plex_db.getItem_byId(plexshowid)
        try:
            showid = plex_dbitem[0]
        except:
            log.error('Could not find parent tv show for season %s. '
                      'Skipping season for now.' % (plex_id))
            return

        seasonid = self.kodi_db.addSeason(showid, seasonnum)
        checksum = API.getChecksum()
        # Check whether Season already exists
        update_item = True
        plex_dbitem = plex_db.getItem_byId(plex_id)
        try:
            plexdbItemId = plex_dbitem[0]
        except TypeError:
            update_item = False

        # Process artwork
        allartworks = API.getAllArtwork()
        artwork.addArtwork(allartworks, seasonid, "season", kodicursor)

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

    @CatchExceptions(warnuser=True)
    def add_updateEpisode(self, item, viewtag=None, viewid=None):
        """
        """
        # Process single episode
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        # If the item already exist in the local Kodi DB we'll perform a full
        # item update
        # If the item doesn't exist, we'll add it to the database
        update_item = True
        itemid = API.getRatingKey()
        if not itemid:
            log.error('Error getting itemid for episode, skipping')
            return
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            episodeid = plex_dbitem[0]
            fileid = plex_dbitem[1]
            pathid = plex_dbitem[2]
        except TypeError:
            update_item = False
            # episodeid
            kodicursor.execute("select coalesce(max(idEpisode),0) from episode")
            episodeid = kodicursor.fetchone()[0] + 1

        else:
            # Verification the item is still in Kodi
            query = "SELECT * FROM episode WHERE idEpisode = ?"
            kodicursor.execute(query, (episodeid,))
            try:
                kodicursor.fetchone()[0]
            except TypeError:
                # item is not found, let's recreate it.
                update_item = False
                log.info("episodeid: %s missing from Kodi, repairing entry."
                         % episodeid)

        # fileId information
        checksum = API.getChecksum()
        dateadded = API.getDateCreated()
        userdata = API.getUserData()
        playcount = userdata['PlayCount']
        dateplayed = userdata['LastPlayedDate']
        tvdb = API.getProvider('tvdb')
        votecount = None

        # item details
        peoples = API.getPeople()
        director = API.joinList(peoples['Director'])
        writer = API.joinList(peoples['Writer'])
        title, sorttitle = API.getTitle()
        plot = API.getPlot()
        rating = userdata['Rating']
        resume, runtime = API.getRuntime()
        premieredate = API.getPremiereDate()

        # episode details
        seriesId, seriesName, season, episode = API.getEpisodeDetails()

        if season is None:
            season = -1
        if episode is None:
            episode = -1
            # if item.get('AbsoluteEpisodeNumber'):
            #     # Anime scenario
            #     season = 1
            #     episode = item['AbsoluteEpisodeNumber']
            # else:
            #     season = -1

        # Specials ordering within season
        if item.get('AirsAfterSeasonNumber'):
            airsBeforeSeason = item['AirsAfterSeasonNumber']
            # Kodi default number for afterseason ordering
            airsBeforeEpisode = 4096
        else:
            airsBeforeSeason = item.get('AirsBeforeSeasonNumber')
            airsBeforeEpisode = item.get('AirsBeforeEpisodeNumber')

        airsBeforeSeason = "-1"
        airsBeforeEpisode = "-1"
        # Append multi episodes to title
        # if item.get('IndexNumberEnd'):
        #     title = "| %02d | %s" % (item['IndexNumberEnd'], title)

        # Get season id
        show = plex_db.getItem_byId(seriesId)
        try:
            showid = show[0]
        except TypeError:
            log.error("Parent tvshow now found, skip item")
            return False
        seasonid = self.kodi_db.addSeason(showid, season)

        # GET THE FILE AND PATH #####
        doIndirect = not state.DIRECT_PATHS
        playurl = API.getFilePath(forceFirstMediaStream=True)
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            if playurl is None:
                # Something went wrong, trying to use non-direct paths
                doIndirect = True
            else:
                playurl = API.validatePlayurl(playurl, API.getType())
                if playurl is None:
                    return False
                if "\\" in playurl:
                    # Local path
                    filename = playurl.rsplit("\\", 1)[1]
                else:
                    # Network share
                    filename = playurl.rsplit("/", 1)[1]
                path = playurl.replace(filename, "")
                parentPathId = self.kodi_db.getParentPathId(path)
        if doIndirect:
            # Set plugin path and media flags using real filename
            if playurl is not None:
                if '\\' in playurl:
                    filename = playurl.rsplit('\\', 1)[1]
                else:
                    filename = playurl.rsplit('/', 1)[1]
            else:
                filename = 'file_not_found.mkv'
            path = "plugin://plugin.video.plexkodiconnect/tvshows/%s/" % seriesId
            params = {
                'filename': tryEncode(filename),
                'id': itemid,
                'dbid': episodeid,
                'mode': "play"
            }
            filename = "%s?%s" % (path, tryDecode(urlencode(params)))
            playurl = filename
            parentPathId = self.kodi_db.addPath(
                'plugin://plugin.video.plexkodiconnect/tvshows/')

        # episodes table:
        # c18 - playurl
        # c19 - pathid
        # This information is used later by file browser.

        # add/retrieve pathid and fileid
        # if the path or file already exists, the calls return current value
        pathid = self.kodi_db.addPath(path)
        fileid = self.kodi_db.addFile(filename, pathid)

        # UPDATE THE EPISODE #####
        if update_item:
            log.info("UPDATE episode itemid: %s" % (itemid))
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
                kodicursor.execute(query, (title, plot, rating, writer,
                    premieredate, runtime, director, season, episode, title,
                    airsBeforeSeason, airsBeforeEpisode, playurl, pathid,
                    fileid, seasonid, userdata['UserRating'], episodeid))
            elif v.KODIVERSION == 16:
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
                    airsBeforeSeason, airsBeforeEpisode, playurl, pathid,
                    fileid, seasonid, episodeid))
            else:
                query = '''
                    UPDATE episode
                    SET c00 = ?, c01 = ?, c03 = ?, c04 = ?, c05 = ?, c09 = ?,
                        c10 = ?, c12 = ?, c13 = ?, c14 = ?, c15 = ?, c16 = ?,
                        c18 = ?, c19 = ?, idFile = ?
                    WHERE idEpisode = ?
                '''
                kodicursor.execute(query, (title, plot, rating, writer,
                    premieredate, runtime, director, season, episode, title,
                    airsBeforeSeason, airsBeforeEpisode, playurl, pathid,
                    fileid, episodeid))
            # Update parentid reference
            plex_db.updateParentId(itemid, seasonid)

        # OR ADD THE EPISODE #####
        else:
            log.info("ADD episode itemid: %s - Title: %s" % (itemid, title))
            # Create the episode entry
            if v.KODIVERSION >= 17:
                # add new ratings Kodi 17
                rating_id = self.kodi_db.create_entry_rating()
                self.kodi_db.add_ratings(rating_id,
                                         episodeid,
                                         v.KODI_TYPE_EPISODE,
                                         "default",
                                         rating,
                                         votecount)
                # add new uniqueid Kodi 17
                self.kodi_db.add_uniqueid(self.kodi_db.create_entry_uniqueid(),
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
                    episode, title, showid, airsBeforeSeason,
                    airsBeforeEpisode, playurl, pathid, seasonid,
                    userdata['UserRating']))
            elif v.KODIVERSION == 16:
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
                    episode, title, showid, airsBeforeSeason,
                    airsBeforeEpisode, playurl, pathid, seasonid))
            else:
                query = (
                    '''
                    INSERT INTO episode(
                        idEpisode, idFile, c00, c01, c03, c04, c05, c09, c10, c12, c13, c14,
                        idShow, c15, c16, c18, c19)

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                )
                kodicursor.execute(query, (episodeid, fileid, title, plot, rating, writer,
                    premieredate, runtime, director, season, episode, title, showid,
                    airsBeforeSeason, airsBeforeEpisode, playurl, pathid))

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

        # Update the path
        query = ' '.join((

            "UPDATE path",
            "SET strPath = ?, strContent = ?, strScraper = ?, noUpdate = ?, ",
            "idParentPath = ?"
            "WHERE idPath = ?"
        ))
        kodicursor.execute(query, (path, None, None, 1, parentPathId, pathid))
        # Update the file
        query = ' '.join((

            "UPDATE files",
            "SET idPath = ?, strFilename = ?, dateAdded = ?",
            "WHERE idFile = ?"
        ))
        kodicursor.execute(query, (pathid, filename, dateadded, fileid))
        # Process cast
        people = API.getPeopleList()
        self.kodi_db.addPeople(episodeid, people, "episode")
        # Process artwork
        # Wide "screenshot" of particular episode
        poster = item.attrib.get('thumb')
        if poster:
            poster = API.addPlexCredentialsToUrl(
                "%s%s" % (self.server, poster))
            artwork.addOrUpdateArt(
                poster, episodeid, "episode", "thumb", kodicursor)
        # poster of TV show itself
        # poster = item.attrib.get('grandparentThumb')
        # if poster:
        #     poster = API.addPlexCredentialsToUrl(
        #         "%s%s" % (self.server, poster))
        #     artwork.addOrUpdateArt(
        #         poster, episodeid, "episode", "poster", kodicursor)

        # Process stream details
        streams = API.getMediaStreams()
        self.kodi_db.addStreams(fileid, streams, runtime)
        # Process playstates
        self.kodi_db.addPlaystate(fileid, resume, runtime, playcount, dateplayed)
        if not state.DIRECT_PATHS and resume:
            # Create additional entry for widgets. This is only required for plugin/episode.
            temppathid = self.kodi_db.getPath("plugin://plugin.video.plexkodiconnect/tvshows/")
            tempfileid = self.kodi_db.addFile(filename, temppathid)
            query = ' '.join((

                "UPDATE files",
                "SET idPath = ?, strFilename = ?, dateAdded = ?",
                "WHERE idFile = ?"
            ))
            kodicursor.execute(query,
                               (temppathid, filename, dateadded, tempfileid))
            self.kodi_db.addPlaystate(tempfileid,
                                      resume,
                                      runtime,
                                      playcount,
                                      dateplayed)

    def remove(self, itemid):
        # Remove showid, fileid, pathid, plex reference
        plex_db = self.plex_db
        kodicursor = self.kodicursor

        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            kodiid = plex_dbitem[0]
            fileid = plex_dbitem[1]
            parentid = plex_dbitem[3]
            mediatype = plex_dbitem[4]
            log.info("Removing %s kodiid: %s fileid: %s"
                     % (mediatype, kodiid, fileid))
        except TypeError:
            return

        ##### PROCESS ITEM #####

        # Remove the plex reference
        plex_db.removeItem(itemid)

        ##### IF EPISODE #####

        if mediatype == v.KODI_TYPE_EPISODE:
            # Delete kodi episode and file, verify season and tvshow
            self.removeEpisode(kodiid, fileid)

            # Season verification
            season = plex_db.getItem_byKodiId(parentid, v.KODI_TYPE_SEASON)
            try:
                showid = season[1]
            except TypeError:
                return
            season_episodes = plex_db.getItem_byParentId(parentid,
                                                         v.KODI_TYPE_EPISODE)
            if not season_episodes:
                self.removeSeason(parentid)
                plex_db.removeItem(season[0])

            # Show verification
            show = plex_db.getItem_byKodiId(showid, v.KODI_TYPE_SHOW)
            query = ' '.join((

                "SELECT totalCount",
                "FROM tvshowcounts",
                "WHERE idShow = ?"
            ))
            kodicursor.execute(query, (showid,))
            result = kodicursor.fetchone()
            if result and result[0] is None:
                # There's no episodes left, delete show and any possible remaining seasons
                seasons = plex_db.getItem_byParentId(showid,
                                                     v.KODI_TYPE_SEASON)
                for season in seasons:
                    self.removeSeason(season[1])
                # Delete plex season entries
                plex_db.removeItems_byParentId(showid,
                                               v.KODI_TYPE_SEASON)
                self.removeShow(showid)
                plex_db.removeItem(show[0])

        ##### IF TVSHOW #####

        elif mediatype == v.KODI_TYPE_SHOW:
            # Remove episodes, seasons, tvshow
            seasons = plex_db.getItem_byParentId(kodiid,
                                                 v.KODI_TYPE_SEASON)
            for season in seasons:
                seasonid = season[1]
                season_episodes = plex_db.getItem_byParentId(
                    seasonid, v.KODI_TYPE_EPISODE)
                for episode in season_episodes:
                    self.removeEpisode(episode[1], episode[2])
                # Remove plex episodes
                plex_db.removeItems_byParentId(seasonid,
                                               v.KODI_TYPE_EPISODE)
            # Remove plex seasons
            plex_db.removeItems_byParentId(kodiid,
                                           v.KODI_TYPE_SEASON)

            # Remove tvshow
            self.removeShow(kodiid)

        ##### IF SEASON #####

        elif mediatype == v.KODI_TYPE_SEASON:
            # Remove episodes, season, verify tvshow
            season_episodes = plex_db.getItem_byParentId(kodiid,
                                                         v.KODI_TYPE_EPISODE)
            for episode in season_episodes:
                self.removeEpisode(episode[1], episode[2])
            # Remove plex episodes
            plex_db.removeItems_byParentId(kodiid, v.KODI_TYPE_EPISODE)
            
            # Remove season
            self.removeSeason(kodiid)

            # Show verification
            seasons = plex_db.getItem_byParentId(parentid, v.KODI_TYPE_SEASON)
            if not seasons:
                # There's no seasons, delete the show
                self.removeShow(parentid)
                plex_db.removeItem_byKodiId(parentid, v.KODI_TYPE_SHOW)

        log.debug("Deleted %s: %s from kodi database" % (mediatype, itemid))

    def removeShow(self, kodi_id):
        kodicursor = self.kodicursor
        self.artwork.deleteArtwork(kodi_id, v.KODI_TYPE_SHOW, kodicursor)
        kodicursor.execute("DELETE FROM tvshow WHERE idShow = ?", (kodi_id,))
        if v.KODIVERSION >= 17:
            self.kodi_db.remove_uniqueid(kodi_id, v.KODI_TYPE_SHOW)
            self.kodi_db.remove_ratings(kodi_id, v.KODI_TYPE_SHOW)
        log.info("Removed tvshow: %s." % kodi_id)

    def removeSeason(self, kodi_id):
        kodicursor = self.kodicursor
        self.artwork.deleteArtwork(kodi_id, "season", kodicursor)
        kodicursor.execute("DELETE FROM seasons WHERE idSeason = ?",
                           (kodi_id,))
        log.info("Removed season: %s." % kodi_id)

    def removeEpisode(self, kodi_id, fileid):
        kodicursor = self.kodicursor
        self.artwork.deleteArtwork(kodi_id, "episode", kodicursor)
        kodicursor.execute("DELETE FROM episode WHERE idEpisode = ?",
                           (kodi_id,))
        kodicursor.execute("DELETE FROM files WHERE idFile = ?", (fileid,))
        if v.KODIVERSION >= 17:
            self.kodi_db.remove_uniqueid(kodi_id, v.KODI_TYPE_EPISODE)
            self.kodi_db.remove_ratings(kodi_id, v.KODI_TYPE_EPISODE)
        log.info("Removed episode: %s." % kodi_id)


class Music(Items):

    def __enter__(self):
        """
        OVERWRITE this method, because we need to open another DB.
        Open DB connections and cursors
        """
        self.plexconn = kodiSQL('plex')
        self.plexcursor = self.plexconn.cursor()
        # Here it is, not 'video' but 'music'
        self.kodiconn = kodiSQL('music')
        self.kodicursor = self.kodiconn.cursor()
        self.plex_db = plexdb.Plex_DB_Functions(self.plexcursor)
        self.kodi_db = kodidb.Kodidb_Functions(self.kodicursor)
        return self

    @CatchExceptions(warnuser=True)
    def add_updateArtist(self, item, viewtag=None, viewid=None,
                         artisttype="MusicArtist"):
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            artistid = plex_dbitem[0]
        except TypeError:
            update_item = False

        # The artist details #####
        lastScraped = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dateadded = API.getDateCreated()
        checksum = API.getChecksum()

        name, sortname = API.getTitle()
        # musicBrainzId = API.getProvider('MusicBrainzArtist')
        musicBrainzId = None
        genres = ' / '.join(API.getGenres())
        bio = API.getPlot()

        # Associate artwork
        artworks = API.getAllArtwork(parentInfo=True)
        thumb = artworks['Primary']
        backdrops = artworks['Backdrop']  # List

        if thumb:
            thumb = "<thumb>%s</thumb>" % thumb
        if backdrops:
            fanart = "<fanart>%s</fanart>" % backdrops[0]
        else:
            fanart = ""

        # UPDATE THE ARTIST #####
        if update_item:
            log.info("UPDATE artist itemid: %s - Name: %s" % (itemid, name))
            # Update the checksum in plex table
            plex_db.updateReference(itemid, checksum)

        # OR ADD THE ARTIST #####
        else:
            log.info("ADD artist itemid: %s - Name: %s" % (itemid, name))
            # safety checks: It looks like plex supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            artistid = self.kodi_db.addArtist(name, musicBrainzId)
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
        artwork.addArtwork(artworks, artistid, v.KODI_TYPE_ARTIST, kodicursor)

    @CatchExceptions(warnuser=True)
    def add_updateAlbum(self, item, viewtag=None, viewid=None, children=None):
        """
        children: list of child xml's, so in this case songs
        """
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()
        if not itemid:
            log.error('Error processing Album, skipping')
            return
        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            albumid = plex_dbitem[0]
        except TypeError:
            # Albumid not found
            update_item = False

        # The album details #####
        lastScraped = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dateadded = API.getDateCreated()
        userdata = API.getUserData()
        checksum = API.getChecksum()

        name, sorttitle = API.getTitle()
        # musicBrainzId = API.getProvider('MusicBrainzAlbum')
        musicBrainzId = None
        year = API.getYear()
        self.genres = API.getGenres()
        self.genre = ' / '.join(self.genres)
        bio = API.getPlot()
        rating = userdata['UserRating']
        studio = API.getMusicStudio()
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
        artworks = API.getAllArtwork(parentInfo=True)
        thumb = artworks['Primary']
        if thumb:
            thumb = "<thumb>%s</thumb>" % thumb

        # UPDATE THE ALBUM #####
        if update_item:
            log.info("UPDATE album itemid: %s - Name: %s" % (itemid, name))
            # Update the checksum in plex table
            plex_db.updateReference(itemid, checksum)

        # OR ADD THE ALBUM #####
        else:
            log.info("ADD album itemid: %s - Name: %s" % (itemid, name))
            # safety checks: It looks like plex supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            albumid = self.kodi_db.addAlbum(name, musicBrainzId)
            # Create the reference in plex table
            plex_db.addReference(itemid,
                                 v.PLEX_TYPE_ALBUM,
                                 albumid,
                                 v.KODI_TYPE_ALBUM,
                                 view_id=viewid,
                                 checksum=checksum)

        # Process the album info
        if v.KODIVERSION >= 17:
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
                                       self.compilation, albumid))
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
                                       self.compilation, albumid))
        elif v.KODIVERSION == 15:
            # Kodi Isengard
            query = '''
                UPDATE album
                SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?,
                    strImage = ?, iRating = ?, lastScraped = ?, dateAdded = ?,
                    strReleaseType = ?, strLabel = ?
                WHERE idAlbum = ?
            '''
            kodicursor.execute(query, (artistname, year, self.genre, bio,
                                       thumb, rating, lastScraped, dateadded,
                                       v.KODI_TYPE_ALBUM, studio, albumid))
        else:
            # Kodi Helix
            query = '''
                UPDATE album
                SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?,
                    strImage = ?, iRating = ?, lastScraped = ?, dateAdded = ?,
                    strLabel = ?
                WHERE idAlbum = ?
            '''
            kodicursor.execute(query, (artistname, year, self.genre, bio,
                                       thumb, rating, lastScraped, dateadded,
                                       studio, albumid))

        # Associate the parentid for plex reference
        parentId = item.attrib.get('parentRatingKey')
        if parentId is not None:
            plex_dbartist = plex_db.getItem_byId(parentId)
            try:
                artistid = plex_dbartist[0]
            except TypeError:
                log.info('Artist %s does not exist in plex database'
                         % parentId)
                artist = GetPlexMetadata(parentId)
                # Item may not be an artist, verification necessary.
                if artist is not None and artist != 401:
                    if artist[0].attrib.get('type') == v.PLEX_TYPE_ARTIST:
                        # Update with the parentId, for remove reference
                        plex_db.addReference(parentId,
                                             v.PLEX_TYPE_ARTIST,
                                             parentId,
                                             v.KODI_TYPE_ARTIST,
                                             view_id=viewid)
                        plex_db.updateParentId(itemid, parentId)
            else:
                # Update plex reference with the artistid
                plex_db.updateParentId(itemid, artistid)

        # Assign main artists to album
        # Plex unfortunately only supports 1 artist :-(
        artistId = parentId
        plex_dbartist = plex_db.getItem_byId(artistId)
        try:
            artistid = plex_dbartist[0]
        except TypeError:
            # Artist does not exist in plex database, create the reference
            log.info('Artist %s does not exist in Plex database' % artistId)
            artist = GetPlexMetadata(artistId)
            if artist is not None and artist != 401:
                self.add_updateArtist(artist[0], artisttype="AlbumArtist")
                plex_dbartist = plex_db.getItem_byId(artistId)
                artistid = plex_dbartist[0]
        else:
            # Best take this name over anything else.
            query = "UPDATE artist SET strArtist = ? WHERE idArtist = ?"
            kodicursor.execute(query, (artistname, artistid,))
            log.info("UPDATE artist: strArtist: %s, idArtist: %s"
                     % (artistname, artistid))

        # Add artist to album
        query = '''
            INSERT OR REPLACE INTO album_artist(idArtist, idAlbum, strArtist)
            VALUES (?, ?, ?)
        '''
        kodicursor.execute(query, (artistid, albumid, artistname))
        # Update discography
        query = '''
            INSERT OR REPLACE INTO discography(idArtist, strAlbum, strYear)
            VALUES (?, ?, ?)
        '''
        kodicursor.execute(query, (artistid, name, year))
        # Update plex reference with parentid
        plex_db.updateParentId(artistId, albumid)
        # Add genres
        self.kodi_db.addMusicGenres(albumid, self.genres, v.KODI_TYPE_ALBUM)
        # Update artwork
        artwork.addArtwork(artworks, albumid, v.KODI_TYPE_ALBUM, kodicursor)
        # Add all children - all tracks
        for child in children:
            self.add_updateSong(child, viewtag, viewid)

    @CatchExceptions(warnuser=True)
    def add_updateSong(self, item, viewtag=None, viewid=None):
        # Process single song
        kodicursor = self.kodicursor
        plex_db = self.plex_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()
        if not itemid:
            log.error('Error processing Song; skipping')
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
        checksum = API.getChecksum()
        dateadded = API.getDateCreated()
        userdata = API.getUserData()
        playcount = userdata['PlayCount']
        if playcount is None:
            # This is different to Video DB!
            playcount = 0
        dateplayed = userdata['LastPlayedDate']

        # item details
        title, sorttitle = API.getTitle()
        # musicBrainzId = API.getProvider('MusicBrainzTrackId')
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
                artists = item.attrib.get('grandparentTitle')
            else:
                artists = item.attrib.get('originalTitle')
        except AttributeError:
            # compilation not set
            artists = item.attrib.get('originalTitle',
                                      item.attrib.get('grandparentTitle'))
        tracknumber = int(item.attrib.get('index', 0))
        disc = int(item.attrib.get('parentIndex', 1))
        if disc == 1:
            track = tracknumber
        else:
            track = disc*2**16 + tracknumber
        year = API.getYear()
        resume, duration = API.getRuntime()
        rating = userdata['UserRating']
        comment = None
        # Moods
        moods = []
        for entry in item:
            if entry.tag == 'Mood':
                moods.append(entry.attrib['tag'])
        mood = ' / '.join(moods)

        # GET THE FILE AND PATH #####
        doIndirect = not state.DIRECT_PATHS
        if state.DIRECT_PATHS:
            # Direct paths is set the Kodi way
            playurl = API.getFilePath(forceFirstMediaStream=True)
            if playurl is None:
                # Something went wrong, trying to use non-direct paths
                doIndirect = True
            else:
                playurl = API.validatePlayurl(playurl, API.getType())
                if playurl is None:
                    return False
                if "\\" in playurl:
                    # Local path
                    filename = playurl.rsplit("\\", 1)[1]
                else:
                    # Network share
                    filename = playurl.rsplit("/", 1)[1]
                path = playurl.replace(filename, "")
        if doIndirect:
            # Plex works a bit differently
            path = "%s%s" % (self.server, item[0][0].attrib.get('key'))
            path = API.addPlexCredentialsToUrl(path)
            filename = path.rsplit('/', 1)[1]
            path = path.replace(filename, '')

        # UPDATE THE SONG #####
        if update_item:
            log.info("UPDATE song itemid: %s - Title: %s with path: %s"
                     % (itemid, title, path))
            # Update path
            # Use dummy strHash '123' for Kodi
            query = "UPDATE path SET strPath = ?, strHash = ? WHERE idPath = ?"
            kodicursor.execute(query, (path, '123', pathid))

            # Update the song entry
            query = '''
                UPDATE song
                SET idAlbum = ?, strArtists = ?, strGenres = ?, strTitle = ?,
                    iTrack = ?, iDuration = ?, iYear = ?, strFilename = ?,
                    iTimesPlayed = ?, lastplayed = ?, rating = ?, comment = ?,
                    mood = ?
                WHERE idSong = ?
            '''
            kodicursor.execute(query, (albumid, artists, genre, title, track,
                                       duration, year, filename, playcount,
                                       dateplayed, rating, comment, mood,
                                       songid))

            # Update the checksum in plex table
            plex_db.updateReference(itemid, checksum)

        # OR ADD THE SONG #####
        else:
            log.info("ADD song itemid: %s - Title: %s" % (itemid, title))

            # Add path
            pathid = self.kodi_db.addPath(path, strHash="123")

            try:
                # Get the album
                plex_dbalbum = plex_db.getItem_byId(
                    item.attrib.get('parentRatingKey'))
                albumid = plex_dbalbum[0]
            except KeyError:
                # Verify if there's an album associated.
                album_name = item.get('parentTitle')
                if album_name:
                    log.info("Creating virtual music album for song: %s."
                             % itemid)
                    albumid = self.kodi_db.addAlbum(
                        album_name,
                        API.getProvider('MusicBrainzAlbum'))
                    plex_db.addReference("%salbum%s" % (itemid, albumid),
                                         v.PLEX_TYPE_ALBUM,
                                         albumid,
                                         v.KODI_TYPE_ALBUM,
                                         view_id=viewid)
                else:
                    # No album Id associated to the song.
                    log.error("Song itemid: %s has no albumId associated."
                              % itemid)
                    return False

            except TypeError:
                # No album found. Let's create it
                log.info("Album database entry missing.")
                plex_albumId = item.attrib.get('parentRatingKey')
                album = GetPlexMetadata(plex_albumId)
                if album is None or album == 401:
                    log.error('Could not download album, abort')
                    return
                self.add_updateAlbum(album[0], children=[item])
                plex_dbalbum = plex_db.getItem_byId(plex_albumId)
                try:
                    albumid = plex_dbalbum[0]
                    log.debug("Found albumid: %s" % albumid)
                except TypeError:
                    # No album found, create a single's album
                    log.info("Failed to add album. Creating singles.")
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
            query = '''
                INSERT INTO song(
                    idSong, idAlbum, idPath, strArtists, strGenres, strTitle,
                    iTrack, iDuration, iYear, strFileName,
                    strMusicBrainzTrackID, iTimesPlayed, lastplayed,
                    rating, iStartOffset, iEndOffset, mood)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
            kodicursor.execute(
                query, (songid, albumid, pathid, artists, genre, title, track,
                        duration, year, filename, musicBrainzId, playcount,
                        dateplayed, rating, 0, 0, mood))

            # Create the reference in plex table
            plex_db.addReference(itemid,
                                 v.PLEX_TYPE_SONG,
                                 songid,
                                 v.KODI_TYPE_SONG,
                                 kodi_pathid=pathid,
                                 parent_id=albumid,
                                 checksum=checksum,
                                 view_id=viewid)

        # Link song to album
        query = '''
            INSERT OR REPLACE INTO albuminfosong(
                idAlbumInfoSong, idAlbumInfo, iTrack, strTitle, iDuration)
            VALUES (?, ?, ?, ?, ?)
        '''
        kodicursor.execute(query, (songid, albumid, track, title, duration))

        # Link song to artists
        artistLoop = [{
            'Name': item.attrib.get('grandparentTitle'),
            'Id': item.attrib.get('grandparentRatingKey')
        }]
        # for index, artist in enumerate(item['ArtistItems']):
        for index, artist in enumerate(artistLoop):

            artist_name = artist['Name']
            artist_eid = artist['Id']
            artist_edb = plex_db.getItem_byId(artist_eid)
            try:
                artistid = artist_edb[0]
            except TypeError:
                # Artist is missing from plex database, add it.
                artistXml = GetPlexMetadata(artist_eid)
                if artistXml is None or artistXml == 401:
                    log.error('Error getting artist, abort')
                    return
                self.add_updateArtist(artistXml[0])
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

        # Verify if album artist exists
        album_artists = []
        # for artist in item['AlbumArtists']:
        if False:
            artist_name = artist['Name']
            album_artists.append(artist_name)
            artist_eid = artist['Id']
            artist_edb = plex_db.getItem_byId(artist_eid)
            try:
                artistid = artist_edb[0]
            except TypeError:
                # Artist is missing from plex database, add it.
                artistXml = GetPlexMetadata(artist_eid)
                if artistXml is None or artistXml == 401:
                    log.error('Error getting artist, abort')
                    return
                self.add_updateArtist(artistXml)
                artist_edb = plex_db.getItem_byId(artist_eid)
                artistid = artist_edb[0]
            finally:
                query = '''
                    INSERT OR REPLACE INTO album_artist(
                        idArtist, idAlbum, strArtist)
                    VALUES (?, ?, ?)
                '''
                kodicursor.execute(query, (artistid, albumid, artist_name))
                # Update discography
                if item.get('Album'):
                    query = '''
                        INSERT OR REPLACE INTO discography(
                            idArtist, strAlbum, strYear)
                        VALUES (?, ?, ?)
                    '''
                    kodicursor.execute(query, (artistid, item['Album'], 0))
        # else:
        if False:
            album_artists = " / ".join(album_artists)
            query = '''
                SELECT strArtists
                FROM album
                WHERE idAlbum = ?
            '''
            kodicursor.execute(query, (albumid,))
            result = kodicursor.fetchone()
            if result and result[0] != album_artists:
                # Field is empty
                if v.KODIVERSION >= 16:
                    # Kodi Jarvis, Krypton
                    query = "UPDATE album SET strArtists = ? WHERE idAlbum = ?"
                    kodicursor.execute(query, (album_artists, albumid))
                elif v.KODIVERSION == 15:
                    # Kodi Isengard
                    query = "UPDATE album SET strArtists = ? WHERE idAlbum = ?"
                    kodicursor.execute(query, (album_artists, albumid))
                else:
                    # Kodi Helix
                    query = "UPDATE album SET strArtists = ? WHERE idAlbum = ?"
                    kodicursor.execute(query, (album_artists, albumid))

        # Add genres
        if genres:
            self.kodi_db.addMusicGenres(songid, genres, v.KODI_TYPE_SONG)

        # Update artwork
        allart = API.getAllArtwork(parentInfo=True)
        artwork.addArtwork(allart, songid, v.KODI_TYPE_SONG, kodicursor)

        if item.get('parentKey') is None:
            # Update album artwork
            artwork.addArtwork(allart, albumid, v.KODI_TYPE_ALBUM, kodicursor)

    def remove(self, itemid):
        # Remove kodiid, fileid, pathid, plex reference
        plex_db = self.plex_db

        plex_dbitem = plex_db.getItem_byId(itemid)
        try:
            kodiid = plex_dbitem[0]
            mediatype = plex_dbitem[4]
            log.info("Removing %s kodiid: %s" % (mediatype, kodiid))
        except TypeError:
            return

        ##### PROCESS ITEM #####

        # Remove the plex reference
        plex_db.removeItem(itemid)

        ##### IF SONG #####

        if mediatype == v.KODI_TYPE_SONG:
            # Delete song
            self.removeSong(kodiid)
            # This should only address single song scenario, where server doesn't actually
            # create an album for the song. 
            plex_db.removeWildItem(itemid)

            for item in plex_db.getItem_byWildId(itemid):

                item_kid = item[0]
                item_mediatype = item[1]

                if item_mediatype == v.KODI_TYPE_ALBUM:
                    childs = plex_db.getItem_byParentId(item_kid,
                                                        v.KODI_TYPE_SONG)
                    if not childs:
                        # Delete album
                        self.removeAlbum(item_kid)

        ##### IF ALBUM #####

        elif mediatype == v.KODI_TYPE_ALBUM:
            # Delete songs, album
            album_songs = plex_db.getItem_byParentId(kodiid,
                                                     v.KODI_TYPE_SONG)
            for song in album_songs:
                self.removeSong(song[1])
            else:
                # Remove plex songs
                plex_db.removeItems_byParentId(kodiid,
                                               v.KODI_TYPE_SONG)

            # Remove the album
            self.removeAlbum(kodiid)

        ##### IF ARTIST #####

        elif mediatype == v.KODI_TYPE_ARTIST:
            # Delete songs, album, artist
            albums = plex_db.getItem_byParentId(kodiid,
                                                v.KODI_TYPE_ALBUM)
            for album in albums:
                albumid = album[1]
                album_songs = plex_db.getItem_byParentId(albumid,
                                                         v.KODI_TYPE_SONG)
                for song in album_songs:
                    self.removeSong(song[1])
                else:
                    # Remove plex song
                    plex_db.removeItems_byParentId(albumid,
                                                   v.KODI_TYPE_SONG)
                    # Remove plex artist
                    plex_db.removeItems_byParentId(albumid,
                                                   v.KODI_TYPE_ARTIST)
                    # Remove kodi album
                    self.removeAlbum(albumid)
            else:
                # Remove plex albums
                plex_db.removeItems_byParentId(kodiid,
                                               v.KODI_TYPE_ALBUM)

            # Remove artist
            self.removeArtist(kodiid)

        log.info("Deleted %s: %s from kodi database" % (mediatype, itemid))

    def removeSong(self, kodiid):
        self.artwork.deleteArtwork(kodiid, v.KODI_TYPE_SONG, self.kodicursor)
        self.kodicursor.execute("DELETE FROM song WHERE idSong = ?",
                                (kodiid,))

    def removeAlbum(self, kodiid):
        self.artwork.deleteArtwork(kodiid, v.KODI_TYPE_ALBUM, self.kodicursor)
        self.kodicursor.execute("DELETE FROM album WHERE idAlbum = ?",
                                (kodiid,))

    def removeArtist(self, kodiid):
        self.artwork.deleteArtwork(kodiid,
                                   v.KODI_TYPE_ARTIST,
                                   self.kodicursor)
        self.kodicursor.execute("DELETE FROM artist WHERE idArtist = ?",
                                (kodiid,))
