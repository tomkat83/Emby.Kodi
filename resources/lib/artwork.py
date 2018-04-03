# -*- coding: utf-8 -*-

###############################################################################
from logging import getLogger
from Queue import Queue, Empty
from shutil import rmtree
from urllib import quote_plus, unquote
from threading import Thread
from os import makedirs
import requests

from xbmc import sleep, translatePath
from xbmcvfs import exists

from utils import window, settings, language as lang, kodi_sql, try_encode, \
    thread_methods, dialog, exists_dir, try_decode
import state

###############################################################################
LOG = getLogger("PLEX." + __name__)

# Disable annoying requests warnings
requests.packages.urllib3.disable_warnings()
ARTWORK_QUEUE = Queue()
###############################################################################


def double_urlencode(text):
    return quote_plus(quote_plus(text))


def double_urldecode(text):
    return unquote(unquote(text))


@thread_methods(add_suspends=['SUSPEND_LIBRARY_THREAD',
                              'DB_SCAN',
                              'STOP_SYNC'])
class Image_Cache_Thread(Thread):
    sleep_between = 50
    # Potentially issues with limited number of threads
    # Hence let Kodi wait till download is successful
    timeout = (35.1, 35.1)

    def __init__(self):
        self.queue = ARTWORK_QUEUE
        Thread.__init__(self)

    def run(self):
        stopped = self.stopped
        suspended = self.suspended
        queue = self.queue
        sleep_between = self.sleep_between
        while not stopped():
            # In the event the server goes offline
            while suspended():
                # Set in service.py
                if stopped():
                    # Abort was requested while waiting. We should exit
                    LOG.info("---===### Stopped Image_Cache_Thread ###===---")
                    return
                sleep(1000)
            try:
                url = queue.get(block=False)
            except Empty:
                sleep(1000)
                continue
            sleeptime = 0
            while True:
                try:
                    requests.head(
                        url="http://%s:%s/image/image://%s"
                            % (state.WEBSERVER_HOST,
                               state.WEBSERVER_PORT,
                               url),
                        auth=(state.WEBSERVER_USERNAME,
                              state.WEBSERVER_PASSWORD),
                        timeout=self.timeout)
                except requests.Timeout:
                    # We don't need the result, only trigger Kodi to start the
                    # download. All is well
                    break
                except requests.ConnectionError:
                    if stopped():
                        # Kodi terminated
                        break
                    # Server thinks its a DOS attack, ('error 10053')
                    # Wait before trying again
                    if sleeptime > 5:
                        LOG.error('Repeatedly got ConnectionError for url %s',
                                  double_urldecode(url))
                        break
                    LOG.debug('Were trying too hard to download art, server '
                              'over-loaded. Sleep %s seconds before trying '
                              'again to download %s',
                              2**sleeptime, double_urldecode(url))
                    sleep((2**sleeptime)*1000)
                    sleeptime += 1
                    continue
                except Exception as e:
                    LOG.error('Unknown exception for url %s: %s'.
                              double_urldecode(url), e)
                    import traceback
                    LOG.error("Traceback:\n%s", traceback.format_exc())
                    break
                # We did not even get a timeout
                break
            queue.task_done()
            # Sleep for a bit to reduce CPU strain
            sleep(sleep_between)
        LOG.info("---===### Stopped Image_Cache_Thread ###===---")


class Artwork():
    enableTextureCache = settings('enableTextureCache') == "true"
    if enableTextureCache:
        queue = ARTWORK_QUEUE

    def fullTextureCacheSync(self):
        """
        This method will sync all Kodi artwork to textures13.db
        and cache them locally. This takes diskspace!
        """
        if not dialog('yesno', "Image Texture Cache", lang(39250)):
            return

        LOG.info("Doing Image Cache Sync")

        # ask to rest all existing or not
        if dialog('yesno', "Image Texture Cache", lang(39251)):
            LOG.info("Resetting all cache data first")
            # Remove all existing textures first
            path = try_decode(translatePath("special://thumbnails/"))
            if exists_dir(path):
                rmtree(path, ignore_errors=True)
                self.restore_cache_directories()

            # remove all existing data from texture DB
            connection = kodi_sql('texture')
            cursor = connection.cursor()
            query = 'SELECT tbl_name FROM sqlite_master WHERE type=?'
            cursor.execute(query, ('table', ))
            rows = cursor.fetchall()
            for row in rows:
                tableName = row[0]
                if tableName != "version":
                    cursor.execute("DELETE FROM %s" % tableName)
            connection.commit()
            connection.close()

        # Cache all entries in video DB
        connection = kodi_sql('video')
        cursor = connection.cursor()
        # dont include actors
        query = "SELECT url FROM art WHERE media_type != ?"
        cursor.execute(query, ('actor', ))
        result = cursor.fetchall()
        total = len(result)
        LOG.info("Image cache sync about to process %s video images", total)
        connection.close()

        for url in result:
            self.cache_texture(url[0])
        # Cache all entries in music DB
        connection = kodi_sql('music')
        cursor = connection.cursor()
        cursor.execute("SELECT url FROM art")
        result = cursor.fetchall()
        total = len(result)
        LOG.info("Image cache sync about to process %s music images", total)
        connection.close()
        for url in result:
            self.cache_texture(url[0])

    def cache_texture(self, url):
        '''
        Cache a single image url to the texture cache
        '''
        if url and self.enableTextureCache:
            self.queue.put(double_urlencode(try_encode(url)))

    def modify_artwork(self, artworks, kodi_id, kodi_type, cursor):
        """
        Pass in an artworks dict (see PlexAPI) to set an items artwork.
        """
        for kodi_art, url in artworks.iteritems():
            self.modify_art(url, kodi_id, kodi_type, kodi_art, cursor)

    def modify_art(self, url, kodi_id, kodi_type, kodi_art, cursor):
        """
        Adds or modifies the artwork of kind kodi_art (e.g. 'poster') in the
        Kodi art table for item kodi_id/kodi_type. Will also cache everything
        except actor portraits.
        """
        query = '''
            SELECT url FROM art
            WHERE media_id = ? AND media_type = ? AND type = ?
            LIMIT 1
        '''
        cursor.execute(query, (kodi_id, kodi_type, kodi_art,))
        try:
            # Update the artwork
            old_url = cursor.fetchone()[0]
        except TypeError:
            # Add the artwork
            LOG.debug('Adding Art Link for %s kodi_id %s, kodi_type %s: %s',
                      kodi_art, kodi_id, kodi_type, url)
            query = '''
                INSERT INTO art(media_id, media_type, type, url)
                VALUES (?, ?, ?, ?)
            '''
            cursor.execute(query, (kodi_id, kodi_type, kodi_art, url))
        else:
            if url == old_url:
                # Only cache artwork if it changed
                return
            self.delete_cached_artwork(old_url)
            LOG.debug("Updating Art url for %s kodi_id %s, kodi_type %s to %s",
                      kodi_art, kodi_id, kodi_type, url)
            query = '''
                UPDATE art SET url = ?
                WHERE media_id = ? AND media_type = ? AND type = ?
            '''
            cursor.execute(query, (url, kodi_id, kodi_type, kodi_art))
        # Cache fanart and poster in Kodi texture cache
        if kodi_type != 'actor':
            self.cache_texture(url)

    def delete_artwork(self, kodiId, mediaType, cursor):
        query = 'SELECT url FROM art WHERE media_id = ? AND media_type = ?'
        cursor.execute(query, (kodiId, mediaType,))
        for row in cursor.fetchall():
            self.delete_cached_artwork(row[0])

    @staticmethod
    def delete_cached_artwork(url):
        """
        Deleted the cached artwork with path url (if it exists)
        """
        connection = kodi_sql('texture')
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT cachedurl FROM texture WHERE url=? LIMIT 1",
                           (url,))
            cachedurl = cursor.fetchone()[0]
        except TypeError:
            # Could not find cached url
            pass
        else:
            # Delete thumbnail as well as the entry
            path = translatePath("special://thumbnails/%s" % cachedurl)
            LOG.debug("Deleting cached thumbnail: %s", path)
            if exists(path):
                rmtree(try_decode(path), ignore_errors=True)
            cursor.execute("DELETE FROM texture WHERE url = ?", (url,))
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def restore_cache_directories():
        LOG.info("Restoring cache directories...")
        paths = ("", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                 "a", "b", "c", "d", "e", "f",
                 "Video", "plex")
        for path in paths:
            makedirs(try_decode(translatePath("special://thumbnails/%s"
                                              % path)))
