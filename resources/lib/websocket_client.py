#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import json

from . import websocket
from . import backgroundthread, app, variables as v, utils, companion

log = getLogger('PLEX.websocket')

PMS_PATH = '/:/websockets/notifications'

PMS_INTERESTING_MESSAGE_TYPES = ('playing', 'timeline', 'activity')
SETTINGS_STRING = '_status'


def get_pms_uri():
    uri = app.CONN.server
    if not uri:
        return
    # Get the appropriate prefix for the websocket
    if uri.startswith('https'):
        uri = "wss%s" % uri[5:]
    else:
        uri = "ws%s" % uri[4:]
    uri += PMS_PATH
    log.debug('uri to connect pms websocket: %s', uri)
    if app.ACCOUNT.pms_token:
        uri += '?X-Plex-Token=' + app.ACCOUNT.pms_token
    return uri


def get_alexa_uri():
    if not app.ACCOUNT.plex_token:
        return
    return (f'wss://pubsub.plex.tv/sub/websockets/{app.ACCOUNT.plex_user_id}/'
            f'{v.PKC_MACHINE_IDENTIFIER}?'
            f'X-Plex-Token={app.ACCOUNT.plex_token}')


def pms_on_message(ws, message):
    """
    Called when we receive a message from the PMS, e.g. when a new library
    item has been added.
    """
    try:
        message = json.loads(message)
    except ValueError as err:
        log.error('Error decoding PMS websocket message: %s', err)
        log.error('message: %s', message)
        return
    try:
        message = message['NotificationContainer']
        typus = message['type']
    except KeyError:
        log.error('Could not parse PMS message: %s', message)
        return
    # Triage
    if typus not in PMS_INTERESTING_MESSAGE_TYPES:
        # Drop everything we're not interested in
        return
    else:
        # Put PMS message on queue and let libsync take care of it
        app.APP.websocket_queue.put(message)


def alexa_on_message(ws, message):
    """
    Called when we receive a message from Alexa
    """
    log.debug('alexa message received: %s', message)
    try:
        message = utils.etree.fromstring(message)
    except Exception as err:
        log.error('Error decoding message from Alexa: %s %s', type(err), err)
        log.error('message from Alexa: %s', message)
        return
    try:
        if message.attrib['command'] == 'processRemoteControlCommand':
            message = message[0]
        else:
            log.error('Unknown Alexa message received: %s', message)
            return
        companion.process_command(message.attrib['path'][1:], message.attrib)
    except Exception as err:
        log.exception('Could not parse Alexa message, error: %s %s',
                      type(err), err)
        log.error('message: %s', message)


def on_error(ws, error):
    status = ws.name + SETTINGS_STRING
    if isinstance(error, IOError):
        # We are probably offline
        log.debug('%s: IOError connecting', ws.name)
        # Status = IOError - not connected
        utils.settings(status, value=utils.lang(39092))
        ws.sleep_cycle()
    elif isinstance(error, websocket.WebSocketTimeoutException):
        log.debug('%s: WebSocketTimeoutException', ws.name)
        # Status = 'Timeout - not connected'
        utils.settings(status, value=utils.lang(39091))
        ws.sleep_cycle()
    elif isinstance(error, websocket.WebSocketConnectionClosedException):
        log.debug('%s: WebSocketConnectionClosedException', ws.name)
        # Status = Not connected
        utils.settings(ws.name + SETTINGS_STRING, value=utils.lang(15208))
    elif isinstance(error, websocket.WebSocketBadStatusException):
        # Most likely Alexa not connecting, throwing a 403
        log.debug('%s: got a bad HTTP status: %s', ws.name, error)
        # Status = <value of exception>
        utils.settings(status, value=str(error))
        ws.sleep_cycle()
    elif isinstance(error, websocket.WebSocketException):
        log.error('%s: got another websocket exception %s: %s',
                  ws.name, type(error), error)
        # Status = Error
        utils.settings(status, value=utils.lang(257))
        ws.sleep_cycle()
    elif isinstance(error, SystemExit):
        log.debug('%s: SystemExit detected', ws.name)
        # Status = Not connected
        utils.settings(ws.name + SETTINGS_STRING, value=utils.lang(15208))
    else:
        log.exception('%s: got an unexpected exception of type %s: %s',
                      ws.name, type(error), error)
        # Status = Error
        utils.settings(status, value=utils.lang(257))


def on_close(ws):
    """
    This does not seem to get called by our websocket client :-(
    """
    log.debug('%s: connection closed', ws.name)
    # Status = Not connected
    utils.settings(ws.name + SETTINGS_STRING, value=utils.lang(15208))


def on_open(ws):
    log.debug('%s: connected', ws.name)
    # Status = Connected
    utils.settings(ws.name + SETTINGS_STRING, value=utils.lang(13296))
    ws.sleeptime = 0


class PlexWebSocketApp(websocket.WebSocketApp,
                       backgroundthread.KillableThread):
    def __init__(self, **kwargs):
        self.sleeptime = 0
        backgroundthread.KillableThread.__init__(self)
        websocket.WebSocketApp.__init__(self, self.get_uri(), **kwargs)

    def sleep_cycle(self):
        """
        Sleeps for 2^self.sleeptime where sleeping period will be doubled with
        each unsuccessful connection attempt.
        Will sleep at most 64 seconds
        """
        self.sleep(2 ** self.sleeptime)
        if self.sleeptime < 6:
            self.sleeptime += 1

    def close(self, **kwargs):
        """websocket.WebSocketApp is not yet thread-safe. close() might
        encounter websockets that have already been closed"""
        try:
            websocket.WebSocketApp.close(self, **kwargs)
        except AttributeError:
            pass

    def suspend(self, block=False, timeout=None):
        """
        Call this method from another thread to suspend this websocket thread
        """
        self.close()
        backgroundthread.KillableThread.suspend(self, block, timeout)

    def cancel(self):
        """
        Call this method from another thread to cancel this websocket thread
        """
        self.close()
        backgroundthread.KillableThread.cancel(self)

    def run(self):
        """
        Ensure that sockets will be closed no matter what
        """
        log.info("----===## Starting %s ##===----", self.name)
        app.APP.register_thread(self)
        try:
            self._run()
        except RuntimeError:
            pass
        except Exception as err:
            log.exception('Exception of type %s occured: %s', type(err), err)
        finally:
            self.close()
            if self._enabled:
                # Status = Not connected
                message = utils.lang(15208)
            else:
                # Status = Disabled
                message = utils.lang(24023)
            utils.settings(self.name + SETTINGS_STRING,
                           value=message)
            app.APP.deregister_thread(self)
            log.info("----===## %s stopped ##===----", self.name)

    def _run(self):
        while not self.should_cancel() and self._enabled:
            # In the event the server goes offline
            while self.should_suspend():
                # We will be caught in this loop if either another thread
                # called the suspend() method, thus setting _suspended = True
                # OR if there any other conditions to not open a websocket
                # connection - see methods should_suspend() below
                # Status = Suspended - not connected
                self.set_suspension_settings_status()
                if self.wait_while_suspended():
                    # Abort was requested while waiting. We should exit
                    return
                if not self._suspended:
                    # because wait_while_suspended will return instantly if
                    # this thread did not get suspended from another thread
                    self.sleep_cycle()
            self.url = self.get_uri()
            if not self.url:
                self.sleep_cycle()
                continue
            self.run_forever()


class PMSWebsocketApp(PlexWebSocketApp):
    name = 'pms_websocket'

    def __init__(self, *args, **kwargs):
        self._enabled = utils.settings('enableBackgroundSync') == 'true'
        super().__init__(*args, **kwargs)

    def get_uri(self):
        return get_pms_uri()

    def set_suspension_settings_status(self):
        if utils.settings('enableBackgroundSync') != 'true':
            # Status = Disabled
            utils.settings(self.name + SETTINGS_STRING,
                           value=utils.lang(24023))
        else:
            # Status = 'Suspended - not connected'
            utils.settings(self.name + SETTINGS_STRING,
                           value=utils.lang(39093))


class AlexaWebsocketApp(PlexWebSocketApp):
    name = 'alexa_websocket'

    def __init__(self, *args, **kwargs):
        self._enabled = utils.settings('enable_alexa') == 'true'
        super().__init__(*args, **kwargs)

    def get_uri(self):
        return get_alexa_uri()

    def should_suspend(self):
        """
        Returns True if the thread needs to suspend.
        """
        return self._suspended or \
            app.ACCOUNT.restricted_user or \
            not app.ACCOUNT.plex_token

    def set_suspension_settings_status(self):
        if utils.settings('enable_alexa') != 'true':
            # Status = Disabled
            utils.settings(self.name + SETTINGS_STRING,
                           value=utils.lang(24023))
        elif app.ACCOUNT.restricted_user:
            # Status = Managed Plex User - not connected
            utils.settings(self.name + SETTINGS_STRING,
                           value=utils.lang(39094))
        elif not app.ACCOUNT.plex_token:
            # Status = Not logged in to plex.tv
            utils.settings(self.name + SETTINGS_STRING,
                           value=utils.lang(39226))
        else:
            # Status = 'Suspended - not connected'
            utils.settings(self.name + SETTINGS_STRING,
                           value=utils.lang(39093))


def get_pms_websocketapp():
    return PMSWebsocketApp(on_open=on_open,
                           on_message=pms_on_message,
                           on_error=on_error,
                           on_close=on_close)


def get_alexa_websocketapp():
    return AlexaWebsocketApp(on_open=on_open,
                             on_message=alexa_on_message,
                             on_error=on_error,
                             on_close=on_close)
