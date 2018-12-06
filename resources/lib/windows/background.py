#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from . import kodigui
from .. import utils, variables as v

utils.setGlobalProperty('background.busy', '')
utils.setGlobalProperty('background.shutdown', '')
utils.setGlobalProperty('background.splash', '')


class BackgroundWindow(kodigui.BaseWindow):
    xmlFile = 'script-plex-background.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    def __init__(self, *args, **kwargs):
        kodigui.BaseWindow.__init__(self, *args, **kwargs)
        self.result = None
        self.function = kwargs.get('function')


    def onAction(self, action):
        kodigui.BaseWindow.onAction(self, action)


    def onFirstInit(self):
        self.result = self.function()
        self.doClose()


def setBusy(on=True):
    utils.setGlobalProperty('background.busy', on and '1' or '')


def setSplash(on=True):
    utils.setGlobalProperty('background.splash', on and '1' or '')


def setShutdown(on=True):
    utils.setGlobalProperty('background.shutdown', on and '1' or '')
