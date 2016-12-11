# -*- coding: utf-8 -*-

###############################################################################
import logging
import json
import threading
import Queue
import websocket
import ssl

import xbmc

from utils import window, settings, ThreadMethodsAdditionalSuspend, \
    ThreadMethods

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


@ThreadMethodsAdditionalSuspend('suspend_LibraryThread')
@ThreadMethods
class WebSocket(threading.Thread):
    opcode_data = (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY)

    def __init__(self, queue):
        self.ws = None
        # Communication with librarysync
        self.queue = queue
        threading.Thread.__init__(self)

    def process(self, opcode, message):
        if opcode not in self.opcode_data:
            return False

        try:
            message = json.loads(message)
        except Exception as ex:
            log.error('Error decoding message from websocket: %s' % ex)
            log.error(message)
            return False

        # Triage
        typus = message.get('type')
        if 'NotificationContainer' in message:
            typus = message['NotificationContainer'].get('type')
        if typus is None:
            log.error('No message type, dropping message: %s' % message)
            return False
        log.debug('Received message from PMS server: %s' % message)
        # Drop everything we're not interested in
        if typus not in ('playing', 'timeline'):
            return True

        # Put PMS message on queue and let libsync take care of it
        try:
            self.queue.put(message)
            return True
        except Queue.Full:
            # Queue only takes 200 messages. No worries if we miss one or two
            log.info('Queue is full, dropping PMS message %s' % message)
            return False

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
        server = window('pms_server')
        # Need to use plex.tv token, if any. NOT user token
        token = window('plex_token')
        # Get the appropriate prefix for the websocket
        if server.startswith('https'):
            server = "wss%s" % server[5:]
        else:
            server = "ws%s" % server[4:]
        uri = "%s/:/websockets/notifications" % server
        if token:
            uri += '?X-Plex-Token=%s' % token
        sslopt = {}
        if settings('sslverify') == "false":
            sslopt["cert_reqs"] = ssl.CERT_NONE
        log.debug("Uri: %s, sslopt: %s" % (uri, sslopt))
        return uri, sslopt

    def run(self):
        log.info("----===## Starting WebSocketClient ##===----")

        counter = 0
        handshake_counter = 0
        threadStopped = self.threadStopped
        threadSuspended = self.threadSuspended
        while not threadStopped():
            # In the event the server goes offline
            while threadSuspended():
                # Set in service.py
                if self.ws is not None:
                    try:
                        self.ws.shutdown()
                    except:
                        pass
                    self.ws = None
                if threadStopped():
                    # Abort was requested while waiting. We should exit
                    log.info("##===---- WebSocketClient Stopped ----===##")
                    return
                xbmc.sleep(1000)
            try:
                self.process(*self.receive(self.ws))
            except websocket.WebSocketTimeoutException:
                # No worries if read timed out
                pass
            except websocket.WebSocketConnectionClosedException:
                log.info("Connection closed, (re)connecting")
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
                    log.info("Error connecting")
                    self.ws = None
                    counter += 1
                    if counter > 10:
                        log.warn("Repeatedly could not connect to PMS, "
                                 "declaring the connection dead")
                        window('plex_online', value='false')
                        counter = 0
                    xbmc.sleep(1000)
                except websocket.WebSocketTimeoutException:
                    log.info("timeout while connecting, trying again")
                    self.ws = None
                    xbmc.sleep(1000)
                except websocket.WebSocketException as e:
                    log.info('WebSocketException: %s' % e)
                    if 'Handshake Status 401' in e.args:
                        handshake_counter += 1
                        if handshake_counter >= 5:
                            log.info('Error in handshake detected. Stopping '
                                     'WebSocketClient now')
                            break
                    self.ws = None
                    xbmc.sleep(1000)
                except Exception as e:
                    log.error("Unknown exception encountered in connecting: %s"
                              % e)
                    import traceback
                    log.error("Traceback:\n%s" % traceback.format_exc())
                    self.ws = None
                    xbmc.sleep(1000)
                else:
                    counter = 0
                    handshake_counter = 0
            except Exception as e:
                log.error("Unknown exception encountered: %s" % e)
                try:
                    self.ws.shutdown()
                except:
                    pass
                self.ws = None

        log.info("##===---- WebSocketClient Stopped ----===##")

    def stopThread(self):
        """
        Overwrite this method from ThreadMethods to close websockets
        """
        log.info("Stopping websocket client thread.")
        self._threadStopped = True
        try:
            self.ws.shutdown()
        except:
            pass
