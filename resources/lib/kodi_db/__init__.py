#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

from .common import KODIDB_LOCK
from .video import KodiVideoDB
from .music import KodiMusicDB
from .texture import KodiTextureDB

from .. import path_ops, utils, variables as v

LOG = getLogger('PLEX.kodi_db')


def kodiid_from_filename(path, kodi_type=None, db_type=None):
    """
    Returns kodi_id if we have an item in the Kodi video or audio database with
    said path. Feed with either koditype, e.v. 'movie', 'song' or the DB
    you want to poll ('video' or 'music')
    Returns None, <kodi_type> if not possible
    """
    kodi_id = None
    # Make sure path ends in either '/' or '\'
    # We CANNOT use path_ops.path.join as this can result in \ where we need /
    try:
        filename = path.rsplit('/', 1)[1]
        path = path.rsplit('/', 1)[0] + '/'
    except IndexError:
        filename = path.rsplit('\\', 1)[1]
        path = path.rsplit('\\', 1)[0] + '\\'
    if kodi_type == v.KODI_TYPE_SONG or db_type == 'music':
        with KodiMusicDB(lock=False) as kodidb:
            try:
                kodi_id = kodidb.song_id_from_filename(filename, path)
            except TypeError:
                LOG.debug('No Kodi audio db element found for path %s', path)
            else:
                kodi_type = v.KODI_TYPE_SONG
    else:
        with KodiVideoDB(lock=False) as kodidb:
            try:
                kodi_id, kodi_type = kodidb.video_id_from_filename(filename,
                                                                   path)
            except TypeError:
                LOG.debug('No kodi video db element found for path %s file %s',
                          path, filename)
    return kodi_id, kodi_type


def setup_kodi_default_entries():
    """
    Makes sure that we retain the Kodi standard databases. E.g. that there
    is a dummy artist with ID 1
    """
    if utils.settings('enableMusic') == 'true':
        with KodiMusicDB() as kodidb:
            kodidb.setup_kodi_default_entries()


def reset_cached_images():
    LOG.info('Resetting cached artwork')
    LOG.debug('Resetting the Kodi texture DB')
    with KodiTextureDB() as kodidb:
        kodidb.wipe()
    LOG.debug('Deleting all cached image files')
    path = path_ops.translate_path('special://thumbnails/')
    if path_ops.exists(path):
        path_ops.rmtree(path, ignore_errors=True)
        paths = ('', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                 'a', 'b', 'c', 'd', 'e', 'f',
                 'Video', 'plex')
        for path in paths:
            new_path = path_ops.translate_path('special://thumbnails/%s' % path)
            try:
                path_ops.makedirs(new_path)
            except OSError as err:
                LOG.warn('Could not create thumbnail directory %s: %s',
                         new_path, err)
    LOG.info('Done resetting cached artwork')


def wipe_dbs(music=True):
    """
    Completely resets the Kodi databases 'video', 'texture' and 'music' (if
    music sync is enabled)

    We need to connect without sqlite WAL mode as Kodi might still be accessing
    the dbs and we need to prevent that
    """
    LOG.warn('Wiping Kodi databases!')
    LOG.info('Wiping Kodi video database')
    with KodiVideoDB() as kodidb:
        kodidb.wipe()
    if music:
        LOG.info('Wiping Kodi music database')
        with KodiMusicDB() as kodidb:
            kodidb.wipe()
    reset_cached_images()
    setup_kodi_default_entries()
    # Delete SQLITE wal files
    import xbmc
    # Make sure Kodi knows we wiped the databases
    xbmc.executebuiltin('UpdateLibrary(video)')
    if utils.settings('enableMusic') == 'true':
        xbmc.executebuiltin('UpdateLibrary(music)')


def create_kodi_db_indicees():
    """
    Index the "actors" because we got a TON - speed up SELECT and WHEN
    """
    with KodiVideoDB() as kodidb:
        kodidb.create_kodi_db_indicees()


KODIDB_FROM_PLEXTYPE = {
    v.PLEX_TYPE_MOVIE: KodiVideoDB,
    v.PLEX_TYPE_SHOW: KodiVideoDB,
    v.PLEX_TYPE_SEASON: KodiVideoDB,
    v.PLEX_TYPE_EPISODE: KodiVideoDB,
    v.PLEX_TYPE_ARTIST: KodiMusicDB,
    v.PLEX_TYPE_ALBUM: KodiMusicDB,
    v.PLEX_TYPE_SONG: KodiMusicDB
}
