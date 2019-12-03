# -*- coding: utf-8 -*-

from logging import getLogger

from . import common
from ..plex_api import API
from .. import plex_functions as PF, backgroundthread, utils, variables as v


LOG = getLogger("PLEX." + __name__)

LOCK = backgroundthread.threading.Lock()
# List of tuples: (collection index [as in an item's metadata with "Collection
# id"], collection plex id)
COLLECTION_MATCH = None
# Dict with entries of the form <collection index>: <collection xml>
COLLECTION_XMLS = {}


def reset_collections():
    """
    Collections seem unique to Plex sections
    """
    global LOCK, COLLECTION_MATCH, COLLECTION_XMLS
    with LOCK:
        COLLECTION_MATCH = None
        COLLECTION_XMLS = {}


class GetMetadataTask(common.fullsync_mixin, backgroundthread.Task):
    """
    Threaded download of Plex XML metadata for a certain library item.
    Fills the queue with the downloaded etree XML objects

    Input:
        queue               Queue.Queue() object where this thread will store
                            the downloaded metadata XMLs as etree objects
    """
    def __init__(self, queue, plex_id, plex_type, get_children=False,
                 count=None):
        self.queue = queue
        self.plex_id = plex_id
        self.plex_type = plex_type
        self.get_children = get_children
        self.count = count
        super(GetMetadataTask, self).__init__()

    def _collections(self, item):
        global COLLECTION_MATCH, COLLECTION_XMLS
        api = API(item['xml'][0])
        if COLLECTION_MATCH is None:
            COLLECTION_MATCH = PF.collections(api.library_section_id())
            if COLLECTION_MATCH is None:
                LOG.error('Could not download collections')
                return
            # Extract what we need to know
            COLLECTION_MATCH = \
                [(utils.cast(int, x.get('index')),
                  utils.cast(int, x.get('ratingKey'))) for x in COLLECTION_MATCH]
        item['children'] = {}
        for plex_set_id, set_name in api.collections():
            if self.isCanceled():
                return
            if plex_set_id not in COLLECTION_XMLS:
                # Get Plex metadata for collections - a pain
                for index, collection_plex_id in COLLECTION_MATCH:
                    if index == plex_set_id:
                        collection_xml = PF.GetPlexMetadata(collection_plex_id)
                        try:
                            collection_xml[0].attrib
                        except (TypeError, IndexError, AttributeError):
                            LOG.error('Could not get collection %s %s',
                                      collection_plex_id, set_name)
                            continue
                        COLLECTION_XMLS[plex_set_id] = collection_xml
                        break
                else:
                    LOG.error('Did not find Plex collection %s %s',
                              plex_set_id, set_name)
                    continue
            item['children'][plex_set_id] = COLLECTION_XMLS[plex_set_id]

    def run(self):
        """
        Do the work
        """
        if self.isCanceled():
            return
        # Download Metadata
        item = {
            'xml': PF.GetPlexMetadata(self.plex_id),
            'children': None
        }
        if item['xml'] is None:
            # Did not receive a valid XML - skip that item for now
            LOG.error("Could not get metadata for %s. Skipping that item "
                      "for now", self.plex_id)
            return
        elif item['xml'] == 401:
            LOG.error('HTTP 401 returned by PMS. Too much strain? '
                      'Cancelling sync for now')
            utils.window('plex_scancrashed', value='401')
            return
        if not self.isCanceled() and self.plex_type == v.PLEX_TYPE_MOVIE:
            # Check for collections/sets
            collections = False
            for child in item['xml'][0]:
                if child.tag == 'Collection':
                    collections = True
                    break
            if collections:
                global LOCK
                with LOCK:
                    self._collections(item)
        if not self.isCanceled() and self.get_children:
            children_xml = PF.GetAllPlexChildren(self.plex_id)
            try:
                children_xml[0].attrib
            except (TypeError, IndexError, AttributeError):
                LOG.error('Could not get children for Plex id %s',
                          self.plex_id)
            else:
                item['children'] = children_xml
        if not self.isCanceled():
            self.queue.put((self.count, item))
