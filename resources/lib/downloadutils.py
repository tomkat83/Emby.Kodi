#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import xml.etree.ElementTree as etree
import requests

from . import utils
from . import clientinfo
from . import state

###############################################################################

# Disable annoying requests warnings
import requests.packages.urllib3
requests.packages.urllib3.disable_warnings()

LOG = getLogger('PLEX.downloadutils')

###############################################################################


class DownloadUtils():
    """
    Manages any up/downloads with PKC. Careful to initiate correctly
    Use startSession() to initiate.
    If not initiated, e.g. SSL check will fallback to False
    """

    # Borg - multiple instances, shared state
    _shared_state = {}

    # How many failed attempts before declaring PMS dead?
    connectionAttempts = 1
    # How many 401 returns before declaring unauthorized?
    unauthorizedAttempts = 2
    # How long should we wait for an answer from the
    timeout = 30.0

    def __init__(self):
        self.__dict__ = self._shared_state

    def setServer(self, server):
        """
        Reserved for userclient only
        """
        self.server = server
        LOG.debug("Set server: %s", server)

    def setSSL(self, verifySSL=None, certificate=None):
        """
        Reserved for userclient only

        verifySSL must be 'true' to enable certificate validation

        certificate must be path to certificate or 'None'
        """
        if verifySSL is None:
            verifySSL = state.VERIFY_SSL_CERT
        if certificate is None:
            certificate = state.SSL_CERT_PATH
        # Set the session's parameters
        self.s.verify = verifySSL
        if certificate:
            self.s.cert = certificate
        LOG.debug("Verify SSL certificates set to: %s", verifySSL)
        LOG.debug("SSL client side certificate set to: %s", certificate)

    def startSession(self, reset=False):
        """
        User should be authenticated when this method is called (via
        userclient)
        """
        # Start session
        self.s = requests.Session()

        self.deviceId = clientinfo.getDeviceId()
        # Attach authenticated header to the session
        self.s.headers = clientinfo.getXArgsDeviceInfo()
        self.s.encoding = 'utf-8'
        # Set SSL settings
        self.setSSL()

        # Set other stuff
        self.setServer(utils.window('pms_server'))

        # Counters to declare PMS dead or unauthorized
        # Use window variables because start of movies will be called with a
        # new plugin instance - it's impossible to share data otherwise
        if reset is True:
            utils.window('countUnauthorized', value='0')
            utils.window('countError', value='0')

        # Retry connections to the server
        self.s.mount("http://", requests.adapters.HTTPAdapter(max_retries=1))
        self.s.mount("https://", requests.adapters.HTTPAdapter(max_retries=1))

        LOG.info("Requests session started on: %s", self.server)

    def stopSession(self):
        try:
            self.s.close()
        except:
            LOG.info("Requests session already closed")
        try:
            del self.s
        except:
            pass
        LOG.info('Request session stopped')

    def getHeader(self, options=None):
        header = clientinfo.getXArgsDeviceInfo()
        if options is not None:
            header.update(options)
        return header

    def _doDownload(self, s, action_type, **kwargs):
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
                    headerOverride=None):
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
            url = url.replace("{server}", self.server)
        else:
            # User is not (yet) authenticated. Used to communicate with
            # plex.tv and to check for PMS servers
            s = requests
            if not headerOverride:
                headerOptions = self.getHeader(options=headerOptions)
            else:
                headerOptions = headerOverride
            kwargs['verify'] = state.VERIFY_SSL_CERT
            if state.SSL_CERT_PATH:
                kwargs['cert'] = state.SSL_CERT_PATH

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
        try:
            r = self._doDownload(s, action_type, **kwargs)

        # THE EXCEPTIONS
        except requests.exceptions.SSLError as e:
            LOG.warn("Invalid SSL certificate for: %s", url)
            LOG.warn(e)

        except requests.exceptions.ConnectionError as e:
            # Connection error
            LOG.warn("Server unreachable at: %s", url)
            LOG.warn(e)

        except requests.exceptions.Timeout as e:
            LOG.warn("Server timeout at: %s", url)
            LOG.warn(e)

        except requests.exceptions.HTTPError as e:
            LOG.warn('HTTP Error at %s', url)
            LOG.warn(e)

        except requests.exceptions.TooManyRedirects as e:
            LOG.warn("Too many redirects connecting to: %s", url)
            LOG.warn(e)

        except requests.exceptions.RequestException as e:
            LOG.warn("Unknown error connecting to: %s", url)
            LOG.warn(e)

        except SystemExit:
            LOG.info('SystemExit detected, aborting download')
            self.stopSession()

        except:
            LOG.warn('Unknown error while downloading. Traceback:')
            import traceback
            LOG.warn(traceback.format_exc())

        # THE RESPONSE #####
        else:
            # We COULD contact the PMS, hence it ain't dead
            if authenticate is True:
                utils.window('countError', value='0')
                if r.status_code != 401:
                    utils.window('countUnauthorized', value='0')

            if r.status_code == 204:
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
                    utils.window(
                        'countUnauthorized',
                        value=str(int(utils.window('countUnauthorized')) + 1))
                    if (int(utils.window('countUnauthorized')) >=
                            self.unauthorizedAttempts):
                        LOG.warn('We seem to be truly unauthorized for PMS'
                                 ' %s ', url)
                        if state.PMS_STATUS not in ('401', 'Auth'):
                            # Tell userclient token has been revoked.
                            LOG.debug('Setting PMS server status to '
                                      'unauthorized')
                            state.PMS_STATUS = '401'
                            utils.window('plex_serverStatus', value="401")
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
                if return_response is True:
                    # return the entire response object
                    return r
                try:
                    # xml response
                    r = etree.fromstring(r.content)
                    return r
                except:
                    r.encoding = 'utf-8'
                    if r.text == '':
                        # Answer does not contain a body
                        return True
                    try:
                        # UNICODE - JSON object
                        r = r.json()
                        return r
                    except:
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
                return None
            else:
                r.encoding = 'utf-8'
                LOG.warn('Unknown answer from PMS %s with status code %s. ',
                         url, r.status_code)
                return True

        # And now deal with the consequences of the exceptions
        if authenticate is True:
            # Make the addon aware of status
            try:
                utils.window('countError',
                             value=str(int(utils.window('countError')) + 1))
                if int(utils.window('countError')) >= self.connectionAttempts:
                    LOG.warn('Failed to connect to %s too many times. '
                             'Declare PMS dead', url)
                    utils.window('plex_online', value="false")
            except ValueError:
                # 'countError' not yet set
                pass
        return None
