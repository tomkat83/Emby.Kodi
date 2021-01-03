#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

from .. import utils

LOG = getLogger('PLEX.account')


class Account(object):
    def __init__(self, entrypoint=False):
        self.plex_login = None
        self.plex_login_id = None
        self.plex_username = None
        self.plex_user_id = None
        self.plex_token = None
        # Personal access token per specific user and PMS
        # As a rule of thumb, always use this token!
        self.pms_token = None
        self.avatar = None
        self.myplexlogin = None
        self.restricted_user = None
        self.force_login = None
        self._session = None
        self.authenticated = False
        if entrypoint:
            self.load_entrypoint()
        else:
            utils.window('plex_authenticated', clear=True)
            self.load()

    def set_authenticated(self):
        self.authenticated = True
        utils.window('plex_authenticated', value='true')

    def set_unauthenticated(self):
        self.authenticated = False
        utils.window('plex_authenticated', clear=True)

    def reset_session(self):
        try:
            self._session.stopSession()
        except AttributeError:
            pass
        from .. import downloadutils
        self._session = downloadutils.DownloadUtils()
        self._session.startSession(reset=True)

    def load(self):
        LOG.debug('Loading account settings')
        # User name we used to sign in to plex.tv
        self.plex_login = utils.settings('plexLogin') or None
        self.plex_login_id = utils.settings('plexid') or None
        # plex.tv username
        self.plex_username = utils.settings('username') or None
        # Plex ID of that user (e.g. for plex.tv) as a STRING
        self.plex_user_id = utils.settings('userid') or None
        # Token for that user for plex.tv
        self.plex_token = utils.settings('plexToken') or None
        # Plex token for the active PMS for the active user
        # (might be diffent to plex_token)
        self.pms_token = utils.settings('accessToken') or None
        self.avatar = utils.settings('plexAvatar') or None
        self.myplexlogin = utils.settings('myplexlogin') == 'true'

        # Plex home user? Then "False"
        self.restricted_user = utils.settings('plex_restricteduser') == 'true'
        # Force user to enter Pin if set?
        self.force_login = utils.settings('enforceUserLogin') == 'true'

        # Also load these settings to Kodi window variables - they'll be
        # available for other PKC Python instances
        utils.window('plex_restricteduser',
                     value='true' if self.restricted_user else 'false')
        utils.window('plex_token', value=self.plex_token or '')
        utils.window('pms_token', value=self.pms_token or '')
        utils.window('plexAvatar', value=self.avatar or '')

        # Start download session
        self.reset_session()

        LOG.debug('Loaded user %s, %s with plex token %s... and pms token %s...',
                  self.plex_username, self.plex_user_id,
                  self.plex_token[:5] if self.plex_token else None,
                  self.pms_token[:5] if self.pms_token else None)
        LOG.debug('User is restricted Home user: %s', self.restricted_user)

    def load_entrypoint(self):
        self.pms_token = utils.settings('accessToken') or None

    def log_out(self):
        LOG.debug('Logging-out user %s', self.plex_username)
        self.plex_username = None
        self.plex_user_id = None
        self.pms_token = None
        self.avatar = None
        self.restricted_user = None
        self.authenticated = False
        try:
            self._session.stopSession()
        except AttributeError:
            pass
        self._session = None

        utils.settings('username', value='')
        utils.settings('userid', value='')
        utils.settings('plex_restricteduser', value='')
        utils.settings('accessToken', value='')
        utils.settings('plexAvatar', value='')

        utils.window('plex_restricteduser', clear=True)
        utils.window('pms_token', clear=True)
        utils.window('plexAvatar', clear=True)
        utils.window('plex_authenticated', clear=True)

    def clear(self):
        LOG.debug('Clearing account settings')
        self.plex_username = None
        self.plex_user_id = None
        self.plex_token = None
        self.pms_token = None
        self.avatar = None
        self.restricted_user = None
        self.authenticated = False
        self.plex_login = None
        self.plex_login_id = None
        try:
            self._session.stopSession()
        except AttributeError:
            pass
        self._session = None

        utils.settings('username', value='')
        utils.settings('userid', value='')
        utils.settings('plex_restricteduser', value='')
        utils.settings('plexToken', value='')
        utils.settings('accessToken', value='')
        utils.settings('plexAvatar', value='')
        utils.settings('plexLogin', value='')
        utils.settings('plexid', value='')

        utils.window('plex_restricteduser', clear=True)
        utils.window('plex_token', clear=True)
        utils.window('pms_token', clear=True)
        utils.window('plexAvatar', clear=True)
        utils.window('plex_authenticated', clear=True)
