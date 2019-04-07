# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

import xbmc

from .plex_api import API
from .playutils import PlayUtils
from .windows.resume import resume_dialog
from . import app, plex_functions as PF, utils, json_rpc, variables as v, \
    widgets, playlist_func as PL, playqueue as PQ


LOG = getLogger('PLEX.playstrm')


class PlayStrmException(Exception):
    """
    Any Exception associated with playstrm
    """
    pass


class PlayStrm(object):
    '''
    Workflow: Strm that calls our webservice in database. When played, the
    webserivce returns a dummy file to play. Meanwhile, PlayStrm adds the real
    listitems for items to play to the playlist.
    '''
    def __init__(self, params, server_id=None):
        LOG.debug('Starting PlayStrm with server_id %s, params: %s',
                  server_id, params)
        self.xml = None
        self.api = None
        self.start_index = None
        self.index = None
        self.server_id = server_id
        self.plex_id = utils.cast(int, params['plex_id'])
        self.plex_type = params.get('plex_type')
        if params.get('synched') and params['synched'].lower() == 'false':
            self.synched = False
        else:
            self.synched = True
        self._get_xml()
        self.name = self.api.title()
        self.kodi_id = utils.cast(int, params.get('kodi_id'))
        self.kodi_type = params.get('kodi_type')
        if ((self.kodi_id is None or self.kodi_type is None) and
                self.xml[0].get('pkc_db_item')):
            self.kodi_id = self.xml[0].get('pkc_db_item')['kodi_id']
            self.kodi_type = self.xml[0].get('pkc_db_item')['kodi_type']
        self.transcode = params.get('transcode')
        if self.transcode is None:
            self.transcode = utils.settings('playFromTranscode.bool') if utils.settings('playFromStream.bool') else None
        if utils.window('plex.playlist.audio'):
            LOG.debug('Audio playlist detected')
            self.playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_AUDIO)
        else:
            LOG.debug('Video playlist detected')
            self.playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_VIDEO)
        self.kodi_playlist = self.playqueue.kodi_pl

    def __repr__(self):
        return ("{{"
                "'name': '{self.name}', "
                "'plex_id': {self.plex_id}, "
                "'plex_type': '{self.plex_type}', "
                "'kodi_id': {self.kodi_id}, "
                "'kodi_type': '{self.kodi_type}', "
                "'server_id': '{self.server_id}', "
                "'transcode': {self.transcode}, "
                "'start_index': {self.start_index}, "
                "'index': {self.index}"
                "}}").format(self=self).encode('utf-8')
    __str__ = __repr__

    def add_to_playlist(self, kodi_id, kodi_type, index=None, playlistid=None):
        playlistid = playlistid or self.kodi_playlist.getPlayListId()
        LOG.debug('Adding kodi_id %s, kodi_type %s to playlist %s at index %s',
                  kodi_id, kodi_type, playlistid, index)
        if index is None:
            json_rpc.playlist_add(playlistid, {'%sid' % kodi_type: kodi_id})
        else:
            json_rpc.playlist_insert({'playlistid': playlistid,
                                      'position': index,
                                      'item': {'%sid' % kodi_type: kodi_id}})

    def remove_from_playlist(self, index):
        LOG.debug('Removing playlist item number %s from %s', index, self)
        json_rpc.playlist_remove(self.kodi_playlist.getPlayListId(),
                                 index)

    def _get_xml(self):
        self.xml = PF.GetPlexMetadata(self.plex_id)
        if self.xml in (None, 401):
            raise PlayStrmException('No xml received from the PMS')
        if self.synched:
            # Adds a new key 'pkc_db_item' to self.xml[0].attrib
            widgets.attach_kodi_ids(self.xml)
        else:
            self.xml[0].set('pkc_db_item', None)
        self.api = API(self.xml[0])
        self.playqueue_item = PL.playlist_item_from_xml(self.xml[0])

    def start_playback(self, index=0):
        LOG.debug('Starting playback at %s', index)
        xbmc.Player().play(self.kodi_playlist, startpos=index, windowed=False)

    def play(self, start_position=None, delayed=True):
        '''
        Create and add listitems to the Kodi playlist.
        '''
        if start_position is not None:
            self.start_index = start_position
        else:
            self.start_index = max(self.kodi_playlist.getposition(), 0)
        self.index = self.start_index
        listitem = widgets.get_listitem(self.xml[0])
        self._set_playlist(listitem)
        LOG.info('Initiating play for %s', self)
        if not delayed:
            self.start_playback(self.start_index)
        return self.start_index

    def play_folder(self, position=None):
        '''
        When an entire queue is requested, If requested from Kodi, kodi_type is
        provided, add as Kodi would, otherwise queue playlist items using strm
        links to setup playback later.
        '''
        self.start_index = position or max(self.kodi_playlist.size(), 0)
        self.index = self.start_index + 1
        LOG.info('Play folder plex_id %s, index: %s', self.plex_id, self.index)
        if self.kodi_id and self.kodi_type:
            self.add_to_playlist(self.kodi_id, self.kodi_type, self.index)
        else:
            listitem = widgets.get_listitem(self.xml[0])
            url = 'http://127.0.0.1:%s/plex/play/file.strm' % v.WEBSERVICE_PORT
            args = {
                'mode': 'play',
                'plex_id': self.plex_id,
                'plex_type': self.api.plex_type()
            }
            if self.kodi_id:
                args['kodi_id'] = self.kodi_id
            if self.kodi_type:
                args['kodi_type'] = self.kodi_type
            if self.server_id:
                args['server_id'] = self.server_id
            if self.transcode:
                args['transcode'] = True
            url = utils.extend_url(url, args).encode('utf-8')
            listitem.setPath(url)
            self.kodi_playlist.add(url=url,
                                   listitem=listitem,
                                   index=self.index)
        return self.index

    def _set_playlist(self, listitem):
        '''
        Verify seektime, set intros, set main item and set additional parts.
        Detect the seektime for video type content. Verify the default video
        action set in Kodi for accurate resume behavior.
        '''
        seektime = self._resume()
        trailers = False
        if (not seektime and self.plex_type == v.PLEX_TYPE_MOVIE and
                utils.settings('enableCinema') == 'true'):
            if utils.settings('askCinema') == "true":
                # "Play trailers?"
                trailers = utils.yesno_dialog(utils.lang(29999),
                                              utils.lang(33016)) or False
            else:
                trailers = True
        LOG.debug('Playing trailers: %s', trailers)
        xml = PF.init_plex_playqueue(self.plex_id,
                                     self.xml.get('librarySectionUUID'),
                                     mediatype=self.plex_type,
                                     trailers=trailers)
        if xml is None:
            LOG.error('Could not get playqueue for UUID %s for %s',
                      self.xml.get('librarySectionUUID'), self)
            # "Play error"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(30128),
                         icon='{error}')
            app.PLAYSTATE.context_menu_play = False
            app.PLAYSTATE.force_transcode = False
            app.PLAYSTATE.resume_playback = False
            return
        PL.get_playlist_details_from_xml(self.playqueue, xml)
        # See that we add trailers, if they exist in the xml return
        self._set_intros(xml)
        listitem.setSubtitles(self.api.cache_external_subs())
        play = PlayUtils(self.api, self.playqueue_item)
        url = play.getPlayUrl().encode('utf-8')
        listitem.setPath(url)
        self.kodi_playlist.add(url=url, listitem=listitem, index=self.index)
        self.index += 1
        if self.xml.get('PartCount'):
            self._set_additional_parts()

    def _resume(self):
        '''
        Resume item if available. Returns bool or raise an PlayStrmException if
        resume was cancelled by user.
        '''
        seektime = app.PLAYSTATE.resume_playback
        app.PLAYSTATE.resume_playback = None
        if app.PLAYSTATE.autoplay:
            seektime = False
            LOG.info('Skip resume for autoplay')
        elif seektime is None:
            resume = self.api.resume_point()
            if resume:
                seektime = resume_dialog(resume)
                LOG.info('User chose resume: %s', seektime)
                if seektime is None:
                    raise PlayStrmException('User backed out of resume dialog.')
            app.PLAYSTATE.autoplay = True
        return seektime

    def _set_intros(self, xml):
        '''
        if we have any play them when the movie/show is not being resumed.
        '''
        if not len(xml) > 1:
            LOG.debug('No trailers returned from the PMS')
            return
        for intro in xml:
            if utils.cast(int, xml.get('ratingKey')) == self.plex_id:
                # The main item we're looking at - skip!
                continue
            api = API(intro)
            listitem = widgets.get_listitem(intro)
            listitem.setSubtitles(api.cache_external_subs())
            playqueue_item = PL.playlist_item_from_xml(intro)
            play = PlayUtils(api, playqueue_item)
            url = play.getPlayUrl().encode('utf-8')
            listitem.setPath(url)
            self.kodi_playlist.add(url=url, listitem=listitem, index=self.index)
            self.index += 1
            utils.window('plex.skip.%s' % api.plex_id(), value='true')

    def _set_additional_parts(self):
        ''' Create listitems and add them to the stack of playlist.
        '''
        for part, _ in enumerate(self.xml[0][0]):
            if part == 0:
                # The first part that we've already added
                continue
            self.api.set_part_number(part)
            listitem = widgets.get_listitem(self.xml[0])
            listitem.setSubtitles(self.api.cache_external_subs())
            playqueue_item = PL.playlist_item_from_xml(self.xml[0])
            play = PlayUtils(self.api, playqueue_item)
            url = play.getPlayUrl().encode('utf-8')
            listitem.setPath(url)
            self.kodi_playlist.add(url=url, listitem=listitem, index=self.index)
            self.index += 1
