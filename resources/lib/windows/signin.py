#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
import xbmcgui

from . import kodigui
from .. import utils, variables as v


class Background(kodigui.BaseWindow):
    xmlFile = 'script-plex-signin_background.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080


class SignInMessage(kodigui.BaseWindow):
    xmlFile = 'script-plex-signin_blank.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    SCREEN_BUTTON_ID = 100

    def __init__(self, *args, **kwargs):
        self.message = kwargs.get('message')
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def onFirstInit(self):
        self.setProperty('message', self.message)

    def onClick(self, controlID):
        if controlID == self.SCREEN_BUTTON_ID:
            self.doClose()


class SignInPlexPass(kodigui.BaseWindow):
    xmlFile = 'script-plex-plex_pass.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    RETRY_BUTTON_ID = 100

    def __init__(self, *args, **kwargs):
        self.retry = False
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def onAction(self, action):
        if action == xbmcgui.ACTION_SELECT_ITEM:
            self.retry = True
            self.doClose()
        kodigui.BaseWindow.onAction(self, action)

    def onClick(self, controlID):
        if controlID == self.RETRY_BUTTON_ID:
            self.retry = True
            self.doClose()


class PreSignInWindow(kodigui.BaseWindow):
    xmlFile = 'script-plex-pre_signin.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    SIGNIN_BUTTON_ID = 100

    def __init__(self, *args, **kwargs):
        self.doSignin = False
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def onFirstInit(self):
        self.signinButton = self.getControl(self.SIGNIN_BUTTON_ID)

    def onAction(self, action):
        if action == xbmcgui.ACTION_SELECT_ITEM:
            self.doSignin = True
            self.doClose()
        kodigui.BaseWindow.onAction(self, action)

    def onClick(self, controlID):
        if controlID == self.SIGNIN_BUTTON_ID:
            self.doSignin = True
            self.doClose()


class PinLoginWindow(kodigui.BaseWindow):
    xmlFile = 'script-plex-pin_login.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    def __init__(self, *args, **kwargs):
        self.abort = False
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def setPin(self, pin):
        self.setProperty('pin.image.0', 'plugin.video.plexkodiconnect/sign_in/digits/{0}.png'.format(pin[0].upper()))
        self.setProperty('pin.image.1', 'plugin.video.plexkodiconnect/sign_in/digits/{0}.png'.format(pin[1].upper()))
        self.setProperty('pin.image.2', 'plugin.video.plexkodiconnect/sign_in/digits/{0}.png'.format(pin[2].upper()))
        self.setProperty('pin.image.3', 'plugin.video.plexkodiconnect/sign_in/digits/{0}.png'.format(pin[3].upper()))

    def setLinking(self):
        self.setProperty('linking', '1')
        self.setProperty('pin.image.0', '')
        self.setProperty('pin.image.1', '')
        self.setProperty('pin.image.2', '')
        self.setProperty('pin.image.3', '')

    def onAction(self, action):
        if action == xbmcgui.ACTION_NAV_BACK or action == xbmcgui.ACTION_PREVIOUS_MENU:
            self.abort = True
        kodigui.BaseWindow.onAction(self, action)


class ExpiredWindow(kodigui.BaseWindow):
    xmlFile = 'script-plex-refresh_code.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    REFRESH_BUTTON_ID = 100

    def __init__(self, *args, **kwargs):
        self.refresh = False
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def onFirstInit(self):
        self.refreshButton = self.getControl(self.REFRESH_BUTTON_ID)

    def onClick(self, controlID):
        if controlID == self.REFRESH_BUTTON_ID:
            self.refresh = True
            self.doClose()
