#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import xbmcgui

from . import utils
from . import path_ops
from . import variables as v

###############################################################################

LOG = getLogger('PLEX.context')

ACTION_PARENT_DIR = 9
ACTION_PREVIOUS_MENU = 10
ACTION_BACK = 92
ACTION_SELECT_ITEM = 7
ACTION_MOUSE_LEFT_CLICK = 100
LIST = 155
USER_IMAGE = 150

###############################################################################


class ContextMenu(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self._options = []
        self.selected_option = None
        self.list_ = None
        self.background = None
        xbmcgui.WindowXMLDialog.__init__(self, *args, **kwargs)

    def set_options(self, options=None):
        if not options:
            options = []
        self._options = options

    def is_selected(self):
        return True if self.selected_option else False

    def get_selected(self):
        return self.selected_option

    def onInit(self):
        if utils.window('PlexUserImage'):
            self.getControl(USER_IMAGE).setImage(utils.window('PlexUserImage'))
        height = 479 + (len(self._options) * 55)
        LOG.debug("options: %s", self._options)
        self.list_ = self.getControl(LIST)
        for option in self._options:
            self.list_.addItem(self._add_listitem(option))
        self.background = self._add_editcontrol(730, height, 30, 450)
        self.setFocus(self.list_)

    def onAction(self, action):

        if action in (ACTION_BACK, ACTION_PARENT_DIR, ACTION_PREVIOUS_MENU):
            self.close()
        if action in (ACTION_SELECT_ITEM, ACTION_MOUSE_LEFT_CLICK):
            if self.getFocusId() == LIST:
                option = self.list_.getSelectedItem()
                self.selected_option = option.getLabel()
                LOG.info('option selected: %s', self.selected_option)
                self.close()

    def _add_editcontrol(self, x, y, height, width, password=None):
        media = path_ops.path.join(
            v.ADDON_PATH, 'resources', 'skins', 'default', 'media')
        filename = utils.try_encode(path_ops.path.join(media, 'white.png'))
        control = xbmcgui.ControlImage(0, 0, 0, 0,
                                       filename=filename,
                                       aspectRatio=0,
                                       colorDiffuse="ff111111")
        control.setPosition(x, y)
        control.setHeight(height)
        control.setWidth(width)
        self.addControl(control)
        return control

    @classmethod
    def _add_listitem(cls, label):
        return xbmcgui.ListItem(label)
