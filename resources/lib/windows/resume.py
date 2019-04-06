#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from datetime import timedelta

import xbmc
import xbmcgui
import xbmcaddon

from logging import getLogger


LOG = getLogger('PLEX.resume')

XML_PATH = (xbmcaddon.Addon('plugin.video.plexkodiconnect').getAddonInfo('path'),
            "default",
            "1080i")

ACTION_PARENT_DIR = 9
ACTION_PREVIOUS_MENU = 10
ACTION_BACK = 92
RESUME = 3010
START_BEGINNING = 3011


class ResumeDialog(xbmcgui.WindowXMLDialog):

    _resume_point = None
    selected_option = None

    def __init__(self, *args, **kwargs):
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)

    def set_resume_point(self, time):
        self._resume_point = time

    def is_selected(self):
        return True if self.selected_option is not None else False

    def get_selected(self):
        return self.selected_option

    def onInit(self):

        self.getControl(RESUME).setLabel(self._resume_point)
        self.getControl(START_BEGINNING).setLabel(xbmc.getLocalizedString(12021))

    def onAction(self, action):
        if action in (ACTION_BACK, ACTION_PARENT_DIR, ACTION_PREVIOUS_MENU):
            self.close()

    def onClick(self, controlID):
        if controlID == RESUME:
            self.selected_option = 1
            self.close()
        if controlID == START_BEGINNING:
            self.selected_option = 0
            self.close()


def resume_dialog(seconds):
    '''
    Base resume dialog based on Kodi settings
    Returns True if PKC should resume, False if not, None if user backed out
    of the dialog
    '''
    LOG.info("Resume dialog called")
    dialog = ResumeDialog("script-plex-resume.xml", *XML_PATH)
    dialog.set_resume_point("Resume from %s"
                            % unicode(timedelta(seconds=seconds)).split(".")[0])
    dialog.doModal()

    if dialog.is_selected():
        if not dialog.get_selected():
            # Start from beginning selected
            return False
    else:
        # User backed out
        LOG.info("User exited without a selection")
        return
    return True
