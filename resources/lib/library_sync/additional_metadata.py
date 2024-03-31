# -*- coding: utf-8 -*-
from logging import getLogger

from . import additional_metadata_tmdb
from ..plex_db import PlexDB
from .. import backgroundthread, utils
from .. import variables as v, app
from ..exceptions import ProcessingNotDone


logger = getLogger('PLEX.sync.metadata')

BATCH_SIZE = 500

SUPPORTED_METADATA = {
    v.PLEX_TYPE_MOVIE: (
        ('missing_trailers', additional_metadata_tmdb.process_trailers),
        ('missing_fanart', additional_metadata_tmdb.process_fanart),
    ),
    v.PLEX_TYPE_SHOW: (
        ('missing_fanart', additional_metadata_tmdb.process_fanart),
    ),
}


def processing_is_activated(item_getter):
    """Checks the PKC settings whether processing is even activated."""
    if item_getter == 'missing_fanart':
        return utils.settings('FanartTV') == 'true'
    return True


class MetadataThread(backgroundthread.KillableThread):
    """This will potentially take hours!"""
    def __init__(self, callback, refresh=False):
        self.callback = callback
        self.refresh = refresh
        super(MetadataThread, self).__init__()

    def should_suspend(self):
        return self._suspended or app.APP.is_playing_video

    def _process_in_batches(self, item_getter, processor, plex_type):
        offset = 0
        while True:
            with PlexDB(lock=False) as plexdb:
                # Keep DB connection open only for a short period of time!
                if self.refresh:
                    # Simply grab every single item if we want to refresh
                    func = plexdb.every_plex_id
                else:
                    func = getattr(plexdb, item_getter)
                batch = list(func(plex_type, offset, BATCH_SIZE))
            for plex_id in batch:
                # Do the actual, time-consuming processing
                if self.should_suspend() or self.should_cancel():
                    raise ProcessingNotDone()
                processor(plex_id, plex_type, self.refresh)
            if len(batch) < BATCH_SIZE:
                break
            offset += BATCH_SIZE

    def _loop(self):
        for plex_type in SUPPORTED_METADATA:
            for item_getter, processor in SUPPORTED_METADATA[plex_type]:
                if not processing_is_activated(item_getter):
                    continue
                self._process_in_batches(item_getter, processor, plex_type)

    def _run(self):
        finished = False
        while not finished:
            try:
                self._loop()
            except ProcessingNotDone:
                finished = False
            else:
                finished = True
            if self.wait_while_suspended():
                break
        logger.info('MetadataThread finished completely: %s', finished)
        self.callback(finished)

    def run(self):
        logger.info('Starting MetadataThread')
        app.APP.register_metadata_thread(self)
        try:
            self._run()
        except Exception:
            utils.ERROR(notify=True)
        finally:
            app.APP.deregister_metadata_thread(self)


class ProcessMetadataTask(backgroundthread.Task):
    """This task will also be executed while library sync is suspended!"""
    def setup(self, plex_id, plex_type, refresh=False):
        self.plex_id = plex_id
        self.plex_type = plex_type
        self.refresh = refresh

    def run(self):
        if self.plex_type not in SUPPORTED_METADATA:
            return
        for item_getter, processor in SUPPORTED_METADATA[self.plex_type]:
            if self.should_cancel():
                # Just don't process this item at all. Next full sync will
                # take care of it
                return
            if not processing_is_activated(item_getter):
                continue
            processor(self.plex_id, self.plex_type, self.refresh)
