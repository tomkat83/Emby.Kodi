#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from json import loads
from ssl import CERT_NONE

from . import backgroundthread, websocket, utils, companion, app, variables as v

###############################################################################

LOG = getLogger('PLEX.websocket_client')

###############################################################################


class WebSocket(backgroundthread.KillableThread):
    opcode_data = (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY)

    def __init__(self):
        self.ws = None
        self.redirect_uri = None
        self.sleeptime = 0.0
        super(WebSocket, self).__init__()

    def close_websocket(self):
        if self.ws is not None:
            self.ws.close()
            self.ws = None

    def process(self, opcode, message):
        raise NotImplementedError

    def receive(self, ws):
        # Not connected yet
        if ws is None:
            raise websocket.WebSocketConnectionClosedException

        frame = ws.recv_frame()

        if not frame:
            raise websocket.WebSocketException("Not a valid frame %s" % frame)
        elif frame.opcode in self.opcode_data:
            return frame.opcode, frame.data
        elif frame.opcode == websocket.ABNF.OPCODE_CLOSE:
            ws.send_close()
            return frame.opcode, None
        elif frame.opcode == websocket.ABNF.OPCODE_PING:
            ws.pong("Hi!")
        return None, None

    def getUri(self):
        raise NotImplementedError

    def _sleep_cycle(self):
        """
        Sleeps for 2^self.sleeptime where sleeping period will be doubled with
        each unsuccessful connection attempt.
        Will sleep at most 64 seconds
        """
        self.sleep(2 ** self.sleeptime)
        if self.sleeptime < 6:
            self.sleeptime += 1.0

    def run(self):
        LOG.info("----===## Starting %s ##===----", self.__class__.__name__)
        app.APP.register_thread(self)
        try:
            self._run()
        finally:
            self.close_websocket()
            app.APP.deregister_thread(self)
            LOG.info("##===---- %s Stopped ----===##", self.__class__.__name__)

    def _run(self):
        while not self.should_cancel():
            # In the event the server goes offline
            if self.should_suspend():
                # Set in service.py
                self.close_websocket()
                if self.wait_while_suspended():
                    # Abort was requested while waiting. We should exit
                    return
            try:
                self.process(*self.receive(self.ws))
            except websocket.WebSocketTimeoutException:
                # No worries if read timed out
                pass
            except websocket.WebSocketConnectionClosedException:
                LOG.debug("%s: connection closed, (re)connecting",
                          self.__class__.__name__)
                uri, sslopt = self.getUri()
                try:
                    # Low timeout - let's us shut this thread down!
                    self.ws = websocket.create_connection(
                        uri,
                        timeout=1,
                        sslopt=sslopt,
                        enable_multithread=True)
                except IOError:
                    # Server is probably offline
                    LOG.debug("%s: IOError connecting", self.__class__.__name__)
                    self.ws = None
                    self._sleep_cycle()
                except websocket.WebSocketTimeoutException:
                    LOG.debug("%s: WebSocketTimeoutException", self.__class__.__name__)
                    self.ws = None
                    self._sleep_cycle()
                except websocket.WebsocketRedirect as e:
                    LOG.debug('301 redirect detected: %s', e)
                    self.redirect_uri = e.headers.get('location',
                                                      e.headers.get('Location'))
                    if self.redirect_uri:
                        self.redirect_uri = self.redirect_uri.decode('utf-8')
                    self.ws = None
                    self._sleep_cycle()
                except websocket.WebSocketException as e:
                    LOG.debug('%s: WebSocketException: %s', self.__class__.__name__, e)
                    self.ws = None
                    self._sleep_cycle()
                except Exception as e:
                    LOG.error('%s: Unknown exception encountered when '
                              'connecting: %s', self.__class__.__name__, e)
                    import traceback
                    LOG.error("%s: Traceback:\n%s",
                              self.__class__.__name__, traceback.format_exc())
                    self.ws = None
                    self._sleep_cycle()
                else:
                    self.sleeptime = 0.0
            except Exception as e:
                LOG.error("%s: Unknown exception encountered: %s",
                          self.__class__.__name__, e)
                import traceback
                LOG.error("%s: Traceback:\n%s",
                          self.__class__.__name__, traceback.format_exc())
                self.close_websocket()


class PMS_Websocket(WebSocket):
    """
    Websocket connection with the PMS for Plex Companion
    """
    def should_suspend(self):
        """
        Returns True if the thread is suspended.
        """
        suspend = self._suspended or app.SYNC.background_sync_disabled
        if suspend:
            # This thread needs to clear the Event() _is_not_suspended itself!
            self.suspend()
        return suspend

    def getUri(self):
        if self.redirect_uri:
            uri = self.redirect_uri
            self.redirect_uri = None
        else:
            server = app.CONN.server
            # Get the appropriate prefix for the websocket
            if server.startswith('https'):
                server = "wss%s" % server[5:]
            else:
                server = "ws%s" % server[4:]
            uri = "%s/:/websockets/notifications" % server
            if app.ACCOUNT.pms_token:
                uri += '?X-Plex-Token=%s' % app.ACCOUNT.pms_token
        sslopt = {}
        LOG.debug("%s: Uri: %s, sslopt: %s",
                  self.__class__.__name__, uri, sslopt)
        return uri, sslopt

    def process(self, opcode, message):
        if opcode not in self.opcode_data:
            return

        try:
            message = loads(message)
        except ValueError:
            LOG.error('%s: Error decoding message from websocket',
                      self.__class__.__name__)
            LOG.error(message)
            return
        try:
            message = message['NotificationContainer']
        except KeyError:
            LOG.error('%s: Could not parse PMS message: %s',
                      self.__class__.__name__, message)
            return
        # Triage
        typus = message.get('type')
        if typus is None:
            LOG.error('%s: No message type, dropping message: %s',
                      self.__class__.__name__, message)
            return
        LOG.debug('%s: Received message from PMS server: %s',
                  self.__class__.__name__, message)
        # Drop everything we're not interested in
        if typus not in ('playing', 'timeline', 'activity'):
            return
        else:
            # Put PMS message on queue and let libsync take care of it
            app.APP.websocket_queue.put(message)


class Alexa_Websocket(WebSocket):
    """
    Websocket connection to talk to Amazon Alexa.
    """
    def should_suspend(self):
        """
        Overwrite method since we need to check for plex token
        """
        suspend = self._suspended or \
            not app.SYNC.enable_alexa or \
            app.ACCOUNT.restricted_user or \
            not app.ACCOUNT.plex_token
        if suspend:
            # This thread needs to clear the Event() _is_not_suspended itself!
            self.suspend()
        return suspend

    def getUri(self):
        if self.redirect_uri:
            uri = self.redirect_uri
            self.redirect_uri = None
        else:
            uri = ('wss://pubsub.plex.tv/sub/websockets/%s/%s?X-Plex-Token=%s'
                   % (app.ACCOUNT.plex_user_id,
                      v.PKC_MACHINE_IDENTIFIER,
                      app.ACCOUNT.plex_token))
        sslopt = {}
        LOG.debug("%s: Uri: %s, sslopt: %s",
                  self.__class__.__name__, uri, sslopt)
        return uri, sslopt

    def process(self, opcode, message):
        if opcode not in self.opcode_data:
            return
        LOG.debug('%s: Received the following message from Alexa:',
                  self.__class__.__name__)
        LOG.debug('%s: %s', self.__class__.__name__, message)
        try:
            message = utils.etree.fromstring(message)
        except Exception as ex:
            LOG.error('%s: Error decoding message from Alexa: %s',
                      self.__class__.__name__, ex)
            return
        try:
            if message.attrib['command'] == 'processRemoteControlCommand':
                message = message[0]
            else:
                LOG.error('%s: Unknown Alexa message received',
                          self.__class__.__name__)
                return
        except Exception:
            LOG.error('%s: Could not parse Alexa message',
                      self.__class__.__name__)
            return
        companion.process_command(message.attrib['path'][1:], message.attrib)
