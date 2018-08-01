#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from json import loads
import xml.etree.ElementTree as etree
from threading import Thread
from ssl import CERT_NONE
from xbmc import sleep

from . import websocket, utils, companion, state, variables as v

###############################################################################

LOG = getLogger('PLEX.websocket_client')

###############################################################################


class WebSocket(Thread):
    opcode_data = (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY)

    def __init__(self):
        self.ws = None
        super(WebSocket, self).__init__()

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

    def run(self):
        LOG.info("----===## Starting %s ##===----", self.__class__.__name__)

        counter = 0
        stopped = self.stopped
        suspended = self.suspended
        while not stopped():
            # In the event the server goes offline
            while suspended():
                # Set in service.py
                if self.ws is not None:
                    self.ws.close()
                    self.ws = None
                if stopped():
                    # Abort was requested while waiting. We should exit
                    LOG.info("##===---- %s Stopped ----===##",
                             self.__class__.__name__)
                    return
                sleep(1000)
            try:
                self.process(*self.receive(self.ws))
            except websocket.WebSocketTimeoutException:
                # No worries if read timed out
                pass
            except websocket.WebSocketConnectionClosedException:
                LOG.info("%s: connection closed, (re)connecting",
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
                    LOG.info("%s: Error connecting", self.__class__.__name__)
                    self.ws = None
                    counter += 1
                    if counter >= 10:
                        LOG.info('%s: Repeated IOError detected. Stopping now',
                                 self.__class__.__name__)
                        break
                    sleep(1000)
                except websocket.WebSocketTimeoutException:
                    LOG.info("%s: Timeout while connecting, trying again",
                             self.__class__.__name__)
                    self.ws = None
                    sleep(1000)
                except websocket.WebSocketException as e:
                    LOG.info('%s: WebSocketException: %s',
                             self.__class__.__name__, e)
                    if ('Handshake Status 401' in e.args or
                            'Handshake Status 403' in e.args):
                        counter += 1
                        if counter >= 5:
                            LOG.info('%s: Error in handshake detected. '
                                     'Stopping now', self.__class__.__name__)
                            break
                    self.ws = None
                    sleep(1000)
                except Exception as e:
                    LOG.error('%s: Unknown exception encountered when '
                              'connecting: %s', self.__class__.__name__, e)
                    import traceback
                    LOG.error("%s: Traceback:\n%s",
                              self.__class__.__name__, traceback.format_exc())
                    self.ws = None
                    sleep(1000)
                else:
                    counter = 0
            except Exception as e:
                LOG.error("%s: Unknown exception encountered: %s",
                          self.__class__.__name__, e)
                import traceback
                LOG.error("%s: Traceback:\n%s",
                          self.__class__.__name__, traceback.format_exc())
                if self.ws is not None:
                    self.ws.close()
                self.ws = None
        # Close websocket connection on shutdown
        if self.ws is not None:
            self.ws.close()
        LOG.info("##===---- %s Stopped ----===##", self.__class__.__name__)


@utils.thread_methods(add_suspends=['SUSPEND_LIBRARY_THREAD',
                                    'BACKGROUND_SYNC_DISABLED'])
class PMS_Websocket(WebSocket):
    """
    Websocket connection with the PMS for Plex Companion
    """
    def getUri(self):
        server = utils.window('pms_server')
        # Get the appropriate prefix for the websocket
        if server.startswith('https'):
            server = "wss%s" % server[5:]
        else:
            server = "ws%s" % server[4:]
        uri = "%s/:/websockets/notifications" % server
        # Need to use plex.tv token, if any. NOT user token
        if state.PLEX_TOKEN:
            uri += '?X-Plex-Token=%s' % state.PLEX_TOKEN
        sslopt = {}
        if utils.settings('sslverify') == "false":
            sslopt["cert_reqs"] = CERT_NONE
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
        elif typus == 'activity' and state.DB_SCAN is True:
            # Only add to processing if PKC is NOT doing a lib scan (and thus
            # possibly causing these reprocessing messages en mass)
            LOG.debug('%s: Dropping message as PKC is currently synching',
                      self.__class__.__name__)
        else:
            # Put PMS message on queue and let libsync take care of it
            state.WEBSOCKET_QUEUE.put(message)


class Alexa_Websocket(WebSocket):
    """
    Websocket connection to talk to Amazon Alexa.

    Can't use utils.thread_methods!
    """
    thread_stopped = False
    thread_suspended = False

    def getUri(self):
        uri = ('wss://pubsub.plex.tv/sub/websockets/%s/%s?X-Plex-Token=%s'
               % (state.PLEX_USER_ID,
                  v.PKC_MACHINE_IDENTIFIER,
                  state.PLEX_TOKEN))
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
            message = etree.fromstring(message)
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
        except:
            LOG.error('%s: Could not parse Alexa message',
                      self.__class__.__name__)
            return
        companion.process_command(message.attrib['path'][1:], message.attrib)

    # Path in utils.thread_methods
    def stop(self):
        self.thread_stopped = True

    def suspend(self):
        self.thread_suspended = True

    def resume(self):
        self.thread_suspended = False

    def stopped(self):
        if self.thread_stopped is True:
            return True
        if state.STOP_PKC:
            return True
        return False

    # The culprit
    def suspended(self):
        """
        Overwrite method since we need to check for plex token
        """
        if self.thread_suspended is True:
            return True
        if not state.PLEX_TOKEN:
            return True
        if state.RESTRICTED_USER:
            return True
        return False
