# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from . import common
from ..plex_api import API
from .. import backgroundthread, plex_functions as PF, utils, variables as v

LOG = getLogger('PLEX.sync.get_metadata')
LOCK = backgroundthread.threading.Lock()


class GetMetadataThread(backgroundthread.KillableThread, common.fullsync_mixin):
    """
    Threaded download of Plex XML metadata for a certain library item.
    Fills the queue with the downloaded etree XML objects

    Input:
        queue               Queue.Queue() object where this thread will store
                            the downloaded metadata XMLs as etree objects
    """
    def __init__(self, get_medata_queue, processing_queue):
        self.get_medata_queue = get_medata_queue
        self.processing_queue = processing_queue
        super(GetMetadataThread, self).__init__()

    def _collections(self, item):
        api = API(item['xml'][0])
        collection_match = item['section'].collection_match
        collection_xmls = item['section'].collection_xmls
        if collection_match is None:
            collection_match = PF.collections(api.library_section_id())
            if collection_match is None:
                LOG.error('Could not download collections')
                return
            # Extract what we need to know
            collection_match = \
                [(utils.cast(int, x.get('index')),
                  utils.cast(int, x.get('ratingKey'))) for x in collection_match]
        item['children'] = {}
        for plex_set_id, set_name in api.collections():
            if self.isCanceled():
                return
            if plex_set_id not in collection_xmls:
                # Get Plex metadata for collections - a pain
                for index, collection_plex_id in collection_match:
                    if index == plex_set_id:
                        collection_xml = PF.GetPlexMetadata(collection_plex_id)
                        try:
                            collection_xml[0].attrib
                        except (TypeError, IndexError, AttributeError):
                            LOG.error('Could not get collection %s %s',
                                      collection_plex_id, set_name)
                            continue
                        collection_xmls[plex_set_id] = collection_xml
                        break
                else:
                    LOG.error('Did not find Plex collection %s %s',
                              plex_set_id, set_name)
                    continue
            item['children'][plex_set_id] = collection_xmls[plex_set_id]

    def _process_abort(self, section):
        # Make sure other threads will also receive sentinel
        self.get_medata_queue.put(None)
        if section:
            section.sync_successful = False

    def run(self):
        LOG.debug('Starting metadata thread')
        while True:
            item = self.get_medata_queue.get()
            try:
                if item is None or self.isCanceled():
                    self._process_abort(item[1] if item else None)
                    break
                count, plex_id, section = item
                item = {
                    'xml': PF.GetPlexMetadata(plex_id),  # This will block
                    'children': None,
                    'section': section
                }
                if item['xml'] is None:
                    # Did not receive a valid XML - skip that item for now
                    LOG.error("Could not get metadata for %s. Skipping item "
                              "for now", plex_id)
                    section.sync_successful = False
                    continue
                elif item['xml'] == 401:
                    LOG.error('HTTP 401 returned by PMS. Too much strain? '
                              'Cancelling sync for now')
                    utils.window('plex_scancrashed', value='401')
                    self._process_abort(section)
                    break
                if section.plex_type == v.PLEX_TYPE_MOVIE:
                    # Check for collections/sets
                    collections = False
                    for child in item['xml'][0]:
                        if child.tag == 'Collection':
                            collections = True
                            break
                    if collections:
                        with LOCK:
                            self._collections(item)
                if section.get_children:
                    if self.isCanceled():
                        self._process_abort(section)
                        break
                    children_xml = PF.GetAllPlexChildren(plex_id)  # Will block
                    try:
                        children_xml[0].attrib
                    except (TypeError, IndexError, AttributeError):
                        LOG.error('Could not get children for Plex id %s',
                                  plex_id)
                        section.sync_successful = False
                        continue
                    else:
                        item['children'] = children_xml
                self.processing_queue.put((count, item))
            finally:
                self.get_medata_queue.task_done()
        LOG.debug('Stopping metadata thread')
