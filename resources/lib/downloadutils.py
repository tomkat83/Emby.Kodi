#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
import requests
import requests.exceptions as exceptions

from . import utils, clientinfo, app

###############################################################################

# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

LOG = getLogger('PLEX.download')

###############################################################################


class DownloadUtils(object):
    """
    Manages any up/downloads with PKC. Careful to initiate correctly
    Use startSession() to initiate.
    If not initiated, e.g. SSL check will fallback to False
    """

    # Borg - multiple instances, shared state
    _shared_state = {}

    # How many failed attempts before declaring PMS dead?
    connection_attempts = 1
    count_error = 0
    # How many 401 returns before declaring unauthorized?
    unauthorized_attempts = 2
    count_unauthorized = 0
    # How long should we wait for an answer from the
    timeout = 30.0

    def __init__(self):
        self.__dict__ = self._shared_state

    def setSSL(self):
        """
        certificate must be path to certificate or 'None'
        """
        verifySSL = app.CONN.verify_ssl_cert
        certificate = app.CONN.ssl_cert_path
        # Set the session's parameters
        self.s.verify = verifySSL
        if certificate:
            self.s.cert = certificate
        LOG.debug("Verify SSL certificates set to: %s", verifySSL)
        LOG.debug("SSL client side certificate set to: %s", certificate)

    def startSession(self, reset=False):
        """
        User should be authenticated when this method is called
        """
        # Start session
        self.s = requests.Session()

        self.deviceId = clientinfo.getDeviceId()
        # Attach authenticated header to the session
        self.s.headers = clientinfo.getXArgsDeviceInfo()
        self.s.encoding = 'utf-8'
        # Set SSL settings
        self.setSSL()

        # Counters to declare PMS dead or unauthorized
        if reset is True:
            self.count_error = 0
            self.count_unauthorized = 0

        # Retry connections to the server
        self.s.mount("http://", requests.adapters.HTTPAdapter(max_retries=1))
        self.s.mount("https://", requests.adapters.HTTPAdapter(max_retries=1))

        LOG.debug("Requests session started on: %s", app.CONN.server)

    def stopSession(self):
        try:
            self.s.close()
        except Exception:
            LOG.info("Requests session already closed")
        try:
            del self.s
        except AttributeError:
            pass
        LOG.info('Request session stopped')

    @staticmethod
    def getHeader(options=None):
        header = clientinfo.getXArgsDeviceInfo()
        if options is not None:
            header.update(options)
        return header

    @staticmethod
    def _doDownload(s, action_type, **kwargs):
        if action_type == "GET":
            r = s.get(**kwargs)
        elif action_type == "POST":
            r = s.post(**kwargs)
        elif action_type == "DELETE":
            r = s.delete(**kwargs)
        elif action_type == "OPTIONS":
            r = s.options(**kwargs)
        elif action_type == "PUT":
            r = s.put(**kwargs)
        return r

    def downloadUrl(self, url, action_type="GET", postBody=None,
                    parameters=None, authenticate=True, headerOptions=None,
                    verifySSL=True, timeout=None, return_response=False,
                    headerOverride=None, reraise=False):
        """
        Override SSL check with verifySSL=False

        If authenticate=True, existing request session will be used/started
        Otherwise, 'empty' request will be made

        Returns:
            None              If an error occured
            True               If connection worked but no body was received
            401, ...           integer if PMS answered with HTTP error 401
                               (unauthorized) or other http error codes
            xml                xml etree root object, if applicable
            json               json() object, if applicable
            <response-object>  if return_response=True is set (200, 201 only)
        """
        kwargs = {'timeout': self.timeout}
        if authenticate is True:
            # Get requests session
            try:
                s = self.s
            except AttributeError:
                LOG.info("Request session does not exist: start one")
                self.startSession()
                s = self.s
            # Replace for the real values
            url = url.replace("{server}", app.CONN.server)
        else:
            # User is not (yet) authenticated. Used to communicate with
            # plex.tv and to check for PMS servers
            s = requests
            if not headerOverride:
                headerOptions = self.getHeader(options=headerOptions)
            else:
                headerOptions = headerOverride
            kwargs['verify'] = app.CONN.verify_ssl_cert
            if app.CONN.ssl_cert_path:
                kwargs['cert'] = app.CONN.ssl_cert_path

        # Set the variables we were passed (fallback to request session
        # otherwise - faster)
        kwargs['url'] = url
        if verifySSL is False:
            kwargs['verify'] = False
        if headerOptions is not None:
            kwargs['headers'] = headerOptions
        if postBody is not None:
            kwargs['data'] = postBody
        if parameters is not None:
            kwargs['params'] = parameters
        if timeout is not None:
            kwargs['timeout'] = timeout

        # ACTUAL DOWNLOAD HAPPENING HERE
        success = False
        try:
            r = self._doDownload(s, action_type, **kwargs)

        # THE EXCEPTIONS
        except exceptions.SSLError as e:
            LOG.warn("Invalid SSL certificate for: %s", url)
            LOG.warn(e)
            if reraise:
                raise
        except exceptions.ConnectionError as e:
            # Connection error
            LOG.warn("Server unreachable at: %s", url)
            LOG.warn(e)
            if reraise:
                raise
        except exceptions.Timeout as e:
            LOG.warn("Server timeout at: %s", url)
            LOG.warn(e)
            if reraise:
                raise
        except exceptions.HTTPError as e:
            LOG.warn('HTTP Error at %s', url)
            LOG.warn(e)
            if reraise:
                raise
        except exceptions.TooManyRedirects as e:
            LOG.warn("Too many redirects connecting to: %s", url)
            LOG.warn(e)
            if reraise:
                raise
        except exceptions.RequestException as e:
            LOG.warn("Unknown error connecting to: %s", url)
            LOG.warn(e)
            if reraise:
                raise
        except SystemExit:
            LOG.info('SystemExit detected, aborting download')
            self.stopSession()
            if reraise:
                raise
        except Exception:
            LOG.warn('Unknown error while downloading. Traceback:')
            import traceback
            LOG.warn(traceback.format_exc())
            if reraise:
                raise

        # THE RESPONSE #####
        else:
            success = True
            # We COULD contact the PMS, hence it ain't dead
            if authenticate is True:
                self.count_error = 0
                if r.status_code != 401:
                    self.count_unauthorized = 0

            if return_response is True:
                # return the entire response object
                return r

            elif r.status_code == 204:
                # No body in the response
                # But read (empty) content to release connection back to pool
                # (see requests: keep-alive documentation)
                r.content
                return True

            elif r.status_code == 401:
                if authenticate is False:
                    # Called when checking a connect - no need for rash action
                    return 401
                r.encoding = 'utf-8'
                LOG.warn('HTTP error 401 from PMS %s', url)
                LOG.info(r.text)
                if '401 Unauthorized' in r.text:
                    # Truly unauthorized
                    self.count_unauthorized += 1
                    if self.count_unauthorized >= self.unauthorized_attempts:
                        LOG.warn('We seem to be truly unauthorized for PMS'
                                 ' %s ', url)
                        # Unauthorized access, user no longer has access
                        app.ACCOUNT.log_out()
                        utils.dialog('notification',
                                     utils.lang(29999),
                                     utils.lang(30017),
                                     icon='{error}')
                else:
                    # there might be other 401 where e.g. PMS under strain
                    LOG.info('PMS might only be under strain')
                return 401

            elif r.status_code in (200, 201):
                # 200: OK
                # 201: Created
                try:
                    # xml response
                    r = utils.etree.fromstring(r.content)
                    return r
                except Exception:
                    r.encoding = 'utf-8'
                    if r.text == '':
                        # Answer does not contain a body
                        return True
                    try:
                        # UNICODE - JSON object
                        r = r.json()
                        return r
                    except Exception:
                        if '200 OK' in r.text:
                            # Received fucked up OK from PMS on playstate
                            # update
                            pass
                        else:
                            LOG.warn("Unable to convert the response for: "
                                     "%s", url)
                            LOG.warn("Received headers were: %s", r.headers)
                            LOG.warn('Received text: %s', r.text)
                        return True
            elif r.status_code == 403:
                # E.g. deleting a PMS item
                LOG.warn('PMS sent 403: Forbidden error for url %s', url)
                return
            else:
                r.encoding = 'utf-8'
                LOG.warn('Unknown answer from PMS %s with status code %s: %s',
                         url, r.status_code, r.text)
                return True

        finally:
            if not success and authenticate:
                # Deal with the consequences of the exceptions
                # Make the addon aware of status
                self.count_error += 1
                if self.count_error >= self.connection_attempts:
                    LOG.warn('Failed to connect to %s too many times. '
                             'Declare PMS dead', url)
                    app.CONN.online = False
