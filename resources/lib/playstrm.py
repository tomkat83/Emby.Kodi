# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from . import app, utils, json_rpc, variables as v, playlist_func as PL, \
    playqueue as PQ


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
    def __init__(self, params):
        LOG.debug('Starting PlayStrm with params: %s', params)
        self.plex_id = utils.cast(int, params['plex_id'])
        self.plex_type = params.get('plex_type')
        if params.get('synched') and params['synched'].lower() == 'false':
            self.synched = False
        else:
            self.synched = True
        self.kodi_id = utils.cast(int, params.get('kodi_id'))
        self.kodi_type = params.get('kodi_type')
        self.force_transcode = params.get('transcode') == 'true'
        if app.PLAYSTATE.audioplaylist:
            LOG.debug('Audio playlist detected')
            self.playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_AUDIO)
        else:
            LOG.debug('Video playlist detected')
            self.playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_VIDEO)

    def __unicode__(self):
        return ("{{"
                "'plex_id': {self.plex_id}, "
                "'plex_type': '{self.plex_type}', "
                "'kodi_id': {self.kodi_id}, "
                "'kodi_type': '{self.kodi_type}', "
                "}}").format(self=self)

    def __str__(self):
        return unicode(self).encode('utf-8')
    __repr__ = __str__

    def play(self, start_position=None, delayed=True):
        '''
        Create and add a single listitem to the Kodi playlist, potentially
        with trailers and different file-parts
        '''
        LOG.debug('play called with start_position %s, delayed %s',
                  start_position, delayed)
        LOG.debug('Kodi playlist BEFORE: %s',
                  json_rpc.playlist_get_items(self.playqueue.playlistid))
        self.playqueue.init(self.plex_id,
                            plex_type=self.plex_type,
                            position=start_position,
                            synched=self.synched,
                            force_transcode=self.force_transcode)
        LOG.info('Initiating play for %s', self)
        LOG.debug('Kodi playlist AFTER: %s',
                  json_rpc.playlist_get_items(self.playqueue.playlistid))
        if not delayed:
            self.playqueue.start_playback(start_position)
        return self.playqueue.index

    def play_folder(self, position=None):
        '''
        When an entire queue is requested, If requested from Kodi, kodi_type is
        provided, add as Kodi would, otherwise queue playlist items using strm
        links to setup playback later.
        '''
        start_position = position or max(self.playqueue.kodi_pl.size(), 0)
        index = start_position + 1
        LOG.info('Play folder plex_id %s, index: %s', self.plex_id, index)
        item = PL.PlaylistItem(plex_id=self.plex_id,
                               plex_type=self.plex_type,
                               kodi_id=self.kodi_id,
                               kodi_type=self.kodi_type)
        self.playqueue.add_item(item, index)
        index += 1
        return index - 1
