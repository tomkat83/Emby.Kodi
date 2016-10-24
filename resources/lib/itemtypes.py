# -*- coding: utf-8 -*-

###############################################################################

import logging
from urllib import urlencode
from ntpath import dirname
from datetime import datetime

import xbmc
import xbmcgui

import artwork
from utils import tryEncode, tryDecode, settings, window, kodiSQL, \
    CatchExceptions
import embydb_functions as embydb
import kodidb_functions as kodidb

import PlexAPI
from PlexFunctions import GetPlexMetadata

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


class Items(object):
    """
    Items to be called with "with Items() as xxx:" to ensure that __enter__
    method is called (opens db connections)

    Input:
        kodiType:       optional argument; e.g. 'video' or 'music'
    """

    def __init__(self):
        self.kodiversion = int(xbmc.getInfoLabel("System.BuildVersion")[:2])
        self.directpath = window('useDirectPaths') == 'true'

        self.artwork = artwork.Artwork()
        self.userid = window('currUserId')
        self.server = window('pms_server')

    def __enter__(self):
        """
        Open DB connections and cursors
        """
        self.embyconn = kodiSQL('emby')
        self.embycursor = self.embyconn.cursor()
        self.kodiconn = kodiSQL('video')
        self.kodicursor = self.kodiconn.cursor()
        self.emby_db = embydb.Embydb_Functions(self.embycursor)
        self.kodi_db = kodidb.Kodidb_Functions(self.kodicursor)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Make sure DB changes are committed and connection to DB is closed.
        """
        self.embyconn.commit()
        self.kodiconn.commit()
        self.embyconn.close()
        self.kodiconn.close()
        return self

    @CatchExceptions(warnuser=True)
    def getfanart(self, item, kodiId, mediaType, allartworks=None):
        """
        """
        API = PlexAPI.API(item)
        if allartworks is None:
            allartworks = API.getAllArtwork()
        self.artwork.addArtwork(API.getFanartArtwork(allartworks),
                                kodiId,
                                mediaType,
                                self.kodicursor)
        # Also get artwork for collections/movie sets
        if mediaType == 'movie':
            for setname in API.getCollections():
                log.debug('Getting artwork for movie set %s' % setname)
                setid = self.kodi_db.createBoxset(setname)
                self.artwork.addArtwork(API.getSetArtwork(),
                                        setid,
                                        "set",
                                        self.kodicursor)
                self.kodi_db.assignBoxset(setid, kodiId)

    def itemsbyId(self, items, process, pdialog=None):
        # Process items by itemid. Process can be added, update, userdata, remove
        embycursor = self.embycursor
        kodicursor = self.kodicursor
        music_enabled = self.music_enabled
        
        itemtypes = {

            'Movie': Movies,
            'BoxSet': Movies,
            'Series': TVShows,
            'Season': TVShows,
            'Episode': TVShows,
            'MusicAlbum': Music,
            'MusicArtist': Music,
            'AlbumArtist': Music,
            'Audio': Music
        }

        update_videolibrary = False
        total = 0
        for item in items:
            total += len(items[item])

        if total == 0:
            return False

        log.info("Processing %s: %s" % (process, items))
        if pdialog:
            pdialog.update(heading="Processing %s: %s items" % (process, total))

        count = 0
        for itemtype in items:

            # Safety check
            if not itemtypes.get(itemtype):
                # We don't process this type of item
                continue

            itemlist = items[itemtype]
            if not itemlist:
                # The list to process is empty
                continue

            musicconn = None

            if itemtype in ('MusicAlbum', 'MusicArtist', 'AlbumArtist', 'Audio'):
                if music_enabled:
                    musicconn = kodiSQL('music')
                    musiccursor = musicconn.cursor()
                    items_process = itemtypes[itemtype](embycursor, musiccursor)
                else:
                    # Music is not enabled, do not proceed with itemtype
                    continue
            else:
                update_videolibrary = True
                items_process = itemtypes[itemtype](embycursor, kodicursor)

            if itemtype == "Movie":
                actions = {
                    'added': items_process.added,
                    'update': items_process.add_update,
                    'userdata': items_process.updateUserdata,
                    'remove': items_process.remove
                }
            elif itemtype == "BoxSet":
                actions = {
                    'added': items_process.added_boxset,
                    'update': items_process.add_updateBoxset,
                    'remove': items_process.remove
                }
            elif itemtype == "MusicVideo":
                actions = {
                    'added': items_process.added,
                    'update': items_process.add_update,
                    'userdata': items_process.updateUserdata,
                    'remove': items_process.remove
                }
            elif itemtype == "Series":
                actions = {
                    'added': items_process.added,
                    'update': items_process.add_update,
                    'userdata': items_process.updateUserdata,
                    'remove': items_process.remove
                }
            elif itemtype == "Season":
                actions = {
                    'added': items_process.added_season,
                    'update': items_process.add_updateSeason,
                    'remove': items_process.remove
                }
            elif itemtype == "Episode":
                actions = {
                    'added': items_process.added_episode,
                    'update': items_process.add_updateEpisode,
                    'userdata': items_process.updateUserdata,
                    'remove': items_process.remove
                }
            elif itemtype == "MusicAlbum":
                actions = {
                    'added': items_process.added_album,
                    'update': items_process.add_updateAlbum,
                    'userdata': items_process.updateUserdata,
                    'remove': items_process.remove
                }
            elif itemtype in ("MusicArtist", "AlbumArtist"):
                actions = {
                    'added': items_process.added,
                    'update': items_process.add_updateArtist,
                    'remove': items_process.remove
                }
            elif itemtype == "Audio":
                actions = {
                    'added': items_process.added_song,
                    'update': items_process.add_updateSong,
                    'userdata': items_process.updateUserdata,
                    'remove': items_process.remove
                }
            else:
                log.info("Unsupported itemtype: %s." % itemtype)
                actions = {}

            if actions.get(process):

                if process == "remove":
                    for item in itemlist:
                        actions[process](item)

                elif process == "added":
                    actions[process](itemlist, pdialog)
            
                else:
                    processItems = emby.getFullItems(itemlist)
                    for item in processItems:

                        title = item['Name']

                        if itemtype == "Episode":
                            title = "%s - %s" % (item['SeriesName'], title)

                        if pdialog:
                            percentage = int((float(count) / float(total))*100)
                            pdialog.update(percentage, message=title)
                            count += 1

                        actions[process](item)


            if musicconn is not None:
                # close connection for special types
                log.info("Updating music database.")
                musicconn.commit()
                musiccursor.close()

        return (True, update_videolibrary)

    def contentPop(self, name, time=5000):
        xbmcgui.Dialog().notification(
                heading="Emby for Kodi",
                message="Added: %s" % name,
                icon="special://home/addons/plugin.video.plexkodiconnect/icon.png",
                time=time,
                sound=False)

    def updateUserdata(self, xml, viewtag=None, viewid=None):
        """
        Updates the Kodi watched state of the item from PMS. Also retrieves
        Plex resume points for movies in progress.

        viewtag and viewid only serve as dummies
        """
        for mediaitem in xml:
            API = PlexAPI.API(mediaitem)
            # Get key and db entry on the Kodi db side
            try:
                fileid = self.emby_db.getItem_byId(API.getRatingKey())[1]
            except:
                continue
            # Grab the user's viewcount, resume points etc. from PMS' answer
            userdata = API.getUserData()
            # Write to Kodi DB
            self.kodi_db.addPlaystate(fileid,
                                      userdata['Resume'],
                                      userdata['Runtime'],
                                      userdata['PlayCount'],
                                      userdata['LastPlayedDate'])

    def updatePlaystate(self, item):
        """
        Use with websockets, not xml
        """
        # If the playback was stopped, check whether we need to increment the
        # playcount. PMS won't tell us the playcount via websockets
        if item['state'] in ('stopped', 'ended'):
            markPlayed = 0.90
            complete = float(item['viewOffset']) / float(item['duration'])
            log.info('Item %s stopped with completion rate %s percent.'
                     'Mark item played at %s percent.'
                     % (item['ratingKey'], str(complete), markPlayed), 1)
            if complete >= markPlayed:
                log.info('Marking as completely watched in Kodi', 1)
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
        emby_db = self.emby_db
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
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            movieid = emby_dbitem[0]
            fileid = emby_dbitem[1]
            pathid = emby_dbitem[2]

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
            if extra['extraType'] == '1':
                trailer = ("plugin://plugin.video.plexkodiconnect/trailer/?"
                           "id=%s&mode=play") % extra['key']
                break

        # GET THE FILE AND PATH #####
        doIndirect = not self.directpath
        if self.directpath:
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
            path = "plugin://plugin.video.plexkodiconnect.movies/"
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
            if self.kodiversion > 16:
                query = ' '.join((
                    "UPDATE movie",
                    "SET c00 = ?, c01 = ?, c02 = ?, c03 = ?, c04 = ?, c05 = ?,"
                    "c06 = ?, c07 = ?, c09 = ?, c10 = ?, c11 = ?, c12 = ?,"
                    "c14 = ?, c15 = ?, c16 = ?, c18 = ?, c19 = ?, c21 = ?,"
                    "c22 = ?, c23 = ?, idFile=?, premiered = ?",
                    "WHERE idMovie = ?"
                ))
                kodicursor.execute(query, (title, plot, shortplot, tagline,
                    votecount, rating, writer, year, imdb, sorttitle, runtime,
                    mpaa, genre, director, title, studio, trailer, country,
                    playurl, pathid, fileid, year, movieid))
            else:
                query = ' '.join((
                    "UPDATE movie",
                    "SET c00 = ?, c01 = ?, c02 = ?, c03 = ?, c04 = ?, c05 = ?,"
                    "c06 = ?, c07 = ?, c09 = ?, c10 = ?, c11 = ?, c12 = ?,"
                    "c14 = ?, c15 = ?, c16 = ?, c18 = ?, c19 = ?, c21 = ?,"
                    "c22 = ?, c23 = ?, idFile=?",
                    "WHERE idMovie = ?"
                ))
                kodicursor.execute(query, (title, plot, shortplot, tagline,
                    votecount, rating, writer, year, imdb, sorttitle, runtime,
                    mpaa, genre, director, title, studio, trailer, country,
                    playurl, pathid, fileid, movieid))

            # Update the checksum in emby table
            # emby_db.updateReference(itemid, checksum)
            # Add reference is idempotent; the call here updates also fileid and pathid when item
            # is moved or renamed
            emby_db.addReference(itemid, movieid, "Movie", "movie", fileid, pathid, None, checksum, viewid)

        ##### OR ADD THE MOVIE #####
        else:
            log.info("ADD movie itemid: %s - Title: %s" % (itemid, title))

            # Create the movie entry
            query = (
                '''
                INSERT INTO movie(
                    idMovie, idFile, c00, c01, c02, c03, c04, c05, c06, c07, 
                    c09, c10, c11, c12, c14, c15, c16, c18, c19, c21, c22, c23)

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
            )
            kodicursor.execute(query, (movieid, fileid, title, plot, shortplot, tagline, votecount,
                rating, writer, year, imdb, sorttitle, runtime, mpaa, genre, director, title,
                studio, trailer, country, playurl, pathid))

            # Create the reference in emby table
            emby_db.addReference(itemid, movieid, "Movie", "movie", fileid, pathid, None, checksum, viewid)

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
        # Remove movieid, fileid, emby reference
        emby_db = self.emby_db
        kodicursor = self.kodicursor
        artwork = self.artwork

        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            kodiid = emby_dbitem[0]
            fileid = emby_dbitem[1]
            mediatype = emby_dbitem[4]
            log.info("Removing %sid: %s fileid: %s"
                     % (mediatype, kodiid, fileid))
        except TypeError:
            return

        # Remove the emby reference
        emby_db.removeItem(itemid)
        # Remove artwork
        artwork.deleteArtwork(kodiid, mediatype, kodicursor)

        if mediatype == "movie":
            # Delete kodi movie and file
            kodicursor.execute("DELETE FROM movie WHERE idMovie = ?", (kodiid,))
            kodicursor.execute("DELETE FROM files WHERE idFile = ?", (fileid,))

        elif mediatype == "set":
            # Delete kodi boxset
            boxset_movies = emby_db.getItem_byParentId(kodiid, "movie")
            for movie in boxset_movies:
                plexid = movie[0]
                movieid = movie[1]
                self.kodi_db.removefromBoxset(movieid)
                # Update emby reference
                emby_db.updateParentId(plexid, None)

            kodicursor.execute("DELETE FROM sets WHERE idSet = ?", (kodiid,))

        log.info("Deleted %s %s from kodi database"
                 % (mediatype, itemid))


class TVShows(Items):

    @CatchExceptions(warnuser=True)
    def add_update(self, item, viewtag=None, viewid=None):
        # Process single tvshow
        kodicursor = self.kodicursor
        emby_db = self.emby_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()

        if not itemid:
            log.error("Cannot parse XML data for TV show")
            return
        # If the item already exist in the local Kodi DB we'll perform a full item update
        # If the item doesn't exist, we'll add it to the database
        update_item = True
        force_episodes = False
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            showid = emby_dbitem[0]
            pathid = emby_dbitem[2]
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

        if viewtag is None or viewid is None:
            # Get view tag from emby
            viewtag, viewid, mediatype = embyserver.getView_plexid(itemid)
            log.debug("View tag found: %s" % viewtag)

        # fileId information
        checksum = API.getChecksum()

        # item details
        genres = API.getGenres()
        title, sorttitle = API.getTitle()
        plot = API.getPlot()
        rating = API.getAudienceRating()
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
        doIndirect = not self.directpath
        if self.directpath:
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
            toplevelpath = "plugin://plugin.video.plexkodiconnect.tvshows/"
            path = "%s%s/" % (toplevelpath, itemid)

        # Add top path
        toppathid = self.kodi_db.addPath(toplevelpath)
        # UPDATE THE TVSHOW #####
        if update_item:
            log.info("UPDATE tvshow itemid: %s - Title: %s"
                     % (itemid, title))

            # Update the tvshow entry
            query = ' '.join((
                
                "UPDATE tvshow",
                "SET c00 = ?, c01 = ?, c04 = ?, c05 = ?, c08 = ?, c09 = ?,",
                    "c12 = ?, c13 = ?, c14 = ?, c15 = ?",
                "WHERE idShow = ?"
            ))
            kodicursor.execute(query, (title, plot, rating, premieredate, genre, title,
                tvdb, mpaa, studio, sorttitle, showid))

            # Update the checksum in emby table
            emby_db.updateReference(itemid, checksum)
        
        ##### OR ADD THE TVSHOW #####
        else:
            log.info("ADD tvshow itemid: %s - Title: %s" % (itemid, title))
            
            query = ' '.join((

                "UPDATE path",
                "SET strPath = ?, strContent = ?, strScraper = ?, noUpdate = ?",
                "WHERE idPath = ?"
            ))
            kodicursor.execute(query, (toplevelpath, "tvshows", "metadata.local", 1, toppathid))
            
            # Add path
            pathid = self.kodi_db.addPath(path)
            
            # Create the tvshow entry
            query = (
                '''
                INSERT INTO tvshow(
                    idShow, c00, c01, c04, c05, c08, c09, c12, c13, c14, c15) 

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
            )
            kodicursor.execute(query, (showid, title, plot, rating, premieredate, genre,
                title, tvdb, mpaa, studio, sorttitle))

            # Link the path
            query = "INSERT INTO tvshowlinkpath(idShow, idPath) values(?, ?)"
            kodicursor.execute(query, (showid, pathid))

            # Create the reference in emby table
            emby_db.addReference(itemid, showid, "Series", "tvshow", pathid=pathid,
                                checksum=checksum, mediafolderid=viewid)
        # Update the path
        query = ' '.join((

            "UPDATE path",
            "SET strPath = ?, strContent = ?, strScraper = ?, noUpdate = ?, ",
            "idParentPath = ?"
            "WHERE idPath = ?"
        ))
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

        if force_episodes:
            # We needed to recreate the show entry. Re-add episodes now.
            log.info("Repairing episodes for showid: %s %s" % (showid, title))
            all_episodes = embyserver.getEpisodesbyShow(itemid)
            self.added_episode(all_episodes['Items'], None)

    @CatchExceptions(warnuser=True)
    def add_updateSeason(self, item, viewtag=None, viewid=None):
        API = PlexAPI.API(item)
        itemid = API.getRatingKey()
        if not itemid:
            log.error('Error getting itemid for season, skipping')
            return
        kodicursor = self.kodicursor
        emby_db = self.emby_db
        artwork = self.artwork
        seasonnum = API.getIndex()
        # Get parent tv show Plex id
        plexshowid = item.attrib.get('parentRatingKey')
        # Get Kodi showid
        emby_dbitem = emby_db.getItem_byId(plexshowid)
        try:
            showid = emby_dbitem[0]
        except:
            log.error('Could not find parent tv show for season %s. '
                      'Skipping season for now.' % (itemid))
            return

        seasonid = self.kodi_db.addSeason(showid, seasonnum)
        checksum = API.getChecksum()
        # Check whether Season already exists
        update_item = True
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            embyDbItemId = emby_dbitem[0]
        except TypeError:
            update_item = False

        # Process artwork
        allartworks = API.getAllArtwork()
        artwork.addArtwork(allartworks, seasonid, "season", kodicursor)

        if update_item:
            # Update a reference: checksum in emby table
            emby_db.updateReference(itemid, checksum)
        else:
            # Create the reference in emby table
            emby_db.addReference(itemid,
                                 seasonid,
                                 "Season",
                                 "season",
                                 parentid=viewid,
                                 checksum=checksum)

    @CatchExceptions(warnuser=True)
    def add_updateEpisode(self, item, viewtag=None, viewid=None):
        """
        viewtag and viewid are irrelevant!
        """
        # Process single episode
        kodicursor = self.kodicursor
        emby_db = self.emby_db
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
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            episodeid = emby_dbitem[0]
            fileid = emby_dbitem[1]
            pathid = emby_dbitem[2]
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

        # item details
        peoples = API.getPeople()
        director = API.joinList(peoples['Director'])
        writer = API.joinList(peoples['Writer'])
        cast = API.joinList(peoples['Cast'])
        producer = API.joinList(peoples['Producer'])
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
        show = emby_db.getItem_byId(seriesId)
        try:
            showid = show[0]
        except TypeError:
            # self.logMsg("Show is missing from database, trying to add", 2)
            # show = self.emby.getItem(seriesId)
            # self.logMsg("Show now: %s. Trying to add new show" % show, 2)
            # self.add_update(show)
            # show = emby_db.getItem_byId(seriesId)
            # try:
            #     showid = show[0]
            # except TypeError:
            #     log.error("Skipping: %s. Unable to add series: %s." % (itemid, seriesId))
            log.error("Parent tvshow now found, skip item")
            return False
        seasonid = self.kodi_db.addSeason(showid, season)

        # GET THE FILE AND PATH #####
        doIndirect = not self.directpath
        playurl = API.getFilePath(forceFirstMediaStream=True)
        if self.directpath:
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
            path = "plugin://plugin.video.plexkodiconnect.tvshows/%s/" % seriesId
            params = {
                'filename': tryEncode(filename),
                'id': itemid,
                'dbid': episodeid,
                'mode': "play"
            }
            filename = "%s?%s" % (path, tryDecode(urlencode(params)))
            playurl = filename
            parentPathId = self.kodi_db.addPath(
                'plugin://plugin.video.plexkodiconnect.tvshows/')

        # episodes table:
        # c18 - playurl
        # c19 - pathid
        # This information is used later by file browser.

        # UPDATE THE EPISODE #####
        if update_item:
            log.info("UPDATE episode itemid: %s" % (itemid))

            # Update the movie entry
            if self.kodiversion in (16, 17):
                # Kodi Jarvis, Krypton
                query = ' '.join((
                
                    "UPDATE episode",
                    "SET c00 = ?, c01 = ?, c03 = ?, c04 = ?, c05 = ?, c09 = ?, c10 = ?,",
                        "c12 = ?, c13 = ?, c14 = ?, c15 = ?, c16 = ?, c18 = ?, c19 = ?,",
                        "idSeason = ?",
                    "WHERE idEpisode = ?"
                ))
                kodicursor.execute(query, (title, plot, rating, writer, premieredate,
                    runtime, director, season, episode, title, airsBeforeSeason,
                    airsBeforeEpisode, playurl, pathid, seasonid, episodeid))
            else:
                query = ' '.join((
                    
                    "UPDATE episode",
                    "SET c00 = ?, c01 = ?, c03 = ?, c04 = ?, c05 = ?, c09 = ?, c10 = ?,",
                        "c12 = ?, c13 = ?, c14 = ?, c15 = ?, c16 = ?, c18 = ?, c19 = ?",
                    "WHERE idEpisode = ?"
                ))
                kodicursor.execute(query, (title, plot, rating, writer, premieredate,
                    runtime, director, season, episode, title, airsBeforeSeason,
                    airsBeforeEpisode, playurl, pathid, episodeid))

            # Update the checksum in emby table
            emby_db.updateReference(itemid, checksum)
            # Update parentid reference
            emby_db.updateParentId(itemid, seasonid)
        
        ##### OR ADD THE EPISODE #####
        else:
            log.info("ADD episode itemid: %s - Title: %s" % (itemid, title))
            # Add path
            pathid = self.kodi_db.addPath(path)
            # Add the file
            fileid = self.kodi_db.addFile(filename, pathid)
            # Create the episode entry
            if self.kodiversion in (16, 17):
                # Kodi Jarvis, Krypton
                query = (
                    '''
                    INSERT INTO episode(
                        idEpisode, idFile, c00, c01, c03, c04, c05, c09, c10, c12, c13, c14,
                        idShow, c15, c16, c18, c19, idSeason)

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    '''
                )
                kodicursor.execute(query, (episodeid, fileid, title, plot, rating, writer,
                    premieredate, runtime, director, season, episode, title, showid,
                    airsBeforeSeason, airsBeforeEpisode, playurl, pathid, seasonid))
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

            # Create the reference in emby table
            emby_db.addReference(itemid, episodeid, "Episode", "episode", fileid, pathid,
                seasonid, checksum)

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
        if not self.directpath and resume:
            # Create additional entry for widgets. This is only required for plugin/episode.
            temppathid = self.kodi_db.getPath("plugin://plugin.video.plexkodiconnect.tvshows/")
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
        # Remove showid, fileid, pathid, emby reference
        emby_db = self.emby_db
        kodicursor = self.kodicursor

        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            kodiid = emby_dbitem[0]
            fileid = emby_dbitem[1]
            pathid = emby_dbitem[2]
            parentid = emby_dbitem[3]
            mediatype = emby_dbitem[4]
            log.info("Removing %s kodiid: %s fileid: %s"
                     % (mediatype, kodiid, fileid))
        except TypeError:
            return

        ##### PROCESS ITEM #####

        # Remove the emby reference
        emby_db.removeItem(itemid)


        ##### IF EPISODE #####

        if mediatype == "episode":
            # Delete kodi episode and file, verify season and tvshow
            self.removeEpisode(kodiid, fileid)

            # Season verification
            season = emby_db.getItem_byKodiId(parentid, "season")
            try:
                showid = season[1]
            except TypeError:
                return
            
            season_episodes = emby_db.getItem_byParentId(parentid, "episode")
            if not season_episodes:
                self.removeSeason(parentid)
                emby_db.removeItem(season[0])

            # Show verification
            show = emby_db.getItem_byKodiId(showid, "tvshow")
            query = ' '.join((

                "SELECT totalCount",
                "FROM tvshowcounts",
                "WHERE idShow = ?"
            ))
            kodicursor.execute(query, (showid,))
            result = kodicursor.fetchone()
            if result and result[0] is None:
                # There's no episodes left, delete show and any possible remaining seasons
                seasons = emby_db.getItem_byParentId(showid, "season")
                for season in seasons:
                    self.removeSeason(season[1])
                else:
                    # Delete emby season entries
                    emby_db.removeItems_byParentId(showid, "season")
                self.removeShow(showid)
                emby_db.removeItem(show[0])

        ##### IF TVSHOW #####

        elif mediatype == "tvshow":
            # Remove episodes, seasons, tvshow
            seasons = emby_db.getItem_byParentId(kodiid, "season")
            for season in seasons:
                seasonid = season[1]
                season_episodes = emby_db.getItem_byParentId(seasonid, "episode")
                for episode in season_episodes:
                    self.removeEpisode(episode[1], episode[2])
                else:
                    # Remove emby episodes
                    emby_db.removeItems_byParentId(seasonid, "episode")
            else:
                # Remove emby seasons
                emby_db.removeItems_byParentId(kodiid, "season")

            # Remove tvshow
            self.removeShow(kodiid)

        ##### IF SEASON #####

        elif mediatype == "season":
            # Remove episodes, season, verify tvshow
            season_episodes = emby_db.getItem_byParentId(kodiid, "episode")
            for episode in season_episodes:
                self.removeEpisode(episode[1], episode[2])
            else:
                # Remove emby episodes
                emby_db.removeItems_byParentId(kodiid, "episode")
            
            # Remove season
            self.removeSeason(kodiid)

            # Show verification
            seasons = emby_db.getItem_byParentId(parentid, "season")
            if not seasons:
                # There's no seasons, delete the show
                self.removeShow(parentid)
                emby_db.removeItem_byKodiId(parentid, "tvshow")

        log.debug("Deleted %s: %s from kodi database" % (mediatype, itemid))

    def removeShow(self, kodiid):
        kodicursor = self.kodicursor
        self.artwork.deleteArtwork(kodiid, "tvshow", kodicursor)
        kodicursor.execute("DELETE FROM tvshow WHERE idShow = ?", (kodiid,))
        log.info("Removed tvshow: %s." % kodiid)

    def removeSeason(self, kodiid):
        kodicursor = self.kodicursor
        self.artwork.deleteArtwork(kodiid, "season", kodicursor)
        kodicursor.execute("DELETE FROM seasons WHERE idSeason = ?", (kodiid,))
        log.info("Removed season: %s." % kodiid)

    def removeEpisode(self, kodiid, fileid):
        kodicursor = self.kodicursor
        self.artwork.deleteArtwork(kodiid, "episode", kodicursor)
        kodicursor.execute("DELETE FROM episode WHERE idEpisode = ?", (kodiid,))
        kodicursor.execute("DELETE FROM files WHERE idFile = ?", (fileid,))
        log.info("Removed episode: %s." % kodiid)


class Music(Items):

    def __init__(self):
        Items.__init__(self)

        self.directstream = settings('streamMusic') == "true"
        self.enableimportsongrating = settings('enableImportSongRating') == "true"
        self.enableexportsongrating = settings('enableExportSongRating') == "true"
        self.enableupdatesongrating = settings('enableUpdateSongRating') == "true"

    def __enter__(self):
        """
        OVERWRITE this method, because we need to open another DB.
        Open DB connections and cursors
        """
        self.embyconn = kodiSQL('emby')
        self.embycursor = self.embyconn.cursor()
        # Here it is, not 'video' but 'music'
        self.kodiconn = kodiSQL('music')
        self.kodicursor = self.kodiconn.cursor()
        self.emby_db = embydb.Embydb_Functions(self.embycursor)
        self.kodi_db = kodidb.Kodidb_Functions(self.kodicursor)
        return self

    @CatchExceptions(warnuser=True)
    def add_updateArtist(self, item, viewtag=None, viewid=None,
                         artisttype="MusicArtist"):
        kodicursor = self.kodicursor
        emby_db = self.emby_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            artistid = emby_dbitem[0]
        except TypeError:
            update_item = False

        # The artist details #####
        lastScraped = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dateadded = API.getDateCreated()
        checksum = API.getChecksum()

        name, sortname = API.getTitle()
        # musicBrainzId = API.getProvider('MusicBrainzArtist')
        musicBrainzId = None
        genres = API.joinList(API.getGenres())
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
            # Update the checksum in emby table
            emby_db.updateReference(itemid, checksum)

        # OR ADD THE ARTIST #####
        else:
            log.info("ADD artist itemid: %s - Name: %s" % (itemid, name))
            # safety checks: It looks like Emby supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            artistid = self.kodi_db.addArtist(name, musicBrainzId)
            # Create the reference in emby table
            emby_db.addReference(
                itemid, artistid, artisttype, "artist", checksum=checksum)

        # Process the artist
        if self.kodiversion in (16, 17):
            query = ' '.join((

                "UPDATE artist",
                "SET strGenres = ?, strBiography = ?, strImage = ?, strFanart = ?,",
                    "lastScraped = ?",
                "WHERE idArtist = ?"
            ))
            kodicursor.execute(query, (genres, bio, thumb, fanart,
                                       lastScraped, artistid))
        else:
            query = ' '.join((

                "UPDATE artist",
                "SET strGenres = ?, strBiography = ?, strImage = ?, strFanart = ?,",
                    "lastScraped = ?, dateAdded = ?",
                "WHERE idArtist = ?"
            ))
            kodicursor.execute(query, (genres, bio, thumb, fanart, lastScraped,
                                       dateadded, artistid))

        # Update artwork
        artwork.addArtwork(artworks, artistid, "artist", kodicursor)

    @CatchExceptions(warnuser=True)
    def add_updateAlbum(self, item, viewtag=None, viewid=None):
        kodicursor = self.kodicursor
        emby_db = self.emby_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()
        if not itemid:
            log.error('Error processing Album, skipping')
            return
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            albumid = emby_dbitem[0]
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
        genres = API.getGenres()
        genre = API.joinList(genres)
        bio = API.getPlot()
        rating = userdata['UserRating']
        studio = API.getMusicStudio()
        # artists = item['AlbumArtists']
        # if not artists:
        #     artists = item['ArtistItems']
        # artistname = []
        # for artist in artists:
        #     artistname.append(artist['Name'])
        artistname = item.attrib.get('parentTitle')
        if not artistname:
            artistname = item.attrib.get('originalTitle')

        # Associate artwork
        artworks = API.getAllArtwork(parentInfo=True)
        thumb = artworks['Primary']
        if thumb:
            thumb = "<thumb>%s</thumb>" % thumb

        # UPDATE THE ALBUM #####
        if update_item:
            log.info("UPDATE album itemid: %s - Name: %s" % (itemid, name))
            # Update the checksum in emby table
            emby_db.updateReference(itemid, checksum)

        # OR ADD THE ALBUM #####
        else:
            log.info("ADD album itemid: %s - Name: %s" % (itemid, name))
            # safety checks: It looks like Emby supports the same artist
            # multiple times.
            # Kodi doesn't allow that. In case that happens we just merge the
            # artist entries.
            albumid = self.kodi_db.addAlbum(name, musicBrainzId)
            # Create the reference in emby table
            emby_db.addReference(
                itemid, albumid, "MusicAlbum", "album", checksum=checksum)

        # Process the album info
        if self.kodiversion == 17:
            # Kodi Krypton
            query = ' '.join((

                "UPDATE album",
                "SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?, strImage = ?,",
                    "iUserrating = ?, lastScraped = ?, strReleaseType = ?, "
                    "strLabel = ? ",
                "WHERE idAlbum = ?"
            ))
            kodicursor.execute(query, (artistname, year, genre, bio, thumb,
                                       rating, lastScraped, "album", studio,
                                       albumid))
        elif self.kodiversion == 16:
            # Kodi Jarvis
            query = ' '.join((

                "UPDATE album",
                "SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?, strImage = ?,",
                    "iRating = ?, lastScraped = ?, strReleaseType = ?, "
                    "strLabel = ? ",
                "WHERE idAlbum = ?"
            ))
            kodicursor.execute(query, (artistname, year, genre, bio, thumb,
                                       rating, lastScraped, "album", studio,
                                       albumid))
        elif self.kodiversion == 15:
            # Kodi Isengard
            query = ' '.join((

                "UPDATE album",
                "SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?, strImage = ?,",
                    "iRating = ?, lastScraped = ?, dateAdded = ?, "
                    "strReleaseType = ?, strLabel = ? ",
                "WHERE idAlbum = ?"
            ))
            kodicursor.execute(query, (artistname, year, genre, bio, thumb,
                                       rating, lastScraped, dateadded,
                                       "album", studio, albumid))
        else:
            # Kodi Helix
            query = ' '.join((

                "UPDATE album",
                "SET strArtists = ?, iYear = ?, strGenres = ?, strReview = ?, strImage = ?,",
                    "iRating = ?, lastScraped = ?, dateAdded = ?, "
                    "strLabel = ? ",
                "WHERE idAlbum = ?"
            ))
            kodicursor.execute(query, (artistname, year, genre, bio, thumb,
                                       rating, lastScraped, dateadded, studio,
                                       albumid))

        # Associate the parentid for emby reference
        parentId = item.attrib.get('parentRatingKey')
        if parentId is not None:
            emby_dbartist = emby_db.getItem_byId(parentId)
            try:
                artistid = emby_dbartist[0]
            except TypeError:
                log.info('Artist %s does not exist in emby database'
                         % parentId)
                artist = GetPlexMetadata(parentId)
                # Item may not be an artist, verification necessary.
                if artist is not None and artist != 401:
                    if artist[0].attrib.get('type') == "artist":
                        # Update with the parentId, for remove reference
                        emby_db.addReference(
                            parentId, parentId, "MusicArtist", "artist")
                        emby_db.updateParentId(itemid, parentId)
            else:
                # Update emby reference with the artistid
                emby_db.updateParentId(itemid, artistid)

        # Assign main artists to album
        # Plex unfortunately only supports 1 artist :-(
        artistId = parentId
        emby_dbartist = emby_db.getItem_byId(artistId)
        try:
            artistid = emby_dbartist[0]
        except TypeError:
            # Artist does not exist in emby database, create the reference
            log.info('Artist %s does not exist in Plex database' % artistId)
            artist = GetPlexMetadata(artistId)
            if artist is not None and artist != 401:
                self.add_updateArtist(artist[0], artisttype="AlbumArtist")
                emby_dbartist = emby_db.getItem_byId(artistId)
                artistid = emby_dbartist[0]
        else:
            # Best take this name over anything else.
            query = "UPDATE artist SET strArtist = ? WHERE idArtist = ?"
            kodicursor.execute(query, (artistname, artistid,))
            log.info("UPDATE artist: strArtist: %s, idArtist: %s"
                     % (artistname, artistid))

        # Add artist to album
        query = (
            '''
            INSERT OR REPLACE INTO album_artist(idArtist, idAlbum, strArtist)

            VALUES (?, ?, ?)
            '''
        )
        kodicursor.execute(query, (artistid, albumid, artistname))
        # Update discography
        query = (
            '''
            INSERT OR REPLACE INTO discography(idArtist, strAlbum, strYear)

            VALUES (?, ?, ?)
            '''
        )
        kodicursor.execute(query, (artistid, name, year))
        # Update emby reference with parentid
        emby_db.updateParentId(artistId, albumid)
        # Add genres
        self.kodi_db.addMusicGenres(albumid, genres, "album")
        # Update artwork
        artwork.addArtwork(artworks, albumid, "album", kodicursor)

    @CatchExceptions(warnuser=True)
    def add_updateSong(self, item, viewtag=None, viewid=None):
        # Process single song
        kodicursor = self.kodicursor
        emby_db = self.emby_db
        artwork = self.artwork
        API = PlexAPI.API(item)

        update_item = True
        itemid = API.getRatingKey()
        if not itemid:
            log.error('Error processing Song; skipping')
            return
        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            songid = emby_dbitem[0]
            pathid = emby_dbitem[2]
            albumid = emby_dbitem[3]
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
        genres = API.getGenres()
        genre = API.joinList(genres)
        artists = item.attrib.get('grandparentTitle')
        tracknumber = int(item.attrib.get('index', 0))
        disc = int(item.attrib.get('parentIndex', 1))
        if disc == 1:
            track = tracknumber
        else:
            track = disc*2**16 + tracknumber
        year = API.getYear()
        resume, duration = API.getRuntime()
        rating = int(userdata['UserRating'])

        hasEmbeddedCover = False
        comment = None

        # GET THE FILE AND PATH #####
        doIndirect = not self.directpath
        if self.directpath:
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
            query = ' '.join((
                "UPDATE song",
                "SET idAlbum = ?, strArtists = ?, strGenres = ?, strTitle = ?, iTrack = ?,",
                    "iDuration = ?, iYear = ?, strFilename = ?, iTimesPlayed = ?, lastplayed = ?,",
                    "rating = ?, comment = ?",
                "WHERE idSong = ?"
            ))
            kodicursor.execute(query, (albumid, artists, genre, title, track,
                                       duration, year, filename, playcount,
                                       dateplayed, rating, comment, songid))

            # Update the checksum in emby table
            emby_db.updateReference(itemid, checksum)

        # OR ADD THE SONG #####
        else:
            log.info("ADD song itemid: %s - Title: %s" % (itemid, title))

            # Add path
            pathid = self.kodi_db.addPath(path, strHash="123")

            try:
                # Get the album
                emby_dbalbum = emby_db.getItem_byId(
                    item.attrib.get('parentRatingKey'))
                albumid = emby_dbalbum[0]
            except KeyError:
                # Verify if there's an album associated.
                album_name = item.get('parentTitle')
                if album_name:
                    log.info("Creating virtual music album for song: %s."
                             % itemid)
                    albumid = self.kodi_db.addAlbum(album_name, API.getProvider('MusicBrainzAlbum'))
                    emby_db.addReference("%salbum%s" % (itemid, albumid), albumid, "MusicAlbum_", "album")
                else:
                    # No album Id associated to the song.
                    log.error("Song itemid: %s has no albumId associated."
                              % itemid)
                    return False

            except TypeError:
                # No album found. Let's create it
                log.info("Album database entry missing.")
                emby_albumId = item.attrib.get('parentRatingKey')
                album = GetPlexMetadata(emby_albumId)
                if album is None or album == 401:
                    log.error('Could not download album, abort')
                    return
                self.add_updateAlbum(album[0])
                emby_dbalbum = emby_db.getItem_byId(emby_albumId)
                try:
                    albumid = emby_dbalbum[0]
                    log.debug("Found albumid: %s" % albumid)
                except TypeError:
                    # No album found, create a single's album
                    log.info("Failed to add album. Creating singles.")
                    kodicursor.execute("select coalesce(max(idAlbum),0) from album")
                    albumid = kodicursor.fetchone()[0] + 1
                    if self.kodiversion == 16:
                        # Kodi Jarvis
                        query = (
                            '''
                            INSERT INTO album(idAlbum, strGenres, iYear, strReleaseType)

                            VALUES (?, ?, ?, ?)
                            '''
                        )
                        kodicursor.execute(query, (albumid, genre, year, "single"))
                    elif self.kodiversion == 15:
                        # Kodi Isengard
                        query = (
                            '''
                            INSERT INTO album(idAlbum, strGenres, iYear, dateAdded, strReleaseType)

                            VALUES (?, ?, ?, ?, ?)
                            '''
                        )
                        kodicursor.execute(query, (albumid, genre, year, dateadded, "single"))
                    else:
                        # Kodi Helix
                        query = (
                            '''
                            INSERT INTO album(idAlbum, strGenres, iYear, dateAdded)

                            VALUES (?, ?, ?, ?)
                            '''
                        )
                        kodicursor.execute(query, (albumid, genre, year, dateadded))

            # Create the song entry
            query = (
                '''
                INSERT INTO song(
                    idSong, idAlbum, idPath, strArtists, strGenres, strTitle, iTrack,
                    iDuration, iYear, strFileName, strMusicBrainzTrackID, iTimesPlayed, lastplayed,
                    rating, iStartOffset, iEndOffset)

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
            )
            kodicursor.execute(
                query, (songid, albumid, pathid, artists, genre, title, track,
                        duration, year, filename, musicBrainzId, playcount,
                        dateplayed, rating, 0, 0))

            # Create the reference in emby table
            emby_db.addReference(
                itemid, songid, "Audio", "song",
                pathid=pathid,
                parentid=albumid,
                checksum=checksum)

        # Link song to album
        query = (
            '''
            INSERT OR REPLACE INTO albuminfosong(
                idAlbumInfoSong, idAlbumInfo, iTrack, strTitle, iDuration)

            VALUES (?, ?, ?, ?, ?)
            '''
        )
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
            artist_edb = emby_db.getItem_byId(artist_eid)
            try:
                artistid = artist_edb[0]
            except TypeError:
                # Artist is missing from emby database, add it.
                artistXml = GetPlexMetadata(artist_eid)
                if artistXml is None or artistXml == 401:
                    log.error('Error getting artist, abort')
                    return
                self.add_updateArtist(artistXml[0])
                artist_edb = emby_db.getItem_byId(artist_eid)
                artistid = artist_edb[0]
            finally:
                if self.kodiversion >= 17:
                    # Kodi Krypton
                    query = (
                        '''
                        INSERT OR REPLACE INTO song_artist(idArtist, idSong, idRole, iOrder, strArtist)
                        VALUES (?, ?, ?, ?, ?)
                        '''
                    )
                    kodicursor.execute(query,(artistid, songid, 1, index, artist_name))
                    # May want to look into only doing this once?
                    query = ( 
                        '''
                        INSERT OR REPLACE INTO role(idRole, strRole)
                        VALUES (?, ?)
                        '''
                    )
                    kodicursor.execute(query, (1, 'Composer'))
                else:
                    query = (
                        '''
                        INSERT OR REPLACE INTO song_artist(idArtist, idSong, iOrder, strArtist)
                        VALUES (?, ?, ?, ?)
                        '''
                    )
                    kodicursor.execute(query, (artistid, songid, index, artist_name))

        # Verify if album artist exists
        album_artists = []
        # for artist in item['AlbumArtists']:
        if False:
            artist_name = artist['Name']
            album_artists.append(artist_name)
            artist_eid = artist['Id']
            artist_edb = emby_db.getItem_byId(artist_eid)
            try:
                artistid = artist_edb[0]
            except TypeError:
                # Artist is missing from emby database, add it.
                artistXml = GetPlexMetadata(artist_eid)
                if artistXml is None or artistXml == 401:
                    log.error('Error getting artist, abort')
                    return
                self.add_updateArtist(artistXml)
                artist_edb = emby_db.getItem_byId(artist_eid)
                artistid = artist_edb[0]
            finally:
                query = (
                    '''
                    INSERT OR REPLACE INTO album_artist(idArtist, idAlbum, strArtist)
                    VALUES (?, ?, ?)
                    '''
                )
                kodicursor.execute(query, (artistid, albumid, artist_name))
                # Update discography
                if item.get('Album'):
                    query = (
                        '''
                        INSERT OR REPLACE INTO discography(idArtist, strAlbum, strYear)
                        VALUES (?, ?, ?)
                        '''
                    )
                    kodicursor.execute(query, (artistid, item['Album'], 0))
        # else:
        if False:
            album_artists = " / ".join(album_artists)
            query = ' '.join((

                "SELECT strArtists",
                "FROM album",
                "WHERE idAlbum = ?"
            ))
            kodicursor.execute(query, (albumid,))
            result = kodicursor.fetchone()
            if result and result[0] != album_artists:
                # Field is empty
                if self.kodiversion in (16, 17):
                    # Kodi Jarvis, Krypton
                    query = "UPDATE album SET strArtists = ? WHERE idAlbum = ?"
                    kodicursor.execute(query, (album_artists, albumid))
                elif self.kodiversion == 15:
                    # Kodi Isengard
                    query = "UPDATE album SET strArtists = ? WHERE idAlbum = ?"
                    kodicursor.execute(query, (album_artists, albumid))
                else:
                    # Kodi Helix
                    query = "UPDATE album SET strArtists = ? WHERE idAlbum = ?"
                    kodicursor.execute(query, (album_artists, albumid))

        # Add genres
        self.kodi_db.addMusicGenres(songid, genres, "song")

        # Update artwork
        allart = API.getAllArtwork(parentInfo=True)
        if hasEmbeddedCover:
            allart["Primary"] = "image://music@" + artwork.single_urlencode( playurl )
        artwork.addArtwork(allart, songid, "song", kodicursor)

        # if item.get('AlbumId') is None:
        if item.get('parentKey') is None:
            # Update album artwork
            artwork.addArtwork(allart, albumid, "album", kodicursor)

    def remove(self, itemid):
        # Remove kodiid, fileid, pathid, emby reference
        emby_db = self.emby_db

        emby_dbitem = emby_db.getItem_byId(itemid)
        try:
            kodiid = emby_dbitem[0]
            mediatype = emby_dbitem[4]
            log.info("Removing %s kodiid: %s" % (mediatype, kodiid))
        except TypeError:
            return

        ##### PROCESS ITEM #####

        # Remove the emby reference
        emby_db.removeItem(itemid)

        ##### IF SONG #####

        if mediatype == "song":
            # Delete song
            self.removeSong(kodiid)
            # This should only address single song scenario, where server doesn't actually
            # create an album for the song. 
            emby_db.removeWildItem(itemid)

            for item in emby_db.getItem_byWildId(itemid):

                item_kid = item[0]
                item_mediatype = item[1]

                if item_mediatype == "album":
                    childs = emby_db.getItem_byParentId(item_kid, "song")
                    if not childs:
                        # Delete album
                        self.removeAlbum(item_kid)

        ##### IF ALBUM #####

        elif mediatype == "album":
            # Delete songs, album
            album_songs = emby_db.getItem_byParentId(kodiid, "song")
            for song in album_songs:
                self.removeSong(song[1])
            else:
                # Remove emby songs
                emby_db.removeItems_byParentId(kodiid, "song")

            # Remove the album
            self.removeAlbum(kodiid)

        ##### IF ARTIST #####

        elif mediatype == "artist":
            # Delete songs, album, artist
            albums = emby_db.getItem_byParentId(kodiid, "album")
            for album in albums:
                albumid = album[1]
                album_songs = emby_db.getItem_byParentId(albumid, "song")
                for song in album_songs:
                    self.removeSong(song[1])
                else:
                    # Remove emby song
                    emby_db.removeItems_byParentId(albumid, "song")
                    # Remove emby artist
                    emby_db.removeItems_byParentId(albumid, "artist")
                    # Remove kodi album
                    self.removeAlbum(albumid)
            else:
                # Remove emby albums
                emby_db.removeItems_byParentId(kodiid, "album")

            # Remove artist
            self.removeArtist(kodiid)

        log.info("Deleted %s: %s from kodi database" % (mediatype, itemid))

    def removeSong(self, kodiid):
        self.artwork.deleteArtwork(kodiid, "song", self.kodicursor)
        self.kodicursor.execute("DELETE FROM song WHERE idSong = ?",
                                (kodiid,))

    def removeAlbum(self, kodiid):
        self.artwork.deleteArtwork(kodiid, "album", self.kodicursor)
        self.kodicursor.execute("DELETE FROM album WHERE idAlbum = ?",
                                (kodiid,))

    def removeArtist(self, kodiid):
        self.artwork.deleteArtwork(kodiid, "artist", self.kodicursor)
        self.kodicursor.execute("DELETE FROM artist WHERE idArtist = ?",
                                (kodiid,))
