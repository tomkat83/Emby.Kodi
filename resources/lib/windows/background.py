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


class BackgroundContext(object):
    """
    Context Manager to open a Plex background window - in the background. This
    will e.g. ensure that you can capture key-presses
    Use like this:
        with BackgroundContext(function) as win:
            <now function will be executed immediately. Get its results:>
            result = win.result
    """
    def __init__(self, function=None):
        self.window = None
        self.result = None
        self.function = function

    def __enter__(self):
        self.window = BackgroundWindow.create(function=self.function)
        self.window.modal()
        self.result = self.window.result
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        del self.window
