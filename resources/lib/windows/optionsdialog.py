#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
import xbmc

from . import kodigui
from .. import utils, variables as v


class OptionsDialog(kodigui.BaseDialog):
    xmlFile = 'script-plex-options_dialog.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    GROUP_ID = 100
    BUTTON_IDS = (1001, 1002, 1003)

    def __init__(self, *args, **kwargs):
        kodigui.BaseDialog.__init__(self, *args, **kwargs)
        self.header = kwargs.get('header')
        self.info = kwargs.get('info')
        self.button0 = kwargs.get('button0')
        self.button1 = kwargs.get('button1')
        self.button2 = kwargs.get('button2')
        self.buttonChoice = None

    def onFirstInit(self):
        self.setProperty('header', self.header)
        self.setProperty('info', self.info)

        if self.button2:
            self.setProperty('button.2', self.button2)

        if self.button1:
            self.setProperty('button.1', self.button1)

        if self.button0:
            self.setProperty('button.0', self.button0)

        self.setBoolProperty('initialized', True)
        xbmc.Monitor().waitForAbort(0.1)
        self.setFocusId(self.BUTTON_IDS[0])

    def onClick(self, controlID):
        if controlID in self.BUTTON_IDS:
            self.buttonChoice = self.BUTTON_IDS.index(controlID)
            self.doClose()


def show(header, info, button0=None, button1=None, button2=None):
    w = OptionsDialog.open(header=header, info=info, button0=button0, button1=button1, button2=button2)
    choice = w.buttonChoice
    del w
    utils.garbageCollect()
    return choice
