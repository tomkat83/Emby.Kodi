# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
from Queue import Empty
import xbmc

from ..plex_api import API
from .. import utils, plexdb_functions as plexdb, kodidb_functions as kodidb
from .. import itemtypes, artwork, plex_functions as PF, variables as v, state

###############################################################################

LOG = getLogger("PLEX." + __name__)

###############################################################################


@utils.thread_methods(add_suspends=['SUSPEND_LIBRARY_THREAD',
                                    'DB_SCAN',
                                    'STOP_SYNC',
                                    'SUSPEND_SYNC'])
class ThreadedProcessFanart(Thread):
    """
    Threaded download of additional fanart in the background

    Input:
        queue           Queue.Queue() object that you will need to fill with
                        dicts of the following form:
            {
              'plex_id':                the Plex id as a string
              'plex_type':              the Plex media type, e.g. 'movie'
              'refresh': True/False     if True, will overwrite any 3rd party
                                        fanart. If False, will only get missing
            }
    """
    def __init__(self, queue):
        self.queue = queue
        Thread.__init__(self)

    def run(self):
        """
        Do the work
        """
        LOG.debug("---===### Starting FanartSync ###===---")
        while not self.stopped():
            # In the event the server goes offline
            while self.suspended():
                # Set in service.py
                if self.stopped():
                    # Abort was requested while waiting. We should exit
                    LOG.debug("---===### Stopped FanartSync ###===---")
                    return
                xbmc.sleep(1000)
            # grabs Plex item from queue
            try:
                item = self.queue.get(block=False)
            except Empty:
                xbmc.sleep(200)
                continue
            self.queue.task_done()
            if isinstance(item, artwork.ArtworkSyncMessage):
                if state.IMAGE_SYNC_NOTIFICATIONS:
                    utils.dialog('notification',
                                 heading=utils.lang(29999),
                                 message=item.message,
                                 icon='{plex}',
                                 sound=False)
                continue
            LOG.debug('Get additional fanart for Plex id %s', item['plex_id'])
            _process(item)
        LOG.debug("---===### Stopped FanartSync ###===---")


def _process(item):
    done = False
    try:
        artworks = None
        with plexdb.Get_Plex_DB() as plex_db:
            db_item = plex_db.getItem_byId(item['plex_id'])
        try:
            kodi_id = db_item[0]
            kodi_type = db_item[4]
        except TypeError:
            LOG.error('Could not get Kodi id for plex id %s, abort getfanart',
                      item['plex_id'])
            return
        if item['refresh'] is False:
            with kodidb.GetKodiDB('video') as kodi_db:
                artworks = kodi_db.get_art(kodi_id, kodi_type)
            # Check if we even need to get additional art
            for key in v.ALL_KODI_ARTWORK:
                if key not in artworks:
                    break
            else:
                LOG.debug('Already got all fanart for Plex id %s',
                          item['plex_id'])
                done = True
                return
        xml = PF.GetPlexMetadata(item['plex_id'])
        if xml is None:
            LOG.error('Could not get metadata for %s. Skipping that item '
                      'for now', item['plex_id'])
            return
        elif xml == 401:
            LOG.error('HTTP 401 returned by PMS. Too much strain? '
                      'Cancelling sync for now')
            return
        api = API(xml[0])
        if artworks is None:
            artworks = api.artwork()
        # Get additional missing artwork from fanart artwork sites
        artworks = api.fanart_artwork(artworks)
        with getattr(itemtypes,
                     v.ITEMTYPE_FROM_PLEXTYPE[item['plex_type']])() as itm:
            itm.set_fanart(artworks, kodi_id, kodi_type)
        # Additional fanart for sets/collections
        if api.plex_type() == v.PLEX_TYPE_MOVIE:
            for _, setname in api.collection_list():
                LOG.debug('Getting artwork for movie set %s', setname)
                with kodidb.GetKodiDB('video') as kodi_db:
                    setid = kodi_db.create_collection(setname)
                external_set_artwork = api.set_artwork()
                if (external_set_artwork and
                        utils.settings('PreferKodiCollectionArt') == 'false'):
                    kodi_artwork = api.artwork(kodi_id=setid,
                                               kodi_type=v.KODI_TYPE_SET)
                    for art in kodi_artwork:
                        if art in external_set_artwork:
                            del external_set_artwork[art]
                with itemtypes.Movies() as movie_db:
                    movie_db.artwork.modify_artwork(external_set_artwork,
                                                    setid,
                                                    v.KODI_TYPE_SET,
                                                    movie_db.kodicursor)
        done = True
    finally:
        if done is True:
            LOG.debug('Done getting fanart for Plex id %s', item['plex_id'])
            with plexdb.Get_Plex_DB() as plex_db:
                plex_db.set_fanart_synched(item['plex_id'])
