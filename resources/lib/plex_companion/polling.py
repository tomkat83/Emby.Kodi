#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import requests

from .processing import process_command
from .common import communicate, log_error, create_requests_session, \
    b_ok_message

from .. import utils
from .. import backgroundthread
from .. import app

# Timeout (connection timeout, read timeout)
# The later is up to 20 seconds, if the PMS has nothing to tell us
# THIS WILL PREVENT PKC FROM SHUTTING DOWN CORRECTLY
TIMEOUT = (5.0, 4.0)

# Max. timeout for the Polling: 2 ^ MAX_TIMEOUT
# Corresponds to 2 ^ 7 = 128 seconds
MAX_TIMEOUT = 7

log = logging.getLogger('PLEX.companion.polling')


class Polling(backgroundthread.KillableThread):
    """
    Opens a GET HTTP connection to the current PMS (that will time-out PMS-wise
    after ~20 seconds) and listens for any commands by the PMS. Listening
    will cause this PKC client to be registered as a Plex Companien client.
    """
    daemon = True

    def __init__(self, playstate_mgr):
        self.s = None
        self.playstate_mgr = playstate_mgr
        self._sleep_timer = 0
        self.ok_msg = b_ok_message()
        super().__init__()

    def _get_requests_session(self):
        if self.s is None:
            log.debug('Creating new requests session')
            self.s = create_requests_session()
        return self.s

    def close_requests_session(self):
        try:
            self.s.close()
        except AttributeError:
            # "thread-safety" - Just in case s was set to None in the
            # meantime
            pass
        self.s = None

    def _unauthorized(self):
        """Puts this thread to sleep until e.g. a PMS changes wakes it up"""
        log.warn('We are not authorized to poll the PMS (http error 401). '
                 'Plex Companion will not work.')
        self.suspend()

    def _on_connection_error(self, req=None, error=None):
        if req:
            log_error(log.error, 'Error while contacting the PMS', req)
        if error:
            log.error('Error encountered: %s: %s', type(error), error)
        self.sleep(2 ** self._sleep_timer)
        if self._sleep_timer < MAX_TIMEOUT:
            self._sleep_timer += 1

    def ok_message(self, command_id):
        url = f'{app.CONN.server}/player/proxy/response?commandID={command_id}'
        try:
            req = communicate(self.s.post, url, data=self.ok_msg)
        except (requests.RequestException, SystemExit) as error:
            log.debug('Error replying with an OK message: %s', error)
            return
        if not req.ok:
            log_error(log.error, 'Error replying with OK message', req)

    def run(self):
        """
        Ensure that sockets will be closed no matter what
        """
        app.APP.register_thread(self)
        log.info("----===## Starting PollCompanion ##===----")
        try:
            self._run()
        finally:
            self.close_requests_session()
            app.APP.deregister_thread(self)
            log.info("----===## PollCompanion stopped ##===----")

    def _run(self):
        while not self.should_cancel():
            if self.should_suspend():
                self.close_requests_session()
                if self.wait_while_suspended():
                    break
            # See if there's anything we need to process
            # timeout=1 will cause the PMS to "hold" the connection for approx
            # 20 seconds. This will BLOCK requests - not something we can
            # circumvent.
            url = app.CONN.server + '/player/proxy/poll?timeout=1'
            self._get_requests_session()
            try:
                req = communicate(self.s.get, url, timeout=TIMEOUT)
            except (requests.exceptions.ProxyError,
                    requests.exceptions.SSLError) as error:
                self._on_connection_error(req=None, error=error)
                continue
            except (requests.ConnectionError,
                    requests.Timeout,
                    requests.exceptions.ChunkedEncodingError):
                # Expected due to timeout and the PMS not having to reply
                # No command received from the PMS - try again immediately
                continue
            except requests.RequestException as error:
                self._on_connection_error(req=None, error=error)
                continue
            except SystemExit:
                # We need to quit PKC entirely
                break

            # Sanity checks
            if req.status_code == 401:
                # We can't reach a PMS that is not in the local LAN
                # This might even lead to e.g. cloudflare blocking us, thinking
                # we're staging a DOS attach
                self._unauthorized()
                continue
            elif not req.ok:
                self._on_connection_error(req=req, error=None)
                continue
            elif not ('content-type' in req.headers
                    and 'xml' in req.headers['content-type']):
                self._on_connection_error(req=req, error=None)
                continue

            if not req.text:
                # Means the connection timed-out (usually after 20 seconds),
                # because there was no command from the PMS or a client to
                # remote-control anything no the PKC-side
                # Received an empty body, but still header Content-Type: xml
                continue

            # Parsing
            try:
                xml = utils.etree.fromstring(req.content)
                cmd = xml[0]
                if len(xml) > 1:
                    # We should always just get ONE command per message
                    raise IndexError()
            except (utils.ParseError, IndexError):
                log.error('Could not parse the PMS xml:')
                self._on_connection_error(req=req, error=None)
                continue

            # Do the work
            log.debug('Received a Plex Companion command from the PMS:')
            utils.log_xml(xml, log.debug, logging.DEBUG)
            self.playstate_mgr.check_subscriber(cmd)
            if process_command(cmd):
                self.ok_message(cmd.get('commandID'))
            self._sleep_timer = 0
