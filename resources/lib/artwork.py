#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from Queue import Queue, Empty
from urllib import quote_plus, unquote
from threading import Thread
import requests

import xbmc

from . import path_ops
from . import utils
from . import state

###############################################################################
LOG = getLogger('PLEX.artwork')

# Disable annoying requests warnings
requests.packages.urllib3.disable_warnings()
ARTWORK_QUEUE = Queue()
IMAGE_CACHING_SUSPENDS = ['SUSPEND_LIBRARY_THREAD', 'DB_SCAN', 'STOP_SYNC']
if not utils.settings('imageSyncDuringPlayback') == 'true':
    IMAGE_CACHING_SUSPENDS.append('SUSPEND_SYNC')

###############################################################################


def double_urlencode(text):
    return quote_plus(quote_plus(text))


def double_urldecode(text):
    return unquote(unquote(text))


@utils.thread_methods(add_suspends=IMAGE_CACHING_SUSPENDS)
class Image_Cache_Thread(Thread):
    sleep_between = 50
    # Potentially issues with limited number of threads
    # Hence let Kodi wait till download is successful
    timeout = (35.1, 35.1)

    def __init__(self):
        self.queue = ARTWORK_QUEUE
        Thread.__init__(self)

    def run(self):
        LOG.info("---===### Starting Image_Cache_Thread ###===---")
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
                xbmc.sleep(1000)

            try:
                url = queue.get(block=False)
            except Empty:
                xbmc.sleep(1000)
                continue
            if isinstance(url, ArtworkSyncMessage):
                if state.IMAGE_SYNC_NOTIFICATIONS:
                    utils.dialog('notification',
                                 heading=utils.lang(29999),
                                 message=url.message,
                                 icon='{plex}',
                                 sound=False)
                queue.task_done()
                continue
            url = double_urlencode(utils.try_encode(url))
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
                    xbmc.sleep((2**sleeptime) * 1000)
                    sleeptime += 1
                    continue
                except Exception as err:
                    LOG.error('Unknown exception for url %s: %s'.
                              double_urldecode(url), err)
                    import traceback
                    LOG.error("Traceback:\n%s", traceback.format_exc())
                    break
                # We did not even get a timeout
                break
            queue.task_done()
            # Sleep for a bit to reduce CPU strain
            xbmc.sleep(sleep_between)
        LOG.info("---===### Stopped Image_Cache_Thread ###===---")


class Artwork():
    enableTextureCache = utils.settings('enableTextureCache') == "true"
    if enableTextureCache:
        queue = ARTWORK_QUEUE

    def cache_major_artwork(self):
        """
        Takes the existing Kodi library and caches posters and fanart.
        Necessary because otherwise PKC caches artwork e.g. from fanart.tv
        which basically blocks Kodi from getting needed artwork fast (e.g.
        while browsing the library)
        """
        if not self.enableTextureCache:
            return
        artworks = list()
        # Get all posters and fanart/background for video and music
        for kind in ('video', 'music'):
            connection = utils.kodi_sql(kind)
            cursor = connection.cursor()
            for typus in ('poster', 'fanart'):
                cursor.execute('SELECT url FROM art WHERE type == ?',
                               (typus, ))
                artworks.extend(cursor.fetchall())
            connection.close()
        artworks_to_cache = list()
        connection = utils.kodi_sql('texture')
        cursor = connection.cursor()
        for url in artworks:
            query = 'SELECT url FROM texture WHERE url == ? LIMIT 1'
            cursor.execute(query, (url[0], ))
            if not cursor.fetchone():
                artworks_to_cache.append(url)
        connection.close()
        if not artworks_to_cache:
            LOG.info('Caching of major images to Kodi texture cache done')
            return
        length = len(artworks_to_cache)
        LOG.info('Caching has not been completed - caching %s major images',
                 length)
        # Caching %s Plex images
        self.queue.put(ArtworkSyncMessage(utils.lang(30006) % length))
        for url in artworks_to_cache:
            self.queue.put(url[0])
        # Plex image caching done
        self.queue.put(ArtworkSyncMessage(utils.lang(30007)))

    def fullTextureCacheSync(self):
        """
        This method will sync all Kodi artwork to textures13.db
        and cache them locally. This takes diskspace!
        """
        if not utils.yesno_dialog("Image Texture Cache", utils.lang(39250)):
            return

        LOG.info("Doing Image Cache Sync")

        # ask to rest all existing or not
        if utils.yesno_dialog("Image Texture Cache", utils.lang(39251)):
            LOG.info("Resetting all cache data first")
            # Remove all existing textures first
            path = path_ops.translate_path('special://thumbnails/')
            if path_ops.exists(path):
                path_ops.rmtree(path, ignore_errors=True)
                self.restore_cache_directories()

            # remove all existing data from texture DB
            connection = utils.kodi_sql('texture')
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
        connection = utils.kodi_sql('video')
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
        connection = utils.kodi_sql('music')
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
        Cache a single image url to the texture cache. url: unicode
        '''
        if url and self.enableTextureCache:
            self.queue.put(url)

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
        connection = utils.kodi_sql('texture')
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
            path = path_ops.translate_path("special://thumbnails/%s"
                                           % cachedurl)
            LOG.debug("Deleting cached thumbnail: %s", path)
            if path_ops.exists(path):
                path_ops.rmtree(path, ignore_errors=True)
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
            new_path = path_ops.translate_path("special://thumbnails/%s" % path)
            path_ops.makedirs(path_ops.encode_path(new_path))


class ArtworkSyncMessage(object):
    """
    Put in artwork queue to display the message as a Kodi notification
    """
    def __init__(self, message):
        self.message = message
