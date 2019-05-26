#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import threading

from .common import PlaylistItem, PlaylistItemDummy, PlayqueueError

from ..downloadutils import DownloadUtils as DU
from ..plex_api import API
from ..plex_db import PlexDB
from ..kodi_db import KodiVideoDB
from ..playutils import PlayUtils
from ..windows.resume import resume_dialog
from .. import plex_functions as PF, utils, widgets, variables as v, app
from .. import json_rpc as js


LOG = getLogger('PLEX.playqueue')


class PlayQueue(object):
    """
    PKC object to represent PMS playQueues and Kodi playlist for queueing

    playlistid = None     [int] Kodi playlist id (0, 1, 2)
    type = None           [str] Kodi type: 'audio', 'video', 'picture'
    kodi_pl = None        Kodi xbmc.PlayList object
    items = []            [list] of PlaylistItem
    id = None             [str] Plex playQueueID, unique Plex identifier
    version = None        [int] Plex version of the playQueue
    selectedItemID = None
                          [str] Plex selectedItemID, playing element in queue
    selectedItemOffset = None
                          [str] Offset of the playing element in queue
    shuffled = 0          [int] 0: not shuffled, 1: ??? 2: ???
    repeat = 0            [int] 0: not repeated, 1: ??? 2: ???

    If Companion playback is initiated by another user:
    plex_transient_token = None
    """
    kind = 'playQueue'

    def __init__(self):
        self.id = None
        self.type = None
        self.playlistid = None
        self.kodi_pl = None
        self.items = []
        self.version = None
        self.selectedItemID = None
        self.selectedItemOffset = None
        self.shuffled = 0
        self.repeat = 0
        self.plex_transient_token = None
        # Need a hack for detecting swaps of elements
        self.old_kodi_pl = []
        # Did PKC itself just change the playqueue so the PKC playqueue monitor
        # should not pick up any changes?
        self.pkc_edit = False
        # Workaround to avoid endless loops of detecting PL clears
        self._clear_list = []
        # To keep track if Kodi playback was initiated from a Kodi playlist
        # There are a couple of pitfalls, unfortunately...
        self.kodi_playlist_playback = False
        # Playlist position/index used when initiating the playqueue
        self.index = None
        self.force_transcode = None

    def __unicode__(self):
        return ("{{"
                "'playlistid': {self.playlistid}, "
                "'id': {self.id}, "
                "'version': {self.version}, "
                "'type': '{self.type}', "
                "'items': {items}, "
                "'selectedItemID': {self.selectedItemID}, "
                "'selectedItemOffset': {self.selectedItemOffset}, "
                "'shuffled': {self.shuffled}, "
                "'repeat': {self.repeat}, "
                "'kodi_playlist_playback': {self.kodi_playlist_playback}, "
                "'pkc_edit': {self.pkc_edit}, "
                "}}").format(**{
                    'items': ['%s/%s: %s' % (x.plex_id, x.id, x.name)
                              for x in self.items],
                    'self': self
                })

    def __str__(self):
        return unicode(self).encode('utf-8')
    __repr__ = __str__

    def is_pkc_clear(self):
        """
        Returns True if PKC has cleared the Kodi playqueue just recently.
        Then this clear will be ignored from now on
        """
        try:
            self._clear_list.pop()
        except IndexError:
            return False
        else:
            return True

    def clear(self, kodi=True):
        """
        Resets the playlist object to an empty playlist.

        Pass kodi=False in order to NOT clear the Kodi playqueue
        """
        # kodi monitor's on_clear method will only be called if there were some
        # items to begin with
        if kodi and self.kodi_pl.size() != 0:
            self._clear_list.append(None)
            self.kodi_pl.clear()  # Clear Kodi playlist object
        self.items = []
        self.id = None
        self.version = None
        self.selectedItemID = None
        self.selectedItemOffset = None
        self.shuffled = 0
        self.repeat = 0
        self.plex_transient_token = None
        self.old_kodi_pl = []
        self.kodi_playlist_playback = False
        self.index = None
        self.force_transcode = None
        LOG.debug('Playlist cleared: %s', self)

    def init(self, playlistitem):
        """
        Hit if Kodi initialized playback and we need to catch up on the PKC
        and Plex side; e.g. for direct paths.

        Kodi side will NOT be changed, e.g. no trailers will be added, but Kodi
        playqueue taken as-is
        """
        LOG.debug('Playqueue init called')
        self.clear(kodi=False)
        if not isinstance(playlistitem, PlaylistItem) or playlistitem.uri is None:
            raise RuntimeError('Didnt receive a valid PlaylistItem but %s: %s'
                               % (type(playlistitem), playlistitem))
        try:
            params = {
                'next': 0,
                'type': self.type,
                'uri': playlistitem.uri
            }
            xml = DU().downloadUrl(url="{server}/%ss" % self.kind,
                                   action_type="POST",
                                   parameters=params)
            self.update_details_from_xml(xml)
            # Need to update the details for the playlist item
            playlistitem.from_xml(xml[0])
        except (KeyError, IndexError, TypeError):
            LOG.error('Could not init Plex playlist with %s', playlistitem)
            raise PlayqueueError()
        self.items.append(playlistitem)
        LOG.debug('Initialized the playqueue on the Plex side: %s', self)

    def play(self, plex_id, plex_type=None, startpos=None, position=None,
             synched=True, force_transcode=None):
        """
        Initializes the playQueue with e.g. trailers and additional file parts
        Pass synched=False if you're sure that this item has not been synched
        to Kodi

        Or resolves webservice paths to actual paths

        Hit by webservice.py
        """
        LOG.debug('Play called with plex_id %s, plex_type %s, position %s, '
                  'synched %s, force_transcode %s, startpos %s', plex_id,
                  plex_type, position, synched, force_transcode, startpos)
        resolve = False
        try:
            if plex_id == self.items[startpos].plex_id:
                resolve = True
        except IndexError:
            pass
        if resolve:
            LOG.info('Resolving playback')
            self._resolve(plex_id, startpos)
        else:
            LOG.info('Initializing playback')
            self._init(plex_id,
                       plex_type,
                       startpos,
                       position,
                       synched,
                       force_transcode)

    def _resolve(self, plex_id, startpos):
        """
        The Plex playqueue has already been initialized. We resolve the path
        from original webservice http://127.0.0.1 to the "correct" Plex one
        """
        playlistitem = self.items[startpos]
        # Add an additional item with the resolved path after the current one
        self.index = startpos + 1
        xml = PF.GetPlexMetadata(plex_id)
        if xml in (None, 401):
            raise PlayqueueError('Could not get Plex metadata %s for %s',
                                 plex_id, self.items[startpos])
        api = API(xml[0])
        if playlistitem.resume is None:
            # Potentially ask user to resume
            resume = self._resume_playback(None, xml[0])
        else:
            # Do NOT ask user
            resume = playlistitem.resume
        # Use the original playlistitem to retain all info!
        self._kodi_add_xml(xml[0],
                           api,
                           resume,
                           playlistitem=playlistitem)
        # Add additional file parts, if any exist
        self._add_additional_parts(xml)
        # Note: the CURRENT playlistitem will be deleted through webservice.py
        # once the path resolution has completed

    def _init(self, plex_id, plex_type=None, startpos=None, position=None,
              synched=True, force_transcode=None):
        """
        Initializes the Plex and PKC playqueue for playback. Possibly adds
        additionals trailers
        """
        self.index = position
        while len(self.items) < self.kodi_pl.size():
            # The original item that Kodi put into the playlist, e.g.
            # {
            #     u'title': u'',
            #     u'type': u'unknown',
            #     u'file': u'http://127.0.0.1:57578/plex/kodi/....',
            #     u'label': u''
            # }
            # We CANNOT delete that item right now - so let's add a dummy
            # on the PKC side to keep all indicees lined up.
            # The failing item will be deleted in webservice.py
            LOG.debug('Adding a dummy item to our playqueue')
            self.items.insert(0, PlaylistItemDummy())
        self.force_transcode = force_transcode
        if synched:
            with PlexDB(lock=False) as plexdb:
                db_item = plexdb.item_by_id(plex_id, plex_type)
        else:
            db_item = None
        if db_item:
            xml = None
            section_uuid = db_item['section_uuid']
            plex_type = db_item['plex_type']
        else:
            xml = PF.GetPlexMetadata(plex_id)
            if xml in (None, 401):
                raise PlayqueueError('Could not get Plex metadata %s', plex_id)
            section_uuid = xml.get('librarySectionUUID')
            api = API(xml[0])
            plex_type = api.plex_type()
        resume = self._resume_playback(db_item, xml)
        trailers = False
        if (not resume and plex_type == v.PLEX_TYPE_MOVIE and
                utils.settings('enableCinema') == 'true'):
            if utils.settings('askCinema') == "true":
                # "Play trailers?"
                trailers = utils.yesno_dialog(utils.lang(29999),
                                              utils.lang(33016)) or False
            else:
                trailers = True
        LOG.debug('Playing trailers: %s', trailers)
        xml = PF.init_plex_playqueue(plex_id,
                                     section_uuid,
                                     plex_type=plex_type,
                                     trailers=trailers)
        if xml is None:
            LOG.error('Could not get playqueue for plex_id %s UUID %s for %s',
                      plex_id, section_uuid, self)
            raise PlayqueueError('Could not get playqueue')
        # See that we add trailers, if they exist in the xml return
        self._add_intros(xml)
        # Add the main item after the trailers
        # Look at the LAST item
        api = API(xml[-1])
        self._kodi_add_xml(xml[-1], api, resume)
        # Add additional file parts, if any exist
        self._add_additional_parts(xml)
        self.update_details_from_xml(xml)

    @staticmethod
    def _resume_playback(db_item=None, xml=None):
        '''
        Pass in either db_item or xml
        Resume item if available. Returns bool or raise an PlayStrmException if
        resume was cancelled by user.
        '''
        resume = app.PLAYSTATE.resume_playback
        app.PLAYSTATE.resume_playback = None
        if app.PLAYSTATE.autoplay:
            resume = False
            LOG.info('Skip resume for autoplay')
        elif resume is None:
            if db_item:
                with KodiVideoDB(lock=False) as kodidb:
                    resume = kodidb.get_resume(db_item['kodi_fileid'])
            else:
                api = API(xml)
                resume = api.resume_point()
            if resume:
                resume = resume_dialog(resume)
                LOG.info('User chose resume: %s', resume)
                if resume is None:
                    raise PlayqueueError('User backed out of resume dialog')
            app.PLAYSTATE.autoplay = True
        return resume

    def _add_intros(self, xml):
        '''
        if we have any play them when the movie/show is not being resumed.
        '''
        if not len(xml) > 1:
            LOG.debug('No trailers returned from the PMS')
            return
        for i, intro in enumerate(xml):
            if i + 1 == len(xml):
                # The main item we're looking at - skip!
                break
            api = API(intro)
            LOG.debug('Adding trailer: %s', api.title())
            self._kodi_add_xml(intro, api)

    def _add_additional_parts(self, xml):
        ''' Create listitems and add them to the stack of playlist.
        '''
        api = API(xml[0])
        for part, _ in enumerate(xml[0][0]):
            if part == 0:
                # The first part that we've already added
                continue
            api.set_part_number(part)
            LOG.debug('Adding addional part for %s: %s', api.title(), part)
            self._kodi_add_xml(xml[0], api)

    def _kodi_add_xml(self, xml, api, resume=False, playlistitem=None):
        if not playlistitem:
            playlistitem = PlaylistItem(xml_video_element=xml)
        playlistitem.part = api.part
        playlistitem.force_transcode = self.force_transcode
        listitem = widgets.get_listitem(xml, resume=True)
        listitem.setSubtitles(api.cache_external_subs())
        play = PlayUtils(api, playlistitem)
        url = play.getPlayUrl()
        listitem.setPath(url.encode('utf-8'))
        self.kodi_add_item(playlistitem, self.index, listitem)
        self.items.insert(self.index, playlistitem)
        self.index += 1

    def update_details_from_xml(self, xml):
        """
        Updates the playlist details from the xml provided
        """
        self.id = utils.cast(int, xml.get('%sID' % self.kind))
        self.version = utils.cast(int, xml.get('%sVersion' % self.kind))
        self.shuffled = utils.cast(int, xml.get('%sShuffled' % self.kind))
        self.selectedItemID = utils.cast(int,
                                         xml.get('%sSelectedItemID' % self.kind))
        self.selectedItemOffset = utils.cast(int,
                                             xml.get('%sSelectedItemOffset'
                                                     % self.kind))
        LOG.debug('Updated playlist from xml: %s', self)

    def add_item(self, item, pos, listitem=None):
        """
        Adds a PlaylistItem to both Kodi and Plex at position pos [int]
        Also changes self.items
        Raises PlayqueueError
        """
        self.kodi_add_item(item, pos, listitem)
        self.plex_add_item(item, pos)

    def kodi_add_item(self, item, pos, listitem=None):
        """
        Adds a PlaylistItem to Kodi only. Will not change self.items
        Raises PlayqueueError
        """
        if not isinstance(item, PlaylistItem):
            raise PlayqueueError('Wrong item %s of type %s received'
                                 % (item, type(item)))
        if pos > len(self.items):
            raise PlayqueueError('Position %s too large for playlist length %s'
                                 % (pos, len(self.items)))
        LOG.debug('Adding item to Kodi playlist at position %s: %s', pos, item)
        if listitem:
            self.kodi_pl.add(url=listitem.getPath(),
                             listitem=listitem,
                             index=pos)
        elif item.kodi_id is not None and item.kodi_type is not None:
            # This method ensures we have full Kodi metadata, potentially
            # with more artwork, for example, than Plex provides
            if pos == len(self.items):
                answ = js.playlist_add(self.playlistid,
                                       {'%sid' % item.kodi_type: item.kodi_id})
            else:
                answ = js.playlist_insert({'playlistid': self.playlistid,
                                           'position': pos,
                                           'item': {'%sid' % item.kodi_type: item.kodi_id}})
            if 'error' in answ:
                raise PlayqueueError('Kodi did not add item to playlist: %s',
                                     answ)
        else:
            if item.xml is None:
                LOG.debug('Need to get metadata for item %s', item)
                item.xml = PF.GetPlexMetadata(item.plex_id)
                if item.xml in (None, 401):
                    raise PlayqueueError('Could not get metadata for %s', item)
            api = API(item.xml[0])
            listitem = widgets.get_listitem(item.xml, resume=True)
            url = 'http://127.0.0.1:%s/plex/play/file.strm' % v.WEBSERVICE_PORT
            args = {
                'plex_id': item.plex_id,
                'plex_type': api.plex_type()
            }
            if item.force_transcode:
                args['transcode'] = 'true'
            url = utils.extend_url(url, args)
            item.file = url
            listitem.setPath(url.encode('utf-8'))
            self.kodi_pl.add(url=url.encode('utf-8'),
                             listitem=listitem,
                             index=pos)

    def plex_add_item(self, item, pos):
        """
        Adds a new PlaylistItem to the playlist at position pos [int] only on
        the Plex side of things. Also changes self.items
        Raises PlayqueueError
        """
        if not isinstance(item, PlaylistItem) or not item.uri:
            raise PlayqueueError('Wrong item %s of type %s received'
                                 % (item, type(item)))
        if pos > len(self.items):
            raise PlayqueueError('Position %s too large for playlist length %s'
                                 % (pos, len(self.items)))
        LOG.debug('Adding item to Plex playlist at position %s: %s', pos, item)
        url = '{server}/%ss/%s?uri=%s' % (self.kind, self.id, item.uri)
        # Will usually put the new item at the end of the Plex playlist
        xml = DU().downloadUrl(url, action_type='PUT')
        try:
            xml[0].attrib
        except (TypeError, AttributeError, KeyError, IndexError):
            raise PlayqueueError('Could not add item %s to playlist %s'
                                 % (item, self))
        for actual_pos, xml_video_element in enumerate(xml):
            api = API(xml_video_element)
            if api.plex_id() == item.plex_id:
                break
        else:
            raise PlayqueueError('Something went wrong - Plex id not found')
        item.from_xml(xml[actual_pos])
        self.items.insert(actual_pos, item)
        self.update_details_from_xml(xml)
        if actual_pos != pos:
            self.plex_move_item(actual_pos, pos)
        LOG.debug('Added item %s on Plex side: %s', item, self)

    def kodi_remove_item(self, pos):
        """
        Only manipulates the Kodi playlist. Won't change self.items
        """
        LOG.debug('Removing position %s on the Kodi side for %s', pos, self)
        answ = js.playlist_remove(self.playlistid, pos)
        if 'error' in answ:
            raise PlayqueueError('Could not remove item: %s' % answ['error'])

    def plex_remove_item(self, pos):
        """
        Removes an item from Plex as well as our self.items item list
        """
        LOG.debug('Deleting position %s on the Plex side for: %s', pos, self)
        try:
            xml = DU().downloadUrl("{server}/%ss/%s/items/%s?repeat=%s" %
                                   (self.kind,
                                    self.id,
                                    self.items[pos].id,
                                    self.repeat),
                                   action_type="DELETE")
            self.update_details_from_xml(xml)
            del self.items[pos]
        except IndexError:
            LOG.error('Could not delete item at position %s on the Plex side',
                      pos)
            raise PlayqueueError()

    def plex_move_item(self, before, after):
        """
        Moves playlist item from before [int] to after [int] for Plex only.

        Will also change self.items
        """
        if before > len(self.items) or after > len(self.items) or after == before:
            raise PlayqueueError('Illegal original position %s and/or desired '
                                 'position %s for playlist length %s' %
                                 (before, after, len(self.items)))
        LOG.debug('Moving item from %s to %s on the Plex side for %s',
                  before, after, self)
        if after == 0:
            url = "{server}/%ss/%s/items/%s/move?after=0" % \
                  (self.kind,
                   self.id,
                   self.items[before].id)
        elif after > before:
            url = "{server}/%ss/%s/items/%s/move?after=%s" % \
                  (self.kind,
                   self.id,
                   self.items[before].id,
                   self.items[after].id)
        else:
            url = "{server}/%ss/%s/items/%s/move?after=%s" % \
                  (self.kind,
                   self.id,
                   self.items[before].id,
                   self.items[after - 1].id)
        xml = DU().downloadUrl(url, action_type="PUT")
        try:
            xml[0].attrib
        except (TypeError, IndexError, AttributeError):
            raise PlayqueueError('Could not move playlist item from %s to %s '
                                 'for %s' % (before, after, self))
        self.update_details_from_xml(xml)
        self.items.insert(after, self.items.pop(before))
        LOG.debug('Done moving items for %s', self)

    def init_from_xml(self, xml, offset=None, start_plex_id=None, repeat=None,
                      transient_token=None):
        """
        Play all items contained in the xml passed in. Called by Plex Companion.
        Either supply the ratingKey of the starting Plex element. Or set
        playqueue.selectedItemID

            offset [float]: will seek to position offset after playback start
            start_plex_id [int]: the plex_id of the element that should be
                played
            repeat [int]: 0: don't repear
                          1: repeat item
                          2: repeat everything
            transient_token [unicode]: temporary token received from the PMS

        Will stop current playback and start playback at the end
        """
        LOG.debug("init_from_xml called with offset %s, start_plex_id %s",
                  offset, start_plex_id)
        app.APP.player.stop()
        self.clear()
        self.update_details_from_xml(xml)
        self.repeat = 0 if not repeat else repeat
        self.plex_transient_token = transient_token
        for pos, xml_video_element in enumerate(xml):
            playlistitem = PlaylistItem(xml_video_element=xml_video_element)
            self.kodi_add_item(playlistitem, pos)
            self.items.append(playlistitem)
        # Where do we start playback?
        if start_plex_id is not None:
            for startpos, item in enumerate(self.items):
                if item.plex_id == start_plex_id:
                    break
            else:
                startpos = 0
        else:
            for startpos, item in enumerate(self.items):
                if item.id == self.selectedItemID:
                    break
            else:
                startpos = 0
        # Set resume for the item we should play - do NOT ask user since we
        # initiated from the other Companion client
        self.items[startpos].resume = True if offset else False
        self.start_playback(pos=startpos, offset=offset)

    def start_playback(self, pos=0, offset=0):
        """
        Seek immediately after kicking off playback is not reliable.
        Threaded, since we need to return BEFORE seeking
        """
        LOG.info('Starting playback at %s offset %s for %s', pos, offset, self)
        thread = threading.Thread(target=self._threaded_playback,
                                  args=(self.kodi_pl, pos, offset))
        thread.start()

    @staticmethod
    def _threaded_playback(kodi_playlist, pos, offset):
        app.APP.player.play(kodi_playlist, startpos=pos, windowed=False)
        if offset:
            i = 0
            while not app.APP.is_playing:
                app.APP.monitor.waitForAbort(0.1)
                i += 1
                if i > 50:
                    LOG.warn('Could not seek to %s', offset)
                    return
            js.seek_to(offset)
