#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import requests

from .processing import process_proxy_xml
from .common import proxy_headers, proxy_params, log_error

from .. import utils
from .. import backgroundthread
from .. import app
from .. import variables as v

# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

# Timeout (connection timeout, read timeout)
# The later is up to 20 seconds, if the PMS has nothing to tell us
# THIS WILL PREVENT PKC FROM SHUTTING DOWN CORRECTLY
TIMEOUT = (5.0, 3.0)

log = getLogger('PLEX.companion.listener')


class Listener(backgroundthread.KillableThread):
    """
    Opens a GET HTTP connection to the current PMS (that will time-out PMS-wise
    after ~20 seconds) and listens for any commands by the PMS. Listening
    will cause this PKC client to be registered as a Plex Companien client.
    """
    daemon = True

    def __init__(self, playstate_mgr):
        self.s = None
        self.playstate_mgr = playstate_mgr
        super().__init__()

    def _get_requests_session(self):
        if self.s is None:
            log.debug('Creating new requests session')
            self.s = requests.Session()
            self.s.headers = proxy_headers()
            self.s.verify = app.CONN.verify_ssl_cert
            if app.CONN.ssl_cert_path:
                self.s.cert = app.CONN.ssl_cert_path
            self.s.params = proxy_params()
        return self.s

    def close_requests_session(self):
        try:
            self.s.close()
        except AttributeError:
            # "thread-safety" - Just in case s was set to None in the
            # meantime
            pass
        self.s = None

    def ok_message(self, command_id):
        url = f'{app.CONN.server}/player/proxy/response?commandID={command_id}'
        try:
            req = self.communicate(self.s.post,
                                   url,
                                   data=v.COMPANION_OK_MESSAGE.encode('utf-8'))
        except (requests.RequestException, SystemExit):
            return
        if not req.ok:
            log_error(log.error, 'Error replying OK', req)

    @staticmethod
    def communicate(method, url, **kwargs):
        try:
            req = method(url, **kwargs)
        except requests.ConnectTimeout:
            # The request timed out while trying to connect to the PMS
            log.error('Requests ConnectionTimeout!')
            raise
        except requests.ReadTimeout:
            # The PMS did not send any data in the allotted amount of time
            log.error('Requests ReadTimeout!')
            raise
        except requests.TooManyRedirects:
            log.error('TooManyRedirects error!')
            raise
        except requests.HTTPError as error:
            log.error('HTTPError: %s', error)
            raise
        except requests.ConnectionError:
            # Caused by PKC terminating the connection prematurely
            # log.error('ConnectionError: %s', error)
            raise
        else:
            req.encoding = 'utf-8'
            # Access response content once in order to make sure to release the
            # underlying sockets
            req.content
            return req

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
                req = self.communicate(self.s.get,
                                       url,
                                       timeout=TIMEOUT)
            except requests.ConnectionError:
                # No command received from the PMS - try again immediately
                continue
            except requests.RequestException:
                self.sleep(0.5)
                continue
            except SystemExit:
                # We need to quit PKC entirely
                break

            # Sanity checks
            if not req.ok:
                log_error(log.error, 'Error while contacting the PMS', req)
                self.sleep(0.5)
                continue
            if not req.text:
                # Means the connection timed-out (usually after 20 seconds),
                # because there was no command from the PMS or a client to
                # remote-control anything no the PKC-side
                # Received an empty body, but still header Content-Type: xml
                continue
            if not ('content-type' in req.headers
                    and 'xml' in req.headers['content-type']):
                log_error(log.error, 'Unexpected answer from the PMS', req)
                self.sleep(0.5)
                continue

            # Parsing
            try:
                xml = utils.etree.fromstring(req.content)
                cmd = xml[0]
                if len(xml) > 1:
                    # We should always just get ONE command per message
                    raise IndexError()
            except (utils.ParseError, IndexError):
                log_error(log.error, 'Could not parse the PMS xml:', req)
                self.sleep(0.5)
                continue

            # Do the work
            log.debug('Received a Plex Companion command from the PMS:')
            utils.log_xml(xml, log.debug)
            self.playstate_mgr.check_subscriber(cmd)
            if process_proxy_xml(cmd):
                self.ok_message(cmd.get('commandID'))
