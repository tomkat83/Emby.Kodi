# -*- coding: utf-8 -*-

from logging import getLogger

from ..plex_api import API
from ..plex_db import PlexDB
from ..kodi_db import KodiVideoDB
from .. import backgroundthread, utils
from .. import itemtypes, plex_functions as PF, variables as v, app


LOG = getLogger('PLEX.sync.fanart')

SUPPORTED_TYPES = (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_SHOW)
SYNC_FANART = (utils.settings('FanartTV') == 'true' and
               utils.settings('usePlexArtwork') == 'true')
PREFER_KODI_COLLECTION_ART = utils.settings('PreferKodiCollectionArt') == 'false'
BATCH_SIZE = 500


class FanartThread(backgroundthread.KillableThread):
    """
    This will potentially take hours!
    """
    def __init__(self, callback, refresh=False):
        self.callback = callback
        self.refresh = refresh
        super(FanartThread, self).__init__()

    def isSuspended(self):
        return self._suspended or app.APP.is_playing_video

    def run(self):
        LOG.info('Starting FanartThread')
        app.APP.register_fanart_thread(self)
        try:
            self._run_internal()
        except Exception:
            utils.ERROR(notify=True)
        finally:
            app.APP.deregister_fanart_thread(self)

    def _run_internal(self):
        finished = False
        try:
            for typus in SUPPORTED_TYPES:
                offset = 0
                while True:
                    with PlexDB() as plexdb:
                        # Keep DB connection open only for a short period of time!
                        if self.refresh:
                            batch = list(plexdb.every_plex_id(typus,
                                                              offset,
                                                              BATCH_SIZE))
                        else:
                            batch = list(plexdb.missing_fanart(typus,
                                                               offset,
                                                               BATCH_SIZE))
                    for plex_id in batch:
                        # Do the actual, time-consuming processing
                        if self.wait_while_suspended():
                            return
                        process_fanart(plex_id, typus, self.refresh)
                    if len(batch) < BATCH_SIZE:
                        break
                    offset += BATCH_SIZE
            else:
                finished = True
        finally:
            LOG.info('FanartThread finished: %s', finished)
            self.callback(finished)


class FanartTask(backgroundthread.Task):
    """
    This task will also be executed while library sync is suspended!
    """
    def setup(self, plex_id, plex_type, refresh=False):
        self.plex_id = plex_id
        self.plex_type = plex_type
        self.refresh = refresh

    def run(self):
        process_fanart(self.plex_id, self.plex_type, self.refresh)


def process_fanart(plex_id, plex_type, refresh=False):
    """
    Will look for additional fanart for the plex_type item with plex_id.
    Will check if we already got all artwork and only look if some are indeed
    missing.
    Will set the fanart_synced flag in the Plex DB if successful.
    """
    done = False
    try:
        artworks = None
        with PlexDB() as plexdb:
            db_item = plexdb.item_by_id(plex_id,
                                        plex_type)
        if not db_item:
            LOG.error('Could not get Kodi id for plex id %s', plex_id)
            return
        if not refresh:
            with KodiVideoDB() as kodidb:
                artworks = kodidb.get_art(db_item['kodi_id'],
                                          db_item['kodi_type'])
            # Check if we even need to get additional art
            for key in v.ALL_KODI_ARTWORK:
                if key not in artworks:
                    break
            else:
                done = True
                return
        xml = PF.GetPlexMetadata(plex_id)
        try:
            xml[0].attrib
        except (TypeError, IndexError, AttributeError):
            LOG.warn('Could not get metadata for %s. Skipping that item '
                     'for now', plex_id)
            return
        api = API(xml[0])
        if artworks is None:
            artworks = api.artwork()
        # Get additional missing artwork from fanart artwork sites
        artworks = api.fanart_artwork(artworks)
        with itemtypes.ITEMTYPE_FROM_PLEXTYPE[plex_type](None) as context:
            context.set_fanart(artworks,
                               db_item['kodi_id'],
                               db_item['kodi_type'])
        # Additional fanart for sets/collections
        if plex_type == v.PLEX_TYPE_MOVIE:
            for _, setname in api.collections():
                LOG.debug('Getting artwork for movie set %s', setname)
                with KodiVideoDB() as kodidb:
                    setid = kodidb.create_collection(setname)
                external_set_artwork = api.set_artwork()
                if external_set_artwork and PREFER_KODI_COLLECTION_ART:
                    kodi_artwork = api.artwork(kodi_id=setid,
                                               kodi_type=v.KODI_TYPE_SET)
                    for art in kodi_artwork:
                        if art in external_set_artwork:
                            del external_set_artwork[art]
                with itemtypes.Movie(None) as movie:
                    movie.kodidb.modify_artwork(external_set_artwork,
                                                setid,
                                                v.KODI_TYPE_SET)
        done = True
    finally:
        if done is True:
            with PlexDB() as plexdb:
                plexdb.set_fanart_synced(plex_id, plex_type)
