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
from urllib import urlencode
from xbmc import sleep, executebuiltin, Player

from .plexbmchelper import listener, plexgdm, subscribers, httppersist
from .plex_api import API
from . import utils
from . import plex_functions as PF
from . import playlist_func as PL
from . import playback
from . import json_rpc as js
from . import playqueue as PQ
from . import variables as v
from . import state

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
    """
    LOG.info('New playqueue %s received from Plex companion with offset '
             '%s, repeat %s', playqueue_id, offset, repeat)
    # Safe transient token from being deleted
    if transient_token is None:
        transient_token = playqueue.plex_transient_token
    with state.LOCK_PLAYQUEUES:
        xml = PL.get_PMS_playlist(playqueue, playqueue_id)
        try:
            xml.attrib
        except AttributeError:
            LOG.error('Could now download playqueue %s', playqueue_id)
            return
        playqueue.clear()
        try:
            PL.get_playlist_details_from_xml(playqueue, xml)
        except PL.PlaylistError:
            LOG.error('Could not get playqueue ID %s', playqueue_id)
            return
        playqueue.repeat = 0 if not repeat else int(repeat)
        playqueue.plex_transient_token = transient_token
        playback.play_xml(playqueue, xml, offset)


@utils.thread_methods(add_suspends=['PMS_STATUS'])
class PlexCompanion(Thread):
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
        # kodi player instance
        self.player = Player()
        self.httpd = False
        self.subscription_manager = None
        Thread.__init__(self)

    def _process_alexa(self, data):
        xml = PF.GetPlexMetadata(data['key'])
        try:
            xml[0].attrib
        except (AttributeError, IndexError, TypeError):
            LOG.error('Could not download Plex metadata for: %s', data)
            return
        api = API(xml[0])
        if api.plex_type() == v.PLEX_TYPE_ALBUM:
            LOG.debug('Plex music album detected')
            PQ.init_playqueue_from_plex_children(
                api.plex_id(),
                transient_token=data.get('token'))
        elif data['containerKey'].startswith('/playQueues/'):
            _, container_key, _ = PF.ParseContainerKey(data['containerKey'])
            xml = PF.DownloadChunks('{server}/playQueues/%s?' % container_key)
            if xml is None:
                # "Play error"
                utils.dialog('notification',
                             utils.lang(29999),
                             utils.lang(30128),
                             icon='{error}')
                return
            playqueue = PQ.get_playqueue_from_type(
                v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[api.plex_type()])
            playqueue.clear()
            PL.get_playlist_details_from_xml(playqueue, xml)
            playqueue.plex_transient_token = data.get('token')
            if data.get('offset') != '0':
                offset = float(data['offset']) / 1000.0
            else:
                offset = None
            playback.play_xml(playqueue, xml, offset)
        else:
            state.PLEX_TRANSIENT_TOKEN = data.get('token')
            if data.get('offset') != '0':
                state.RESUMABLE = True
                state.RESUME_PLAYBACK = True
            playback.playback_triage(api.plex_id(),
                                     api.plex_type(),
                                     resolve=False)

    @staticmethod
    def _process_node(data):
        """
        E.g. watch later initiated by Companion. Basically navigating Plex
        """
        state.PLEX_TRANSIENT_TOKEN = data.get('key')
        params = {
            'mode': 'plex_node',
            'key': '{server}%s' % data.get('key'),
            'offset': data.get('offset')
        }
        executebuiltin('RunPlugin(plugin://%s?%s)'
                       % (v.ADDON_ID, urlencode(params)))

    def _process_playlist(self, data):
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
                return
            api = API(xml[0])
            playqueue = PQ.get_playqueue_from_type(
                v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[api.plex_type()])
        update_playqueue_from_PMS(playqueue,
                                  playqueue_id=container_key,
                                  repeat=query.get('repeat'),
                                  offset=data.get('offset'),
                                  transient_token=data.get('token'))

    def _process_streams(self, data):
        """
        Plex Companion client adjusted audio or subtitle stream
        """
        playqueue = PQ.get_playqueue_from_type(
            v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[data['type']])
        pos = js.get_position(playqueue.playlistid)
        if 'audioStreamID' in data:
            index = playqueue.items[pos].kodi_stream_index(
                data['audioStreamID'], 'audio')
            self.player.setAudioStream(index)
        elif 'subtitleStreamID' in data:
            if data['subtitleStreamID'] == '0':
                self.player.showSubtitles(False)
            else:
                index = playqueue.items[pos].kodi_stream_index(
                    data['subtitleStreamID'], 'subtitle')
                self.player.setSubtitleStream(index)
        else:
            LOG.error('Unknown setStreams command: %s', data)

    def _process_refresh(self, data):
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
        if task['action'] == 'alexa':
            with state.LOCK_PLAYQUEUES:
                self._process_alexa(data)
        elif (task['action'] == 'playlist' and
                data.get('address') == 'node.plexapp.com'):
            self._process_node(data)
        elif task['action'] == 'playlist':
            with state.LOCK_PLAYQUEUES:
                self._process_playlist(data)
        elif task['action'] == 'refreshPlayQueue':
            with state.LOCK_PLAYQUEUES:
                self._process_refresh(data)
        elif task['action'] == 'setStreams':
            try:
                self._process_streams(data)
            except KeyError:
                pass

    def run(self):
        """
        Ensure that sockets will be closed no matter what
        """
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
        LOG.info("----===## Plex Companion stopped ##===----")

    def _run(self):
        httpd = self.httpd
        # Cache for quicker while loops
        client = self.client
        stopped = self.stopped
        suspended = self.suspended

        # Start up instances
        request_mgr = httppersist.RequestMgr()
        subscription_manager = subscribers.SubscriptionMgr(request_mgr,
                                                           self.player)
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
                except:
                    LOG.error("Unable to start PlexCompanion. Traceback:")
                    import traceback
                    LOG.error(traceback.print_exc())
                sleep(3000)
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

        while not stopped():
            # If we are not authorized, sleep
            # Otherwise, we trigger a download which leads to a
            # re-authorizations
            while suspended():
                if stopped():
                    break
                sleep(1000)
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
            except:
                LOG.warn("Error in loop, continuing anyway. Traceback:")
                import traceback
                LOG.warn(traceback.format_exc())
            # See if there's anything we need to process
            try:
                task = state.COMPANION_QUEUE.get(block=False)
            except Empty:
                pass
            else:
                # Got instructions, process them
                self._process_tasks(task)
                state.COMPANION_QUEUE.task_done()
                # Don't sleep
                continue
            sleep(50)
        subscription_manager.signal_stop()
        client.stop_all()
