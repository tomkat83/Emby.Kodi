#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from sqlite3 import IntegrityError

from . import common
from .. import path_ops, timing, variables as v

LOG = getLogger('PLEX.kodi_db.video')

MOVIE_PATH = 'http://127.0.0.1:%s/plex/kodi/movies/' % v.WEBSERVICE_PORT
SHOW_PATH = 'http://127.0.0.1:%s/plex/kodi/shows/' % v.WEBSERVICE_PORT


class KodiVideoDB(common.KodiDBBase):
    db_kind = 'video'

    @common.catch_operationalerrors
    def setup_path_table(self):
        """
        Use with Kodi video DB

        Sets strContent to e.g. 'movies' and strScraper to metadata.local

        For some reason, Kodi ignores this if done via itemtypes while e.g.
        adding or updating items. (addPath method does NOT work)
        """
        path_id = self.get_path(MOVIE_PATH)
        if path_id is None:
            self.cursor.execute("SELECT COALESCE(MAX(idPath),0) FROM path")
            path_id = self.cursor.fetchone()[0] + 1
            query = '''
                INSERT INTO path(idPath,
                                 strPath,
                                 strContent,
                                 strScraper,
                                 noUpdate,
                                 exclude)
                VALUES (?, ?, ?, ?, ?, ?)
            '''
            self.cursor.execute(query, (path_id,
                                        MOVIE_PATH,
                                        'movies',
                                        'metadata.local',
                                        1,
                                        0))
        # And TV shows
        path_id = self.get_path(SHOW_PATH)
        if path_id is None:
            self.cursor.execute("SELECT COALESCE(MAX(idPath),0) FROM path")
            path_id = self.cursor.fetchone()[0] + 1
            query = '''
                INSERT INTO path(idPath,
                                 strPath,
                                 strContent,
                                 strScraper,
                                 noUpdate,
                                 exclude)
                VALUES (?, ?, ?, ?, ?, ?)
            '''
            self.cursor.execute(query, (path_id,
                                        SHOW_PATH,
                                        'tvshows',
                                        'metadata.local',
                                        1,
                                        0))

    @common.catch_operationalerrors
    def parent_path_id(self, path):
        """
        Video DB: Adds all subdirectories to path table while setting a "trail"
        of parent path ids
        """
        parentpath = path_ops.path.abspath(
            path_ops.path.join(path,
                               path_ops.decode_path(path_ops.path.pardir)))
        pathid = self.get_path(parentpath)
        if pathid is None:
            self.cursor.execute("SELECT COALESCE(MAX(idPath),0) FROM path")
            pathid = self.cursor.fetchone()[0] + 1
            self.cursor.execute('''
                                INSERT INTO path(idPath, strPath, dateAdded)
                                VALUES (?, ?, ?)
                                ''',
                                (pathid, parentpath, timing.kodi_now()))
            if parentpath != path:
                # In case we end up having media in the filesystem root, C:\
                parent_id = self.parent_path_id(parentpath)
                self.update_parentpath_id(parent_id, pathid)
        return pathid

    @common.catch_operationalerrors
    def update_parentpath_id(self, parent_id, pathid):
        """
        Dedicated method in order to catch OperationalErrors correctly
        """
        self.cursor.execute('UPDATE path SET idParentPath = ? WHERE idPath = ?',
                            (parent_id, pathid))

    @common.catch_operationalerrors
    def add_path(self, path, date_added=None, id_parent_path=None,
                 content=None, scraper=None):
        """
        Returns the idPath from the path table. Creates a new entry if path
        [unicode] does not yet exist (using date_added [kodi date type],
        id_parent_path [int], content ['tvshows', 'movies', None], scraper
        [usually 'metadata.local'])

        WILL activate noUpdate for the path!
        """
        path = '' if path is None else path
        self.cursor.execute('SELECT idPath FROM path WHERE strPath = ? LIMIT 1',
                            (path, ))
        try:
            pathid = self.cursor.fetchone()[0]
        except TypeError:
            self.cursor.execute("SELECT COALESCE(MAX(idPath),0) FROM path")
            pathid = self.cursor.fetchone()[0] + 1
            self.cursor.execute('''
                                INSERT INTO path(
                                    idPath,
                                    strPath,
                                    dateAdded,
                                    idParentPath,
                                    strContent,
                                    strScraper,
                                    noUpdate)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ''',
                                (pathid, path, date_added, id_parent_path,
                                 content, scraper, 1))
        return pathid

    def get_path(self, path):
        """
        Returns the idPath from the path table for path [unicode] or None
        """
        self.cursor.execute('SELECT idPath FROM path WHERE strPath = ?',
                            (path, ))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    @common.catch_operationalerrors
    def add_file(self, filename, path_id, date_added):
        """
        Adds the filename [unicode] to the table files if not already added
        and returns the idFile.
        """
        self.cursor.execute('SELECT COALESCE(MAX(idFile), 0) FROM files')
        file_id = self.cursor.fetchone()[0] + 1
        self.cursor.execute('''
                            INSERT INTO files(
                                idFile,
                                idPath,
                                strFilename,
                                dateAdded)
                            VALUES (?, ?, ?, ?)
                            ''',
                            (file_id, path_id, filename, date_added))
        return file_id

    def modify_file(self, filename, path_id, date_added):
        self.cursor.execute('SELECT idFile FROM files WHERE idPath = ? AND strFilename = ?',
                            (path_id, filename))
        try:
            file_id = self.cursor.fetchone()[0]
        except TypeError:
            file_id = self.add_file(filename, path_id, date_added)
        return file_id

    def obsolete_file_ids(self):
        """
        Returns a generator for idFile of all Kodi file ids that do not have a
        dateAdded set (dateAdded NULL) and the associated path entry has
        a field noUpdate of NULL as well as dateAdded of NULL
        """
        return (x[0] for x in self.cursor.execute("""
            SELECT files.idFile
            FROM files
            LEFT JOIN path ON path.idPath = files.idPath
            WHERE files.dateAdded IS NULL
            AND path.noUpdate IS NULL
            AND path.dateAdded IS NULL
            """))

    def show_id_from_path(self, path):
        """
        Returns the idShow for path [unicode] or None
        """
        self.cursor.execute('SELECT idPath FROM path WHERE strPath = ? LIMIT 1',
                            (path, ))
        try:
            path_id = self.cursor.fetchone()[0]
        except TypeError:
            return
        self.cursor.execute('SELECT idShow FROM tvshowlinkpath WHERE idPath = ? LIMIT 1',
                            (path_id, ))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    @common.catch_operationalerrors
    def remove_file(self, file_id, remove_orphans=True):
        """
        Removes the entry for file_id from the files table. Will also delete
        entries from the associated tables: bookmark, settings, streamdetails.
        If remove_orphans is true, this method will delete any orphaned path
        entries in the Kodi path table
        """
        self.cursor.execute('SELECT idPath FROM files WHERE idFile = ? LIMIT 1',
                            (file_id,))
        try:
            path_id = self.cursor.fetchone()[0]
        except TypeError:
            return
        self.cursor.execute('DELETE FROM files WHERE idFile = ?',
                            (file_id,))
        self.cursor.execute('DELETE FROM bookmark WHERE idFile = ?',
                            (file_id,))
        self.cursor.execute('DELETE FROM settings WHERE idFile = ?',
                            (file_id,))
        self.cursor.execute('DELETE FROM streamdetails WHERE idFile = ?',
                            (file_id,))
        self.cursor.execute('DELETE FROM stacktimes WHERE idFile = ?',
                            (file_id,))
        if remove_orphans:
            # Delete orphaned path entry
            self.cursor.execute('SELECT idFile FROM files WHERE idPath = ? LIMIT 1',
                                (path_id,))
            if self.cursor.fetchone() is None:
                # Make sure we're not deleting our root paths!
                query = '''
                    DELETE FROM path
                    WHERE idPath = ? AND strPath NOT IN (?, ?)
                '''
                self.cursor.execute(query, (path_id, MOVIE_PATH, SHOW_PATH))

    @common.catch_operationalerrors
    def _modify_link_and_table(self, kodi_id, kodi_type, entries, link_table,
                               table, key, first_id=None):
        first_id = first_id if first_id is not None else 1
        entry_ids = []
        for entry in entries:
            self.cursor.execute('''
                SELECT %s FROM %s WHERE name = ? COLLATE NOCASE LIMIT 1
            ''' % (key, table), (entry, ))
            try:
                entry_id = self.cursor.fetchone()[0]
            except TypeError:
                self.cursor.execute('SELECT COALESCE(MAX(%s), %s) FROM %s'
                                    % (key, first_id - 1, table))
                entry_id = self.cursor.fetchone()[0] + 1
                self.cursor.execute('INSERT INTO %s(%s, name) values(?, ?)'
                                    % (table, key), (entry_id, entry))
            finally:
                entry_ids.append(entry_id)
        # Now process the ids obtained from the names
        # Get the existing, old entries
        outdated_entries = []
        for entry_id in self.cursor.execute('SELECT %s FROM %s WHERE media_id = ? AND media_type = ?'
                                            % (key, link_table), (kodi_id, kodi_type)):
            try:
                entry_ids.remove(entry_id[0])
            except ValueError:
                outdated_entries.append(entry_id[0])
        # Add all new entries that haven't already been added
        for entry_id in entry_ids:
            try:
                self.cursor.execute('INSERT INTO %s VALUES (?, ?, ?)' % link_table,
                                    (entry_id, kodi_id, kodi_type))
            except IntegrityError:
                LOG.info('IntegrityError: skipping entry %s for table %s',
                         entry_id, link_table)
        # Delete all outdated references in the link table. Also check whether
        # we need to delete orphaned entries in the master table
        for entry_id in outdated_entries:
            self.cursor.execute('''
                DELETE FROM %s WHERE %s = ? AND media_id = ? AND media_type = ?
            ''' % (link_table, key), (entry_id, kodi_id, kodi_type))
            self.cursor.execute('SELECT %s FROM %s WHERE %s = ?' % (key, link_table, key),
                                (entry_id, ))
            if self.cursor.fetchone() is None:
                # Delete in the original table because entry is now orphaned
                self.cursor.execute('DELETE FROM %s WHERE %s = ?' % (table, key),
                                    (entry_id, ))

    def modify_countries(self, kodi_id, kodi_type, countries=None):
        """
        Writes a country (string) in the list countries into the Kodi DB. Will
        also delete any orphaned country entries.
        """
        self._modify_link_and_table(kodi_id,
                                    kodi_type,
                                    countries if countries else [],
                                    'country_link',
                                    'country',
                                    'country_id')

    def modify_genres(self, kodi_id, kodi_type, genres=None):
        """
        Writes a country (string) in the list countries into the Kodi DB. Will
        also delete any orphaned country entries.
        """
        self._modify_link_and_table(kodi_id,
                                    kodi_type,
                                    genres if genres else [],
                                    'genre_link',
                                    'genre',
                                    'genre_id')

    def modify_studios(self, kodi_id, kodi_type, studios=None):
        """
        Writes a country (string) in the list countries into the Kodi DB. Will
        also delete any orphaned country entries.
        """
        self._modify_link_and_table(kodi_id,
                                    kodi_type,
                                    studios if studios else [],
                                    'studio_link',
                                    'studio',
                                    'studio_id')

    def modify_tags(self, kodi_id, kodi_type, tags=None):
        """
        Writes a country (string) in the list countries into the Kodi DB. Will
        also delete any orphaned country entries.
        """
        self._modify_link_and_table(kodi_id,
                                    kodi_type,
                                    tags if tags else [],
                                    'tag_link',
                                    'tag',
                                    'tag_id')

    def add_people(self, kodi_id, kodi_type, people):
        """
        Makes sure that actors, directors and writers are recorded correctly
        for the elmement kodi_id, kodi_type.
        Will also delete a freshly orphaned actor entry.
        """
        for kind, people_list in people.iteritems():
            self._add_people_kind(kodi_id, kodi_type, kind, people_list)

    @common.catch_operationalerrors
    def _add_people_kind(self, kodi_id, kodi_type, kind, people_list):
        # Save new people to Kodi DB by iterating over the remaining entries
        if kind == 'actor':
            for person in people_list:
                # Make sure the person entry in table actor exists
                actor_id = self._get_actor_id(person[0], art_url=person[1])
                # Link the person with the media element
                try:
                    self.cursor.execute('INSERT INTO actor_link VALUES (?, ?, ?, ?, ?)',
                                        (actor_id, kodi_id, kodi_type,
                                         person[2], person[3]))
                except IntegrityError:
                    # With Kodi, an actor may have only one role, unlike Plex
                    pass
        else:
            for person in people_list:
                # Make sure the person entry in table actor exists:
                actor_id = self._get_actor_id(person[0])
                # Link the person with the media element
                try:
                    self.cursor.execute('INSERT INTO %s_link VALUES (?, ?, ?)' % kind,
                                        (actor_id, kodi_id, kodi_type))
                except IntegrityError:
                    # Again, Kodi may have only one person assigned to a role
                    pass

    def modify_people(self, kodi_id, kodi_type, people=None):
        """
        Makes sure that actors, directors and writers are recorded correctly
        for the elmement kodi_id, kodi_type.
        Will also delete a freshly orphaned actor entry.
        """
        for kind, people_list in (people if people else
                                  {'actor': [],
                                   'director': [],
                                   'writer': []}).iteritems():
            self._modify_people_kind(kodi_id, kodi_type, kind, people_list)

    @common.catch_operationalerrors
    def _modify_people_kind(self, kodi_id, kodi_type, kind, people_list):
        # Get the people already saved in the DB for this specific item
        if kind == 'actor':
            query = '''
                SELECT actor.actor_id, actor.name, art.url, actor_link.role,
                    actor_link.cast_order
                FROM actor_link
                LEFT JOIN actor ON actor.actor_id = actor_link.actor_id
                LEFT JOIN art ON (art.media_id = actor_link.actor_id AND
                                  art.media_type = 'actor')
                WHERE actor_link.media_id = ? AND actor_link.media_type = ?
            '''
        else:
            query = '''
                SELECT actor.actor_id, actor.name
                FROM {0}_link
                LEFT JOIN actor ON actor.actor_id = {0}_link.actor_id
                WHERE {0}_link.media_id = ? AND {0}_link.media_type = ?
            '''.format(kind)
        self.cursor.execute(query, (kodi_id, kodi_type))
        old_people = self.cursor.fetchall()
        # Determine which people we need to save or delete
        outdated_people = []
        for person in old_people:
            try:
                people_list.remove(person[1:])
            except ValueError:
                outdated_people.append(person)
        # Get rid of old entries
        query = '''
            DELETE FROM %s_link
            WHERE actor_id = ? AND media_id = ? AND media_type = ?
        ''' % kind
        query_actor_check = 'SELECT actor_id FROM %s_link WHERE actor_id = ?'
        query_actor_delete = 'DELETE FROM actor WHERE actor_id = ?'
        for person in outdated_people:
            # Delete the outdated entry
            self.cursor.execute(query, (person[0], kodi_id, kodi_type))
            # Do we now have orphaned entries?
            for person_kind in ('actor', 'writer', 'director'):
                self.cursor.execute(query_actor_check % person_kind,
                                    (person[0],))
                if self.cursor.fetchone() is not None:
                    break
            else:
                # person entry in actor table is now orphaned
                # Delete the person from actor table
                self.cursor.execute(query_actor_delete, (person[0],))
                if kind == 'actor':
                    # Delete any associated artwork
                    self.delete_artwork(person[0], 'actor')
        # Save new people to Kodi DB by iterating over the remaining entries
        self._add_people_kind(kodi_id, kodi_type, kind, people_list)

    @common.catch_operationalerrors
    def _new_actor_id(self, name, art_url):
        # Not yet in actor DB, add person
        self.cursor.execute('SELECT COALESCE(MAX(actor_id), 0) FROM actor')
        actor_id = self.cursor.fetchone()[0] + 1
        self.cursor.execute('INSERT INTO actor(actor_id, name) VALUES (?, ?)',
                            (actor_id, name))
        if art_url:
            self.add_art(art_url, actor_id, 'actor', 'thumb')
        return actor_id

    def _get_actor_id(self, name, art_url=None):
        """
        Returns the actor_id [int] for name [unicode] in table actor (without
        ensuring that the name matches).
        If not, will create a new record with actor_id, name, art_url

        Uses Plex ids and thus assumes that Plex person id is unique!
        """
        self.cursor.execute('SELECT actor_id FROM actor WHERE name=? LIMIT 1',
                            (name,))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            return self._new_actor_id(name, art_url)

    def get_art(self, kodi_id, kodi_type):
        """
        Returns a dict of all available artwork with unicode urls/paths:
        {
            'thumb'
            'poster'
            'banner'
            'clearart'
            'clearlogo'
            'discart'
            'fanart'    and also potentially more fanart 'fanart1', 'fanart2',
        }
        Missing fanart will not appear in the dict. 'landscape' and 'icon'
        might be implemented in the future.
        """
        self.cursor.execute('SELECT type, url FROM art WHERE media_id=? AND media_type=?',
                            (kodi_id, kodi_type))
        return dict(self.cursor.fetchall())

    @common.catch_operationalerrors
    def modify_streams(self, fileid, streamdetails=None, runtime=None):
        """
        Leave streamdetails and runtime empty to delete all stream entries for
        fileid
        """
        # First remove any existing entries
        self.cursor.execute('DELETE FROM streamdetails WHERE idFile = ?',
                            (fileid,))
        if not streamdetails:
            return
        for videotrack in streamdetails['video']:
            self.cursor.execute('''
                INSERT OR REPLACE INTO streamdetails(
                    idFile, iStreamType, strVideoCodec, fVideoAspect,
                    iVideoWidth, iVideoHeight, iVideoDuration ,strStereoMode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (fileid, 0, videotrack['codec'],
                      videotrack['aspect'], videotrack['width'],
                      videotrack['height'], runtime,
                      videotrack['video3DFormat']))
        for audiotrack in streamdetails['audio']:
            self.cursor.execute('''
                INSERT OR REPLACE INTO streamdetails(
                    idFile, iStreamType, strAudioCodec, iAudioChannels,
                    strAudioLanguage)
                VALUES (?, ?, ?, ?, ?)
            ''', (fileid, 1, audiotrack['codec'],
                  audiotrack['channels'],
                  audiotrack['language']))
        for subtitletrack in streamdetails['subtitle']:
            self.cursor.execute('''
                INSERT OR REPLACE INTO streamdetails(idFile, iStreamType,
                    strSubtitleLanguage)
                VALUES (?, ?, ?)
            ''', (fileid, 2, subtitletrack))

    def video_id_from_filename(self, filename, path):
        """
        Returns the tuple (itemId, type) where
            itemId:     Kodi DB unique Id for either movie or episode
            type:       either 'movie' or 'episode'

        Returns None if not found OR if too many entries were found
        """
        self.cursor.execute('SELECT idFile, idPath FROM files WHERE strFilename = ?',
                            (filename,))
        files = self.cursor.fetchall()
        if len(files) == 0:
            LOG.debug('Did not find any file, abort')
            return
        # result will contain a list of all idFile with matching filename and
        # matching path
        result = []
        for file in files:
            # Use idPath to get path as a string
            self.cursor.execute('SELECT strPath FROM path WHERE idPath = ?',
                                (file[1], ))
            try:
                path_str = self.cursor.fetchone()[0]
            except TypeError:
                # idPath not found; skip
                continue
            # For whatever reason, double might have become triple
            path_str = path_str.replace('///', '//').replace('\\\\\\', '\\\\')
            if path_str == path:
                result.append(file[0])
        if len(result) == 0:
            LOG.info('Did not find matching paths, abort')
            return
        # Kodi seems to make ONE temporary entry; we only want the earlier,
        # permanent one
        if len(result) > 2:
            LOG.warn('We found too many items with matching filenames and '
                     ' paths, aborting')
            return
        file_id = result[0]

        # Try movies first
        self.cursor.execute('SELECT idMovie FROM movie WHERE idFile = ?',
                            (file_id, ))
        try:
            movie_id = self.cursor.fetchone()[0]
            typus = v.KODI_TYPE_MOVIE
        except TypeError:
            # Try tv shows next
            self.cursor.execute('SELECT idEpisode FROM episode WHERE idFile = ?',
                                (file_id, ))
            try:
                movie_id = self.cursor.fetchone()[0]
                typus = v.KODI_TYPE_EPISODE
            except TypeError:
                LOG.debug('Did not find a video DB match')
                return
        return movie_id, typus

    def get_resume(self, file_id):
        """
        Returns the first resume point in seconds (int) if found, else None for
        the Kodi file_id provided
        """
        self.cursor.execute('SELECT timeInSeconds FROM bookmark WHERE idFile = ? LIMIT 1',
                            (file_id,))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    def get_playcount(self, file_id):
        """
        Returns the playcount for the item file_id or None if not found
        """
        self.cursor.execute('SELECT playCount FROM files WHERE idFile = ? LIMIT 1',
                            (file_id, ))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    @common.catch_operationalerrors
    def set_resume(self, file_id, resume_seconds, total_seconds, playcount,
                   dateplayed):
        """
        Adds a resume marker for a video library item. Will even set 2,
        considering add-on path widget hacks.
        """
        # Delete existing resume point
        self.cursor.execute('DELETE FROM bookmark WHERE idFile = ?', (file_id,))
        # Set watched count
        self.cursor.execute('UPDATE files SET playCount = ?, lastPlayed = ? WHERE idFile = ?',
                            (playcount, dateplayed, file_id))
        # Set the resume bookmark
        if resume_seconds:
            self.cursor.execute(
                'SELECT COALESCE(MAX(idBookmark), 0) FROM bookmark')
            bookmark_id = self.cursor.fetchone()[0] + 1
            self.cursor.execute('''
            INSERT INTO bookmark(
                idBookmark,
                idFile,
                timeInSeconds,
                totalTimeInSeconds,
                thumbNailImage,
                player,
                playerState,
                type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (bookmark_id,
                  file_id,
                  resume_seconds,
                  total_seconds,
                  '',
                  'VideoPlayer',
                  '',
                  1))

    @common.catch_operationalerrors
    def create_tag(self, name):
        """
        Will create a new tag if needed and return the tag_id
        """
        self.cursor.execute('SELECT tag_id FROM tag WHERE name = ? COLLATE NOCASE',
                            (name,))
        try:
            tag_id = self.cursor.fetchone()[0]
        except TypeError:
            self.cursor.execute("SELECT COALESCE(MAX(tag_id), 0) FROM tag")
            tag_id = self.cursor.fetchone()[0] + 1
            self.cursor.execute('INSERT INTO tag(tag_id, name) VALUES(?, ?)',
                                (tag_id, name))
        return tag_id

    @common.catch_operationalerrors
    def update_tag(self, oldtag, newtag, kodiid, mediatype):
        """
        Updates the tag_id by replaying oldtag with newtag
        """
        try:
            self.cursor.execute('''
                UPDATE tag_link
                SET tag_id = ?
                WHERE media_id = ? AND media_type = ? AND tag_id = ?
            ''', (newtag, kodiid, mediatype, oldtag,))
        except Exception:
            # The new tag we are going to apply already exists for this item
            # delete current tag instead
            self.cursor.execute('''
                DELETE FROM tag_link
                WHERE media_id = ? AND media_type = ? AND tag_id = ?
            ''', (kodiid, mediatype, oldtag,))

    @common.catch_operationalerrors
    def create_collection(self, set_name):
        """
        Returns the collection/set id for set_name [unicode]
        """
        self.cursor.execute('SELECT idSet FROM sets WHERE strSet = ? COLLATE NOCASE',
                            (set_name,))
        try:
            setid = self.cursor.fetchone()[0]
        except TypeError:
            self.cursor.execute("SELECT COALESCE(MAX(idSet), 0) FROM sets")
            setid = self.cursor.fetchone()[0] + 1
            self.cursor.execute('INSERT INTO sets(idSet, strSet) VALUES(?, ?)',
                                (setid, set_name))
        return setid

    @common.catch_operationalerrors
    def assign_collection(self, setid, movieid):
        """
        Assign the movie to one set/collection
        """
        self.cursor.execute('UPDATE movie SET idSet = ? WHERE idMovie = ?',
                            (setid, movieid,))

    @common.catch_operationalerrors
    def remove_from_set(self, movieid):
        """
        Remove the movie with movieid [int] from an associated movie set, movie
        collection
        """
        self.cursor.execute('UPDATE movie SET idSet = null WHERE idMovie = ?',
                            (movieid,))

    def get_set_id(self, kodi_id):
        """
        Returns the set_id for the movie with kodi_id or None
        """
        self.cursor.execute('SELECT idSet FROM movie WHERE idMovie = ?',
                            (kodi_id, ))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            pass

    @common.catch_operationalerrors
    def delete_possibly_empty_set(self, set_id):
        """
        Checks whether there are other movies in the set set_id. If not,
        deletes the set
        """
        self.cursor.execute('SELECT idSet FROM movie WHERE idSet = ?',
                            (set_id, ))
        if self.cursor.fetchone() is None:
            self.cursor.execute('DELETE FROM sets WHERE idSet = ?', (set_id,))

    @common.catch_operationalerrors
    def add_season(self, showid, seasonnumber):
        """
        Adds a TV show season to the Kodi video DB or simply returns the ID,
        if there already is an entry in the DB
        """
        self.cursor.execute("SELECT COALESCE(MAX(idSeason),0) FROM seasons")
        seasonid = self.cursor.fetchone()[0] + 1
        self.cursor.execute('''
            INSERT INTO seasons(idSeason, idShow, season)
            VALUES (?, ?, ?)
        ''', (seasonid, showid, seasonnumber))
        return seasonid

    @common.catch_operationalerrors
    def add_uniqueid(self, *args):
        """
        Feed with:
            uniqueid_id: int
            media_id: int
            media_type: string
            value: string
            type: e.g. 'imdb' or 'tvdb'
        """
        self.cursor.execute('''
            INSERT INTO uniqueid(
                uniqueid_id,
                media_id,
                media_type,
                value,
                type)
            VALUES (?, ?, ?, ?, ?)
        ''', (args))

    def add_uniqueid_id(self):
        self.cursor.execute('SELECT COALESCE(MAX(uniqueid_id), 0) FROM uniqueid')
        return self.cursor.fetchone()[0] + 1

    def get_uniqueid(self, kodi_id, kodi_type):
        """
        Returns the uniqueid_id
        """
        self.cursor.execute('SELECT uniqueid_id FROM uniqueid WHERE media_id = ? AND media_type =?',
                            (kodi_id, kodi_type))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            return self.add_uniqueid_id()

    @common.catch_operationalerrors
    def update_uniqueid(self, *args):
        """
        Pass in media_id, media_type, value, type, uniqueid_id
        """
        self.cursor.execute('''
            UPDATE uniqueid
            SET media_id = ?, media_type = ?, value = ?, type = ?
            WHERE uniqueid_id = ?
        ''', (args))

    @common.catch_operationalerrors
    def remove_uniqueid(self, kodi_id, kodi_type):
        """
        Deletes the entry from the uniqueid table for the item
        """
        self.cursor.execute('DELETE FROM uniqueid WHERE media_id = ? AND media_type = ?',
                            (kodi_id, kodi_type))

    def add_ratingid(self):
        self.cursor.execute('SELECT COALESCE(MAX(rating_id),0) FROM rating')
        return self.cursor.fetchone()[0] + 1

    def get_ratingid(self, kodi_id, kodi_type):
        """
        Create if needed and return the unique rating_id from rating table
        """
        self.cursor.execute('SELECT rating_id FROM rating WHERE media_id = ? AND media_type = ?',
                            (kodi_id, kodi_type))
        try:
            return self.cursor.fetchone()[0]
        except TypeError:
            return self.add_ratingid()

    @common.catch_operationalerrors
    def update_ratings(self, *args):
        """
        Feed with media_id, media_type, rating_type, rating, votes, rating_id
        """
        self.cursor.execute('''
            UPDATE rating
            SET media_id = ?,
                media_type = ?,
                rating_type = ?,
                rating = ?,
                votes = ?
            WHERE rating_id = ?
        ''', (args))

    @common.catch_operationalerrors
    def add_ratings(self, *args):
        """
        feed with:
            rating_id, media_id, media_type, rating_type, rating, votes

        rating_type = 'default'
        """
        self.cursor.execute('''
            INSERT INTO rating(
                rating_id,
                media_id,
                media_type,
                rating_type,
                rating,
                votes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (args))

    @common.catch_operationalerrors
    def remove_ratings(self, kodi_id, kodi_type):
        """
        Removes all ratings from the rating table for the item
        """
        self.cursor.execute('DELETE FROM rating WHERE media_id = ? AND media_type = ?',
                            (kodi_id, kodi_type))

    def new_show_id(self):
        self.cursor.execute('SELECT COALESCE(MAX(idShow), 0) FROM tvshow')
        return self.cursor.fetchone()[0] + 1

    def new_episode_id(self):
        self.cursor.execute('SELECT COALESCE(MAX(idEpisode), 0) FROM episode')
        return self.cursor.fetchone()[0] + 1

    @common.catch_operationalerrors
    def add_episode(self, *args):
        self.cursor.execute(
            '''
                INSERT INTO episode(
                    idEpisode,
                    idFile,
                    c00,
                    c01,
                    c03,
                    c04,
                    c05,
                    c09,
                    c10,
                    c12,
                    c13,
                    c14,
                    idShow,
                    c15,
                    c16,
                    c18,
                    c19,
                    idSeason,
                    userrating)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (args))

    @common.catch_operationalerrors
    def update_episode(self, *args):
        self.cursor.execute(
            '''
                UPDATE episode
                SET c00 = ?,
                    c01 = ?,
                    c03 = ?,
                    c04 = ?,
                    c05 = ?,
                    c09 = ?,
                    c10 = ?,
                    c12 = ?,
                    c13 = ?,
                    c14 = ?,
                    c15 = ?,
                    c16 = ?,
                    c18 = ?,
                    c19 = ?,
                    idFile=?,
                    idSeason = ?,
                    userrating = ?
                WHERE idEpisode = ?
            ''', (args))

    @common.catch_operationalerrors
    def add_show(self, *args):
        self.cursor.execute(
            '''
                INSERT INTO tvshow(
                    idShow,
                    c00,
                    c01,
                    c04,
                    c05,
                    c08,
                    c09,
                    c12,
                    c13,
                    c14,
                    c15)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (args))

    @common.catch_operationalerrors
    def update_show(self, *args):
        self.cursor.execute(
            '''
                UPDATE tvshow
                SET c00 = ?,
                    c01 = ?,
                    c04 = ?,
                    c05 = ?,
                    c08 = ?,
                    c09 = ?,
                    c12 = ?,
                    c13 = ?,
                    c14 = ?,
                    c15 = ?
                WHERE idShow = ?
            ''', (args))

    @common.catch_operationalerrors
    def add_showlinkpath(self, kodi_id, kodi_pathid):
        self.cursor.execute('INSERT INTO tvshowlinkpath(idShow, idPath) VALUES (?, ?)',
                            (kodi_id, kodi_pathid))

    @common.catch_operationalerrors
    def remove_show(self, kodi_id):
        self.cursor.execute('DELETE FROM tvshow WHERE idShow = ?', (kodi_id,))

    @common.catch_operationalerrors
    def remove_season(self, kodi_id):
        self.cursor.execute('DELETE FROM seasons WHERE idSeason = ?',
                            (kodi_id,))

    @common.catch_operationalerrors
    def remove_episode(self, kodi_id):
        self.cursor.execute('DELETE FROM episode WHERE idEpisode = ?',
                            (kodi_id,))

    def new_movie_id(self):
        self.cursor.execute('SELECT COALESCE(MAX(idMovie), 0) FROM movie')
        return self.cursor.fetchone()[0] + 1

    @common.catch_operationalerrors
    def add_movie(self, *args):
        self.cursor.execute(
            '''
            INSERT OR REPLACE INTO movie(
                idMovie,
                idFile,
                c00,
                c01,
                c02,
                c03,
                c04,
                c05,
                c06,
                c07,
                c09,
                c10,
                c11,
                c12,
                c14,
                c15,
                c16,
                c18,
                c19,
                c21,
                c22,
                c23,
                premiered,
                userrating)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                 ?, ?, ?, ?)
        ''', (args))

    @common.catch_operationalerrors
    def remove_movie(self, kodi_id):
        self.cursor.execute('DELETE FROM movie WHERE idMovie = ?', (kodi_id,))

    @common.catch_operationalerrors
    def update_userrating(self, kodi_id, kodi_type, userrating):
        """
        Updates userrating
        """
        if kodi_type == v.KODI_TYPE_MOVIE:
            table = kodi_type
            identifier = 'idMovie'
        elif kodi_type == v.KODI_TYPE_EPISODE:
            table = kodi_type
            identifier = 'idEpisode'
        elif kodi_type == v.KODI_TYPE_SEASON:
            table = 'seasons'
            identifier = 'idSeason'
        elif kodi_type == v.KODI_TYPE_SHOW:
            table = kodi_type
            identifier = 'idShow'
        self.cursor.execute('''UPDATE %s SET userrating = ? WHERE ? = ?''' % table,
                            (userrating, identifier, kodi_id))
