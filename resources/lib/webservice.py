# -*- coding: utf-8 -*-
'''
PKC-dedicated webserver. Listens to Kodi starting playback; will then hand-over
playback to plugin://video.plexkodiconnect
'''
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import BaseHTTPServer
import httplib
import socket
import Queue

import xbmc
import xbmcvfs

from .plex_api import API
from .plex_db import PlexDB
from . import backgroundthread, utils, variables as v, app, playqueue as PQ
from . import json_rpc as js, plex_functions as PF


LOG = getLogger('PLEX.webservice')


class WebService(backgroundthread.KillableThread):
    ''' Run a webservice to trigger playback.
    '''
    def is_alive(self):
        ''' Called to see if the webservice is still responding.
        '''
        alive = True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(('127.0.0.1', v.WEBSERVICE_PORT))
            s.sendall('')
        except Exception as error:
            LOG.error('is_alive error: %s', error)
            if 'Errno 61' in str(error):
                alive = False
        s.close()
        return alive

    def abort(self):
        ''' Called when the thread needs to stop
        '''
        try:
            conn = httplib.HTTPConnection('127.0.0.1:%d' % v.WEBSERVICE_PORT)
            conn.request('QUIT', '/')
            conn.getresponse()
        except Exception as error:
            xbmc.log('PLEX.webservice abort error: %s' % error, xbmc.LOGWARNING)

    def suspend(self):
        """
        Called when thread needs to suspend - let's not do anything and keep
        webservice up
        """
        self.suspend_reached = True

    def resume(self):
        """
        Called when thread needs to resume - let's not do anything and keep
        webservice up
        """
        self.suspend_reached = False

    def run(self):
        ''' Called to start the webservice.
        '''
        LOG.info('----===## Starting WebService on port %s ##===----',
                 v.WEBSERVICE_PORT)
        app.APP.register_thread(self)
        try:
            server = HttpServer(('127.0.0.1', v.WEBSERVICE_PORT),
                                RequestHandler)
            LOG.info('Serving http on %s', server.socket.getsockname())
            server.serve_forever()
        except Exception as error:
            LOG.error('Error encountered: %s', error)
            if '10053' not in error:  # ignore host diconnected errors
                utils.ERROR()
        finally:
            app.APP.deregister_thread(self)
            LOG.info('##===---- WebService stopped ----===##')


class HttpServer(BaseHTTPServer.HTTPServer):
    ''' Http server that reacts to self.stop flag.
    '''
    def __init__(self, *args, **kwargs):
        self.stop = False
        self.pending = []
        self.threads = []
        self.queue = Queue.Queue()
        BaseHTTPServer.HTTPServer.__init__(self, *args, **kwargs)

    def serve_forever(self):

        ''' Handle one request at a time until stopped.
        '''
        while not self.stop:
            self.handle_request()


class RequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    '''
    Http request handler. Do not use LOG here, it will hang requests in Kodi >
    show information dialog.
    '''
    timeout = 0.5

    def log_message(self, format, *args):
        ''' Mute the webservice requests.
        '''
        pass

    def handle(self):
        ''' To quiet socket errors with 404.
        '''
        try:
            BaseHTTPServer.BaseHTTPRequestHandler.handle(self)
        except Exception as error:
            if '10054' in error:
                # Silence "[Errno 10054] An existing connection was forcibly
                # closed by the remote host"
                return
            xbmc.log('PLEX.webservice handle error: %s' % error, xbmc.LOGWARNING)

    def do_QUIT(self):
        ''' send 200 OK response, and set server.stop to True
        '''
        self.send_response(200)
        self.end_headers()
        self.server.stop = True

    def get_params(self):
        ''' Get the params as a dict
        '''
        try:
            path = self.path[1:].decode('utf-8')
        except IndexError:
            path = ''
            params = {}
        if '?' in path:
            path = path.split('?', 1)[1]
        params = dict(utils.parse_qsl(path))
        if 'plex_id' not in params:
            LOG.error('No plex_id received for path %s', path)
            return

        if 'plex_type' in params and params['plex_type'].lower() == 'none':
            del params['plex_type']
        if 'plex_type' not in params:
            LOG.debug('Need to look-up plex_type')
            with PlexDB(lock=False) as plexdb:
                db_item = plexdb.item_by_id(params['plex_id'])
            if db_item:
                params['plex_type'] = db_item['plex_type']
            else:
                LOG.debug('No plex_type found, using Kodi player id')
                players = js.get_players()
                if players:
                    params['plex_type'] = v.PLEX_TYPE_CLIP if 'video' in players \
                        else v.PLEX_TYPE_SONG
                    LOG.debug('Using the following plex_type: %s',
                              params['plex_type'])
                else:
                    xml = PF.GetPlexMetadata(params['plex_id'])
                    if xml in (None, 401):
                        LOG.error('Could not get metadata for %s', params)
                        return
                    api = API(xml[0])
                    params['plex_type'] = api.plex_type()
                    LOG.debug('Got metadata, using plex_type %s',
                              params['plex_type'])
        return params

    def do_HEAD(self):
        ''' Called on HEAD requests
        '''
        self.handle_request(True)

    def do_GET(self):
        ''' Called on GET requests
        '''
        self.handle_request()

    def handle_request(self, headers_only=False):
        '''Send headers and reponse
        '''
        xbmc.log('PLEX.webservice handle_request called. headers %s, path: %s'
                 % (headers_only, self.path), xbmc.LOGDEBUG)
        try:
            if b'extrafanart' in self.path or b'extrathumbs' in self.path:
                raise Exception('unsupported artwork request')

            if headers_only:
                self.send_response(200)
                self.send_header(b'Content-type', b'text/html')
                self.end_headers()

            elif b'file.strm' not in self.path:
                self.images()
            else:
                self.strm()

        except Exception as error:
            self.send_error(500,
                            b'PLEX.webservice: Exception occurred: %s' % error)

    def strm(self):
        ''' Return a dummy video and and queue real items.
        '''
        xbmc.log('PLEX.webservice: starting strm', xbmc.LOGDEBUG)
        self.send_response(200)
        self.send_header(b'Content-type', b'text/html')
        self.end_headers()

        params = self.get_params()

        if b'kodi/movies' in self.path:
            params['kodi_type'] = v.KODI_TYPE_MOVIE
        elif b'kodi/tvshows' in self.path:
            params['kodi_type'] = v.KODI_TYPE_EPISODE
        # elif 'kodi/musicvideos' in self.path:
        #     params['MediaType'] = 'musicvideo'

        if utils.settings('pluginSingle.bool'):
            path = 'plugin://plugin.video.plexkodiconnect?mode=playsingle&plex_id=%s' % params['plex_id']
            if params.get('server'):
                path += '&server=%s' % params['server']
            if params.get('transcode'):
                path += '&transcode=true'
            if params.get('kodi_id'):
                path += '&kodi_id=%s' % params['kodi_id']
            if params.get('kodi_type'):
                path += '&kodi_type=%s' % params['kodi_type']
            self.wfile.write(bytes(path))
            return

        path = 'plugin://plugin.video.plexkodiconnect?mode=playstrm&plex_id=%s' % params['plex_id']
        self.wfile.write(bytes(path.encode('utf-8')))
        if params['plex_id'] not in self.server.pending:
            self.server.pending.append(params['plex_id'])
            self.server.queue.put(params)
            if not len(self.server.threads):
                queue = QueuePlay(self.server, params['plex_type'])
                queue.start()
                self.server.threads.append(queue)

    def images(self):
        ''' Return a dummy image for unwanted images requests over the webservice.
            Required to prevent freezing of widget playback if the file url has no
            local textures cached yet.
        '''
        image = xbmc.translatePath(
            'special://home/addons/plugin.video.plexkodiconnect/icon.png').decode('utf-8')
        self.send_response(200)
        self.send_header(b'Content-type', b'image/png')
        modified = xbmcvfs.Stat(image).st_mtime()
        self.send_header(b'Last-Modified', b'%s' % modified)
        image = xbmcvfs.File(image)
        size = image.size()
        self.send_header(b'Content-Length', str(size))
        self.end_headers()
        self.wfile.write(image.readBytes())
        image.close()


class QueuePlay(backgroundthread.KillableThread):
    ''' Workflow for new playback:

        Queue up strm playback that was called in the webservice. Called
        playstrm in default.py which will wait for our signal here. Downloads
        plex information. Add content to the playlist after the strm file that
        initiated playback from db. Start playback by telling playstrm waiting.
        It will fail playback of the current strm and move to the next entry for
        us. If play folder, playback starts here.

        Required delay for widgets, custom skin containers and non library
        windows. Otherwise Kodi will freeze if no artwork textures are cached
        yet in Textures13.db Will be skipped if the player already has media and
        is playing.

        Why do all this instead of using plugin? Strms behaves better than
        plugin in database. Allows to load chapter images with direct play.
        Allows to have proper artwork for intros. Faster than resolving using
        plugin, especially on low powered devices. Cons: Can't use external
        players with this method.
    '''

    def __init__(self, server, plex_type):
        self.server = server
        self.plex_type = plex_type
        self.plex_id = None
        self.kodi_id = None
        self.kodi_type = None
        self.synched = True
        self.force_transcode = False
        super(QueuePlay, self).__init__()

    def load_params(self, params):
        self.plex_id = utils.cast(int, params['plex_id'])
        self.plex_type = params.get('plex_type')
        self.kodi_id = utils.cast(int, params.get('kodi_id'))
        self.kodi_type = params.get('kodi_type')
        # Some cleanup
        if params.get('transcode'):
            self.force_transcode = params['transcode'].lower() == 'true'
        if params.get('server') and params['server'].lower() == 'none':
            self.server = None
        if params.get('synched'):
            self.synched = not params['synched'].lower() == 'false'

    def _get_playqueue(self):
        playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_VIDEO)
        if ((self.plex_type in v.PLEX_VIDEOTYPES and
             not app.PLAYSTATE.initiated_by_plex and
             xbmc.getCondVisibility('Window.IsVisible(Home.xml)'))):
            # Video launched from a widget - which starts a Kodi AUDIO playlist
            # We will empty everything and start with a fresh VIDEO playlist
            LOG.debug('Widget video playback detected')
            video_widget_playback = True
            # Release default.py
            utils.window('plex.playlist.play', value='true')
            # The playlist will be ready anyway
            app.PLAYSTATE.playlist_ready = True
            playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_AUDIO)
            playqueue.clear()
            playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_VIDEO)
            playqueue.clear()
            # Wait for Kodi to catch up - xbmcplugin.setResolvedUrl() needs to
            # have run its course and thus the original item needs to have
            # failed before we start playback anew
            xbmc.sleep(200)
        else:
            video_widget_playback = False
            if self.plex_type in v.PLEX_VIDEOTYPES:
                LOG.debug('Video playback detected')
                playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_VIDEO)
            else:
                LOG.debug('Audio playback detected')
                playqueue = PQ.get_playqueue_from_type(v.KODI_TYPE_AUDIO)
        return playqueue, video_widget_playback

    def run(self):
        with app.APP.lock_playqueues:
            LOG.debug('##===---- Starting QueuePlay ----===##')
            try:
                self._run()
            finally:
                app.PLAYSTATE.playlist_ready = False
                app.PLAYSTATE.playlist_start_pos = None
                app.PLAYSTATE.initiated_by_plex = False
                self.server.threads.remove(self)
                self.server.pending = []
                LOG.debug('##===---- QueuePlay Stopped ----===##')

    def _run(self):
        abort = False
        play_folder = False
        playqueue, video_widget_playback = self._get_playqueue()
        # Position to start playback from (!!)
        # Do NOT use kodi_pl.getposition() as that appears to be buggy
        try:
            start_position = max(js.get_position(playqueue.playlistid), 0)
        except KeyError:
            # Widgets: Since we've emptied the entire playlist, we won't get a
            # position
            start_position = 0
        # Position to add next element to queue - we're doing this at the end
        # of our current playqueue
        position = playqueue.kodi_pl.size()
        # Set to start_position + 1 because first item will fail
        app.PLAYSTATE.playlist_start_pos = start_position + 1
        LOG.debug('start_position %s, position %s for current playqueue: %s',
                  start_position, position, playqueue)
        while True:
            try:
                try:
                    # We cannot know when Kodi will send the last item, e.g.
                    # when playing an entire folder
                    params = self.server.queue.get(timeout=0.01)
                except Queue.Empty:
                    LOG.debug('Wrapping up')
                    if xbmc.getCondVisibility('VideoPlayer.Content(livetv)'):
                        # avoid issues with ongoing Live TV playback
                        app.APP.player.stop()
                    count = 50
                    while not app.PLAYSTATE.playlist_ready:
                        xbmc.sleep(50)
                        if not count:
                            LOG.info('Playback aborted')
                            raise Exception('Playback aborted')
                        count -= 1
                    if play_folder:
                        LOG.info('Start playing folder')
                        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                        playqueue.start_playback(start_position)
                    elif video_widget_playback:
                        LOG.info('Start widget video playback')
                        playqueue.start_playback()
                    else:
                        LOG.info('Start normal playback')
                        # Release default.py
                        utils.window('plex.playlist.play', value='true')
                        if not app.PLAYSTATE.initiated_by_plex:
                            # Remove the playlist element we just added with the
                            # right path
                            xbmc.sleep(1000)
                            playqueue.kodi_remove_item(start_position)
                            del playqueue.items[start_position]
                    LOG.debug('Done wrapping up')
                    break
                self.load_params(params)
                if play_folder:
                    playlistitem = PQ.PlaylistItem(plex_id=self.plex_id,
                                                   plex_type=self.plex_type,
                                                   kodi_id=self.kodi_id,
                                                   kodi_type=self.kodi_type)
                    playlistitem.force_transcode = self.force_transcode
                    playqueue.add_item(playlistitem, position)
                    position += 1
                else:
                    if self.server.pending.count(params['plex_id']) != len(self.server.pending):
                        # E.g. when selecting "play" for an entire video genre
                        LOG.debug('Folder playback detected')
                        play_folder = True
                        xbmc.executebuiltin('Activateutils.window(busydialognocancel)')
                    playqueue.play(self.plex_id,
                                   plex_type=self.plex_type,
                                   startpos=start_position,
                                   position=position,
                                   synched=self.synched,
                                   force_transcode=self.force_transcode)
                    # Do NOT start playback here - because Kodi already started
                    # it!
                    position = playqueue.index
            except Exception:
                abort = True
                utils.ERROR(notify=True)
            try:
                self.server.queue.task_done()
            except ValueError:
                # "task_done() called too many times" when aborting
                pass
            if abort:
                app.APP.player.stop()
                playqueue.clear()
                self.server.queue.queue.clear()
                if play_folder:
                    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                else:
                    utils.window('plex.playlist.aborted', value='true')
                break
