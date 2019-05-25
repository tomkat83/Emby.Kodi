#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals

from ..plex_db import PlexDB
from ..plex_api import API
from .. import plex_functions as PF, utils, kodi_db, variables as v, app

# Our PKC playqueues (3 instances of PlayQueue())
PLAYQUEUES = []


class PlaylistError(Exception):
    """
    Exception for our playlist constructs
    """
    pass


class PlaylistItem(object):
    """
    Object to fill our playqueues and playlists with.

    id = None          [int] Plex playlist/playqueue id, e.g. playQueueItemID
    plex_id = None     [int] Plex unique item id, "ratingKey"
    plex_type = None   [str] Plex type, e.g. 'movie', 'clip'
    plex_uuid = None   [str] Plex librarySectionUUID
    kodi_id = None     [int] Kodi unique kodi id (unique only within type!)
    kodi_type = None   [str] Kodi type: 'movie'
    file = None        [str] Path to the item's file. STRING!!
    uri = None         [str] Weird Plex uri path involving plex_uuid. STRING!
    guid = None        [str] Weird Plex guid
    xml = None         [etree] XML from PMS, 1 lvl below <MediaContainer>
    playmethod = None  [str] either 'DirectPlay', 'DirectStream', 'Transcode'
    playcount = None   [int] how many times the item has already been played
    offset = None      [int] the item's view offset UPON START in Plex time
    part = 0           [int] part number if Plex video consists of mult. parts
    force_transcode    [bool] defaults to False

    PlaylistItem compare as equal, if they
    - have the same plex_id
    - OR: have the same kodi_id AND kodi_type
    - OR: have the same file
    """
    def __init__(self, plex_id=None, plex_type=None, xml_video_element=None,
                 kodi_id=None, kodi_type=None, kodi_item=None, grab_xml=False,
                 lookup_kodi=True):
        """
        Pass grab_xml=True in order to get Plex metadata from the PMS while
        passing a plex_id.
        Pass lookup_kodi=False to NOT check the plex.db for kodi_id and
        kodi_type if they're missing (won't be done for clips anyway)
        """
        self.name = None
        self.id = None
        self.plex_id = plex_id
        self.plex_type = plex_type
        self.plex_uuid = None
        self.kodi_id = kodi_id
        self.kodi_type = kodi_type
        self.file = None
        if kodi_item:
            self.kodi_id = kodi_item.get('id')
            self.kodi_type = kodi_item.get('type')
            self.file = kodi_item.get('file')
        self.uri = None
        self.guid = None
        self.xml = None
        self.playmethod = None
        self.playcount = None
        self.offset = None
        self.part = 0
        self.force_transcode = False
        # Shall we ask user to resume this item?
        #   None: ask user to resume
        #   False: do NOT resume, don't ask user
        #   True: do resume, don't ask user
        self.resume = None
        if (self.plex_id is None and
                (self.kodi_id is not None and self.kodi_type is not None)):
            with PlexDB(lock=False) as plexdb:
                db_item = plexdb.item_by_kodi_id(self.kodi_id, self.kodi_type)
            if db_item:
                self.plex_id = db_item['plex_id']
                self.plex_type = db_item['plex_type']
                self.plex_uuid = db_item['section_uuid']
        if grab_xml and plex_id is not None and xml_video_element is None:
            xml_video_element = PF.GetPlexMetadata(plex_id)
            try:
                xml_video_element = xml_video_element[0]
            except (TypeError, IndexError):
                xml_video_element = None
        if xml_video_element is not None:
            self.from_xml(xml_video_element)
        if (lookup_kodi and (self.kodi_id is None or self.kodi_type is None) and
                self.plex_type != v.PLEX_TYPE_CLIP):
            with PlexDB(lock=False) as plexdb:
                db_item = plexdb.item_by_id(self.plex_id, self.plex_type)
            if db_item is not None:
                self.kodi_id = db_item['kodi_id']
                self.kodi_type = db_item['kodi_type']
                self.plex_uuid = db_item['section_uuid']
        if (lookup_kodi and (self.kodi_id is None or self.kodi_type is None) and
                self.plex_type != v.PLEX_TYPE_CLIP):
            self._guess_id_from_file()
        self.set_uri()

    def __eq__(self, other):
        if self.plex_id is not None and other.plex_id is not None:
            return self.plex_id == other.plex_id
        elif (self.kodi_id is not None and other.kodi_id is not None and
              self.kodi_type and other.kodi_type):
            return (self.kodi_id == other.kodi_id and
                    self.kodi_type == other.kodi_type)
        elif self.file and other.file:
            return self.file == other.file
        raise RuntimeError('PlaylistItems not fully defined: %s, %s' %
                           (self, other))

    def __ne__(self, other):
        return not self == other

    def __unicode__(self):
        return ("{{"
                "'name': '{self.name}', "
                "'id': {self.id}, "
                "'plex_id': {self.plex_id}, "
                "'plex_type': '{self.plex_type}', "
                "'kodi_id': {self.kodi_id}, "
                "'kodi_type': '{self.kodi_type}', "
                "'file': '{self.file}', "
                "'uri': '{self.uri}', "
                "'guid': '{self.guid}', "
                "'playmethod': '{self.playmethod}', "
                "'playcount': {self.playcount}, "
                "'offset': {self.offset}, "
                "'force_transcode': {self.force_transcode}, "
                "'part': {self.part}"
                "}}".format(self=self))

    def __str__(self):
        return unicode(self).encode('utf-8')
    __repr__ = __str__

    def from_xml(self, xml_video_element):
        """
        xml_video_element: etree xml piece 1 level underneath <MediaContainer>
        item.id will only be set if you passed in an xml_video_element from
        e.g. a playQueue
        """
        api = API(xml_video_element)
        self.name = api.title()
        self.plex_id = api.plex_id()
        self.plex_type = api.plex_type()
        self.id = api.item_id()
        self.guid = api.guid_html_escaped()
        self.playcount = api.viewcount()
        self.offset = api.resume_point()
        self.xml = xml_video_element
        self.set_uri()

    def from_kodi(self, playlist_item):
        """
        playlist_item: dict contains keys 'id', 'type', 'file' (if applicable)

        Will thus set the attributes kodi_id, kodi_type, file, if applicable
        If kodi_id & kodi_type are provided, plex_id and plex_type will be
        looked up (if not already set)
        """
        self.kodi_id = playlist_item.get('id')
        self.kodi_type = playlist_item.get('type')
        self.file = playlist_item.get('file')
        if self.plex_id is None and self.kodi_id is not None and self.kodi_type:
            with PlexDB(lock=False) as plexdb:
                db_item = plexdb.item_by_kodi_id(self.kodi_id, self.kodi_type)
            if db_item:
                self.plex_id = db_item['plex_id']
                self.plex_type = db_item['plex_type']
                self.plex_uuid = db_item['section_uuid']
        if self.plex_id is None and self.file is not None:
            try:
                query = self.file.split('?', 1)[1]
            except IndexError:
                query = ''
            query = dict(utils.parse_qsl(query))
            self.plex_id = utils.cast(int, query.get('plex_id'))
            self.plex_type = query.get('itemType')
        self.set_uri()

    def set_uri(self):
        if self.plex_id is None and self.file is not None:
            self.uri = ('library://whatever/item/%s'
                        % utils.quote(self.file, safe=''))
        elif self.plex_id is not None and self.plex_uuid is not None:
            # TO BE VERIFIED - PLEX DOESN'T LIKE PLAYLIST ADDS IN THIS MANNER
            self.uri = ('library://%s/item/library%%2Fmetadata%%2F%s' %
                        (self.plex_uuid, self.plex_id))
        elif self.plex_id is not None:
            self.uri = ('library://%s/item/library%%2Fmetadata%%2F%s' %
                        (self.plex_id, self.plex_id))
        else:
            self.uri = None

    def _guess_id_from_file(self):
        """
        """
        if not self.file:
            return
        # Special case playlist startup - got type but no id
        if (not app.SYNC.direct_paths and app.SYNC.enable_music and
                self.kodi_type == v.KODI_TYPE_SONG and
                self.file.startswith('http')):
            self.kodi_id, _ = kodi_db.kodiid_from_filename(self.file,
                                                           v.KODI_TYPE_SONG)
            return
        # Need more info since we don't have kodi_id nor type. Use file path.
        if (self.file.startswith('plugin') or
                (self.file.startswith('http') and not
                 self.file.startswith('http://127.0.0.1:%s' % v.WEBSERVICE_PORT))):
            return
        # Try the VIDEO DB first - will find both movies and episodes
        self.kodi_id, self.kodi_type = kodi_db.kodiid_from_filename(self.file,
                                                                    db_type='video')
        if self.kodi_id is None:
            # No movie or episode found - try MUSIC DB now for songs
            self.kodi_id, self.kodi_type = kodi_db.kodiid_from_filename(self.file,
                                                                        db_type='music')
        self.kodi_type = None if self.kodi_id is None else self.kodi_type

    def plex_stream_index(self, kodi_stream_index, stream_type):
        """
        Pass in the kodi_stream_index [int] in order to receive the Plex stream
        index.

            stream_type:    'video', 'audio', 'subtitle'

        Returns None if unsuccessful
        """
        stream_type = v.PLEX_STREAM_TYPE_FROM_STREAM_TYPE[stream_type]
        count = 0
        if kodi_stream_index == -1:
            # Kodi telling us "it's the last one"
            iterator = list(reversed(self.xml[0][self.part]))
            kodi_stream_index = 0
        else:
            iterator = self.xml[0][self.part]
        # Kodi indexes differently than Plex
        for stream in iterator:
            if (stream.attrib['streamType'] == stream_type and
                    'key' in stream.attrib):
                if count == kodi_stream_index:
                    return stream.attrib['id']
                count += 1
        for stream in iterator:
            if (stream.attrib['streamType'] == stream_type and
                    'key' not in stream.attrib):
                if count == kodi_stream_index:
                    return stream.attrib['id']
                count += 1

    def kodi_stream_index(self, plex_stream_index, stream_type):
        """
        Pass in the kodi_stream_index [int] in order to receive the Plex stream
        index.

            stream_type:    'video', 'audio', 'subtitle'

        Returns None if unsuccessful
        """
        stream_type = v.PLEX_STREAM_TYPE_FROM_STREAM_TYPE[stream_type]
        count = 0
        for stream in self.xml[0][self.part]:
            if (stream.attrib['streamType'] == stream_type and
                    'key' in stream.attrib):
                if stream.attrib['id'] == plex_stream_index:
                    return count
                count += 1
        for stream in self.xml[0][self.part]:
            if (stream.attrib['streamType'] == stream_type and
                    'key' not in stream.attrib):
                if stream.attrib['id'] == plex_stream_index:
                    return count
                count += 1


class PlaylistItemDummy(PlaylistItem):
    """
    Let e.g. Kodimonitor detect that this is a dummy item
    """
    def __init__(self, *args, **kwargs):
        super(PlaylistItemDummy, self).__init__(*args, **kwargs)
        self.name = 'dummy item'
        self.id = 0
        self.plex_id = 0
