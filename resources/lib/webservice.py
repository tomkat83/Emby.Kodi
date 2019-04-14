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

from . import backgroundthread, utils, variables as v, app
from .playstrm import PlayStrm


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
            xbmc.log('Plex.WebService abort error: %s' % error, xbmc.LOGWARNING)

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
            xbmc.log('Plex.WebService handle error: %s' % error, xbmc.LOGWARNING)

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
            params = {}
        if '?' in path:
            path = path.split('?', 1)[1]
        params = dict(utils.parse_qsl(path))

        if params.get('transcode'):
            params['transcode'] = params['transcode'].lower() == 'true'
        if params.get('server') and params['server'].lower() == 'none':
            params['server'] = None

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
        xbmc.log('Plex.WebService handle_request called. headers %s, path: %s'
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
        xbmc.log('PLEX.webservice: sending %s' % path, xbmc.LOGDEBUG)
        self.wfile.write(bytes(path.encode('utf-8')))
        if params['plex_id'] not in self.server.pending:
            xbmc.log('PLEX.webservice: path %s params %s' % (self.path, params),
                     xbmc.LOGDEBUG)

            self.server.pending.append(params['plex_id'])
            self.server.queue.put(params)
            if not len(self.server.threads):
                queue = QueuePlay(self.server)
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

    def __init__(self, server):
        self.server = server
        super(QueuePlay, self).__init__()

    def run(self):
        LOG.info('##===---- Starting QueuePlay ----===##')
        play_folder = False
        play = None
        start_position = None
        position = None

        # Let Kodi catch up
        xbmc.sleep(200)

        while True:

            try:
                try:
                    params = self.server.queue.get(timeout=0.01)
                except Queue.Empty:
                    count = 20
                    while not utils.window('plex.playlist.ready'):
                        xbmc.sleep(50)
                        if not count:
                            LOG.info('Playback aborted')
                            raise Exception('PlaybackAborted')
                        count -= 1
                    LOG.info('Starting playback at position: %s', start_position)
                    if play_folder:
                        LOG.info('Start playing folder')
                        xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                        play.start_playback()
                    else:
                        utils.window('plex.playlist.play', value='true')
                        # xbmc.sleep(1000)
                        play.remove_from_playlist(start_position)
                    break
                play = PlayStrm(params, params.get('ServerId'))

                if start_position is None:
                    start_position = max(play.kodi_playlist.getposition(), 0)
                    position = start_position + 1
                if play_folder:
                    position = play.play_folder(position)
                else:
                    if self.server.pending.count(params['plex_id']) != len(self.server.pending):
                        play_folder = True
                    utils.window('plex.playlist.start', str(start_position))
                    position = play.play(position)
                    if play_folder:
                        xbmc.executebuiltin('Activateutils.window(busydialognocancel)')
            except Exception:
                utils.ERROR()
                play.kodi_playlist.clear()
                xbmc.Player().stop()
                self.server.queue.queue.clear()
                if play_folder:
                    xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
                else:
                    utils.window('plex.playlist.aborted', value='true')
                break
            self.server.queue.task_done()

        utils.window('plex.playlist.ready', clear=True)
        utils.window('plex.playlist.start', clear=True)
        app.PLAYSTATE.audioplaylist = None
        self.server.threads.remove(self)
        self.server.pending = []
        LOG.info('##===---- QueuePlay Stopped ----===##')
