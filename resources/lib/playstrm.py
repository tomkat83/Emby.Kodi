# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import urllib

import xbmc
import xbmcgui

from .plex_api import API
from . import plex_function as PF, utils, json_rpc, variables as v, \
    widgets


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
        if utils.window('plex.playlist.audio.bool'):
            LOG.info('Audio playlist detected')
            self.kodi_playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        else:
            self.kodi_playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)

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
        listitem = xbmcgui.ListItem()
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
            url = '%s?%s' % (url, urllib.urlencode(args))
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
        if (not seektime and self.plex_type == v.PLEX_TYPE_MOVIE and
                utils.settings('enableCinema') == 'true'):
            self._set_intros()

        play = playutils.PlayUtilsStrm(self.xml, self.transcode, self.server_id, self.info['Server'])
        source = play.select_source(play.get_sources())

        if not source:
            raise PlayStrmException('Playback selection cancelled')

        play.set_external_subs(source, listitem)
        self.set_listitem(self.xml, listitem, self.kodi_id, seektime)
        listitem.setPath(self.xml['PlaybackInfo']['Path'])
        playutils.set_properties(self.xml, self.xml['PlaybackInfo']['Method'], self.server_id)

        self.kodi_playlist.add(url=self.xml['PlaybackInfo']['Path'], listitem=listitem, index=self.index)
        self.index += 1

        if self.xml.get('PartCount'):
            self._set_additional_parts()

    def _resume(self):
        '''
        Resume item if available. Returns bool or raise an PlayStrmException if
        resume was cancelled by user.
        '''
        seektime = utils.window('plex.resume')
        utils.window('plex.resume', clear=True)
        seektime = seektime == 'true' if seektime else None
        auto_play = utils.window('plex.autoplay.bool')
        if auto_play:
            seektime = False
            LOG.info('Skip resume for autoplay')
        elif seektime is None:
            resume = self.api.resume_point()
            if resume:
                seektime = resume_dialog(resume)
                LOG.info('Resume: %s', seektime)
                if seektime is None:
                    raise PlayStrmException('User backed out of resume dialog.')
            # Todo: Probably need to have a look here
            utils.window('plex.autoplay.bool', value='true')
        return seektime

    def _set_intros(self):
        '''
        if we have any play them when the movie/show is not being resumed.
        '''
        if self.info['Intros']['Items']:
            enabled = True

            if utils.settings('askCinema') == 'true':

                resp = dialog('yesno', heading='{emby}', line1=_(33016))
                if not resp:

                    enabled = False
                    LOG.info('Skip trailers.')

            if enabled:
                for intro in self.info['Intros']['Items']:

                    listitem = xbmcgui.ListItem()
                    LOG.info('[ intro/%s/%s ] %s', intro['plex_id'], self.index, intro['Name'])

                    play = playutils.PlayUtilsStrm(intro, False, self.server_id, self.info['Server'])
                    source = play.select_source(play.get_sources())
                    self.set_listitem(intro, listitem, intro=True)
                    listitem.setPath(intro['PlaybackInfo']['Path'])
                    playutils.set_properties(intro, intro['PlaybackInfo']['Method'], self.server_id)

                    self.kodi_playlist.add(url=intro['PlaybackInfo']['Path'], listitem=listitem, index=self.index)
                    self.index += 1

                    utils.window('plex.skip.%s' % intro['plex_id'], value='true')

    def _set_additional_parts(self):
        ''' Create listitems and add them to the stack of playlist.
        '''
        for part in self.info['AdditionalParts']['Items']:

            listitem = xbmcgui.ListItem()
            LOG.info('[ part/%s/%s ] %s', part['plex_id'], self.index, part['Name'])

            play = playutils.PlayUtilsStrm(part, self.transcode, self.server_id, self.info['Server'])
            source = play.select_source(play.get_sources())
            play.set_external_subs(source, listitem)
            self.set_listitem(part, listitem)
            listitem.setPath(part['PlaybackInfo']['Path'])
            playutils.set_properties(part, part['PlaybackInfo']['Method'], self.server_id)

            self.kodi_playlist.add(url=part['PlaybackInfo']['Path'], listitem=listitem, index=self.index)
            self.index += 1
