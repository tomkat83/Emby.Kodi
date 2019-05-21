#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
The Plex Companion master python file
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
from Queue import Empty
from socket import SHUT_RDWR
from xbmc import executebuiltin

from .plexbmchelper import listener, plexgdm, subscribers, httppersist
from .plex_api import API
from . import utils
from . import plex_functions as PF
from . import playlist_func as PL
from . import json_rpc as js
from . import playqueue as PQ
from . import variables as v
from . import backgroundthread
from . import app

###############################################################################

LOG = getLogger('PLEX.plex_companion')

###############################################################################


def update_playqueue_from_PMS(playqueue,
                              playqueue_id=None,
                              repeat=None,
                              offset=None,
                              transient_token=None):
    """
    Completely updates the Kodi playqueue with the new Plex playqueue. Pass
    in playqueue_id if we need to fetch a new playqueue

    repeat = 0, 1, 2
    offset = time offset in Plextime (milliseconds)

    Will (re)start playback
    """
    LOG.info('New playqueue %s received from Plex companion with offset '
             '%s, repeat %s', playqueue_id, offset, repeat)
    # Safe transient token from being deleted
    if transient_token is None:
        transient_token = playqueue.plex_transient_token
    with app.APP.lock_playqueues:
        xml = PL.get_PMS_playlist(playlist_id=playqueue_id)
        if xml is None:
            LOG.error('Could now download playqueue %s', playqueue_id)
            raise PL.PlaylistError()
        app.PLAYSTATE.initiated_by_plex = True
        playqueue.init_from_xml(xml,
                                offset=offset,
                                repeat=0 if not repeat else int(repeat),
                                transient_token=transient_token)


class PlexCompanion(backgroundthread.KillableThread):
    """
    Plex Companion monitoring class. Invoke only once
    """
    def __init__(self):
        LOG.info("----===## Starting PlexCompanion ##===----")
        # Init Plex Companion queue
        # Start GDM for server/client discovery
        self.client = plexgdm.plexgdm()
        self.client.clientDetails()
        LOG.debug("Registration string is:\n%s", self.client.getClientDetails())
        self.httpd = False
        self.subscription_manager = None
        super(PlexCompanion, self).__init__()

    @staticmethod
    def _process_alexa(data):
        app.PLAYSTATE.initiated_by_plex = True
        xml = PF.GetPlexMetadata(data['key'])
        try:
            xml[0].attrib
        except (AttributeError, IndexError, TypeError):
            LOG.error('Could not download Plex metadata for: %s', data)
            raise PL.PlaylistError()
        api = API(xml[0])
        if api.plex_type() == v.PLEX_TYPE_ALBUM:
            LOG.debug('Plex music album detected')
            xml = PF.GetAllPlexChildren(api.plex_id())
            try:
                xml[0].attrib
            except (TypeError, IndexError, AttributeError):
                LOG.error('Could not download the album xml for %s', data)
                raise PL.PlaylistError()
            playqueue = PQ.get_playqueue_from_type('audio')
            playqueue.init_from_xml(xml,
                                    transient_token=data.get('token'))
        elif data['containerKey'].startswith('/playQueues/'):
            _, container_key, _ = PF.ParseContainerKey(data['containerKey'])
            xml = PF.DownloadChunks('{server}/playQueues/%s' % container_key)
            if xml is None:
                LOG.error('Could not get playqueue for %s', data)
                raise PL.PlaylistError()
            playqueue = PQ.get_playqueue_from_type(
                v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[api.plex_type()])
            offset = utils.cast(float, data.get('offset')) or None
            if offset:
                offset = offset / 1000.0
            playqueue.init_from_xml(xml,
                                    offset=offset,
                                    transient_token=data.get('token'))
        else:
            app.CONN.plex_transient_token = data.get('token')
            if utils.cast(float, data.get('offset')):
                app.PLAYSTATE.resume_playback = True
            path = ('http://127.0.0.1:%s/plex/play/file.strm?plex_id=%s'
                    % (v.WEBSERVICE_PORT, api.plex_id()))
            path += '&plex_type=%s' % api.plex_type()
            executebuiltin(('PlayMedia(%s)' % path).encode('utf-8'))

    @staticmethod
    def _process_node(data):
        """
        E.g. watch later initiated by Companion. Basically navigating Plex
        """
        app.CONN.plex_transient_token = data.get('key')
        params = {
            'mode': 'plex_node',
            'key': '{server}%s' % data.get('key'),
            'offset': data.get('offset')
        }
        handle = 'RunPlugin(plugin://%s)' % utils.extend_url(v.ADDON_ID, params)
        executebuiltin(handle.encode('utf-8'))

    @staticmethod
    def _process_playlist(data):
        # Get the playqueue ID
        _, container_key, query = PF.ParseContainerKey(data['containerKey'])
        try:
            playqueue = PQ.get_playqueue_from_type(
                v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[data['type']])
        except KeyError:
            # E.g. Plex web does not supply the media type
            # Still need to figure out the type (video vs. music vs. pix)
            xml = PF.GetPlexMetadata(data['key'])
            try:
                xml[0].attrib
            except (AttributeError, IndexError, TypeError):
                LOG.error('Could not download Plex metadata')
                raise PL.PlaylistError()
            api = API(xml[0])
            playqueue = PQ.get_playqueue_from_type(
                v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[api.plex_type()])
        update_playqueue_from_PMS(playqueue,
                                  playqueue_id=container_key,
                                  repeat=query.get('repeat'),
                                  offset=utils.cast(float, data.get('offset')) or None,
                                  transient_token=data.get('token'))

    @staticmethod
    def _process_streams(data):
        """
        Plex Companion client adjusted audio or subtitle stream
        """
        playqueue = PQ.get_playqueue_from_type(
            v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[data['type']])
        try:
            pos = js.get_position(playqueue.playlistid)
            if 'audioStreamID' in data:
                index = playqueue.items[pos].kodi_stream_index(
                    data['audioStreamID'], 'audio')
                app.APP.player.setAudioStream(index)
            elif 'subtitleStreamID' in data:
                if data['subtitleStreamID'] == '0':
                    app.APP.player.showSubtitles(False)
                else:
                    index = playqueue.items[pos].kodi_stream_index(
                        data['subtitleStreamID'], 'subtitle')
                    app.APP.player.setSubtitleStream(index)
            else:
                LOG.error('Unknown setStreams command: %s', data)
        except KeyError:
            LOG.warn('Could not process stream data: %s', data)

    @staticmethod
    def _process_refresh(data):
        """
        example data: {'playQueueID': '8475', 'commandID': '11'}
        """
        xml = PL.get_pms_playqueue(data['playQueueID'])
        if xml is None:
            return
        if len(xml) == 0:
            LOG.debug('Empty playqueue received - clearing playqueue')
            plex_type = PL.get_plextype_from_xml(xml)
            if plex_type is None:
                return
            playqueue = PQ.get_playqueue_from_type(
                v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[plex_type])
            playqueue.clear()
            return
        playqueue = PQ.get_playqueue_from_type(
            v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[xml[0].attrib['type']])
        update_playqueue_from_PMS(playqueue, data['playQueueID'])

    def _process_tasks(self, task):
        """
        Processes tasks picked up e.g. by Companion listener, e.g.
        {'action': 'playlist',
         'data': {'address': 'xyz.plex.direct',
                  'commandID': '7',
                  'containerKey': '/playQueues/6669?own=1&repeat=0&window=200',
                  'key': '/library/metadata/220493',
                  'machineIdentifier': 'xyz',
                  'offset': '0',
                  'port': '32400',
                  'protocol': 'https',
                  'token': 'transient-cd2527d1-0484-48e0-a5f7-f5caa7d591bd',
                  'type': 'video'}}
        """
        LOG.debug('Processing: %s', task)
        data = task['data']
        try:
            if task['action'] == 'alexa':
                with app.APP.lock_playqueues:
                    self._process_alexa(data)
            elif (task['action'] == 'playlist' and
                    data.get('address') == 'node.plexapp.com'):
                self._process_node(data)
            elif task['action'] == 'playlist':
                with app.APP.lock_playqueues:
                    self._process_playlist(data)
            elif task['action'] == 'refreshPlayQueue':
                with app.APP.lock_playqueues:
                    self._process_refresh(data)
            elif task['action'] == 'setStreams':
                self._process_streams(data)
        except PL.PlaylistError:
            LOG.error('Could not process companion data: %s', data)
            # "Play Error"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(30128),
                         icon='{error}')
            app.PLAYSTATE.initiated_by_plex = False

    def run(self):
        """
        Ensure that sockets will be closed no matter what
        """
        app.APP.register_thread(self)
        try:
            self._run()
        finally:
            try:
                self.httpd.socket.shutdown(SHUT_RDWR)
            except AttributeError:
                pass
            finally:
                try:
                    self.httpd.socket.close()
                except AttributeError:
                    pass
            app.APP.deregister_thread(self)
            LOG.info("----===## Plex Companion stopped ##===----")

    def _run(self):
        httpd = self.httpd
        # Cache for quicker while loops
        client = self.client

        # Start up instances
        request_mgr = httppersist.RequestMgr()
        subscription_manager = subscribers.SubscriptionMgr(request_mgr,
                                                           app.APP.player)
        self.subscription_manager = subscription_manager

        if utils.settings('plexCompanion') == 'true':
            # Start up httpd
            start_count = 0
            while True:
                try:
                    httpd = listener.ThreadedHTTPServer(
                        client,
                        subscription_manager,
                        ('', v.COMPANION_PORT),
                        listener.MyHandler)
                    httpd.timeout = 0.95
                    break
                except Exception:
                    LOG.error("Unable to start PlexCompanion. Traceback:")
                    import traceback
                    LOG.error(traceback.print_exc())
                app.APP.monitor.waitForAbort(3)
                if start_count == 3:
                    LOG.error("Error: Unable to start web helper.")
                    httpd = False
                    break
                start_count += 1
        else:
            LOG.info('User deactivated Plex Companion')
        client.start_all()
        message_count = 0
        if httpd:
            thread = Thread(target=httpd.handle_request)

        while not self.isCanceled():
            # If we are not authorized, sleep
            # Otherwise, we trigger a download which leads to a
            # re-authorizations
            if self.wait_while_suspended():
                break
            try:
                message_count += 1
                if httpd:
                    if not thread.isAlive():
                        # Use threads cause the method will stall
                        thread = Thread(target=httpd.handle_request)
                        thread.start()

                    if message_count == 3000:
                        message_count = 0
                        if client.check_client_registration():
                            LOG.debug('Client is still registered')
                        else:
                            LOG.debug('Client is no longer registered. Plex '
                                      'Companion still running on port %s',
                                      v.COMPANION_PORT)
                            client.register_as_client()
                # Get and set servers
                if message_count % 30 == 0:
                    subscription_manager.serverlist = client.getServerList()
                    subscription_manager.notify()
                    if not httpd:
                        message_count = 0
            except Exception:
                LOG.warn("Error in loop, continuing anyway. Traceback:")
                import traceback
                LOG.warn(traceback.format_exc())
            # See if there's anything we need to process
            try:
                task = app.APP.companion_queue.get(block=False)
            except Empty:
                pass
            else:
                # Got instructions, process them
                self._process_tasks(task)
                app.APP.companion_queue.task_done()
                # Don't sleep
                continue
            app.APP.monitor.waitForAbort(0.05)
        subscription_manager.signal_stop()
        client.stop_all()
