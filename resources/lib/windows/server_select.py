#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:module: plexkodiconnect.userselect
:synopsis: This module shows a dialog to let one choose between different Plex
           (home) users
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import xbmc
import xbmcgui

from . import kodigui
from .connection import plexapp
from .. import backgroundthread, utils, plex_functions as PF, variables as v

LOG = getLogger('PLEX.' + __name__)


class UserThumbTask(backgroundthread.Task):
    def setup(self, users, callback):
        self.users = users
        self.callback = callback
        return self

    def run(self):
        for user in self.users:
            if self.isCanceled():
                return
            thumb, back = user.thumb, ''
            self.callback(user, thumb, back)


class ServerListItem(kodigui.ManagedListItem):
    def init(self):
        self.dataSource.on('completed:reachability', self.onUpdate)
        self.dataSource.on('started:reachability', self.onUpdate)
        return self

    def safeSetProperty(self, key, value):
        # For if we catch the item in the middle of being removed
        try:
            self.setProperty(key, value)
            return True
        except AttributeError:
            return False

    def safeSetLabel(self, value):
        # For if we catch the item in the middle of being removed
        try:
            self.setLabel(value)
            return True
        except AttributeError:
            return False

    def onUpdate(self, **kwargs):
        if not self.listItem:  # ex. can happen on Kodi shutdown
            return

        if not self.dataSource.isSupported or not self.dataSource.isReachable():
            if self.dataSource.pendingReachabilityRequests > 0:
                self.safeSetProperty('status', 'refreshing.gif')
            else:
                self.safeSetProperty('status', 'unreachable.png')
        else:
            self.safeSetProperty('status', self.dataSource.isSecure and 'secure.png' or '')

        self.safeSetProperty('current', plexapp.SERVERMANAGER.selectedServer == self.dataSource and '1' or '')
        self.safeSetLabel(self.dataSource.name)

    def onDestroy(self):
        self.dataSource.off('completed:reachability', self.onUpdate)
        self.dataSource.off('started:reachability', self.onUpdate)


class ServerSelectWindow(kodigui.BaseWindow):
    xmlFile = 'script-plex-server_select.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    USER_LIST_ID = 101
    PIN_ENTRY_GROUP_ID = 400
    HOME_BUTTON_ID = 500
    SERVER_LIST_ID = 260

    def __init__(self, *args, **kwargs):
        self.tasks = None
        self.server = None
        self.aborted = False
        self.serverList = None
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def onFirstInit(self):
        self.serverList = kodigui.ManagedControlList(self,
                                                     self.SERVER_LIST_ID,
                                                     10)
        self.start()

    def onAction(self, action):
        try:
            ID = action.getId()
            if 57 < ID < 68:
                if not xbmc.getCondVisibility('ControlGroup({0}).HasFocus(0)'.format(self.PIN_ENTRY_GROUP_ID)):
                    item = self.userList.getSelectedItem()
                    if not item.dataSource.isProtected:
                        return
                    self.setFocusId(self.PIN_ENTRY_GROUP_ID)
                self.pinEntryClicked(ID + 142)
                return
            elif 142 <= ID <= 149:  # JumpSMS action
                if not xbmc.getCondVisibility('ControlGroup({0}).HasFocus(0)'.format(self.PIN_ENTRY_GROUP_ID)):
                    item = self.userList.getSelectedItem()
                    if not item.dataSource.isProtected:
                        return
                    self.setFocusId(self.PIN_ENTRY_GROUP_ID)
                self.pinEntryClicked(ID + 60)
                return
            elif ID in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_BACKSPACE):
                if xbmc.getCondVisibility('ControlGroup({0}).HasFocus(0)'.format(self.PIN_ENTRY_GROUP_ID)):
                    self.pinEntryClicked(211)
                    return
        except:
            utils.ERROR()

        kodigui.BaseWindow.onAction(self, action)

    def onClick(self, controlID):
        if controlID == self.USER_LIST_ID:
            item = self.userList.getSelectedItem()
            if item.dataSource.isProtected:
                self.setFocusId(self.PIN_ENTRY_GROUP_ID)
            else:
                self.userSelected(item)
        elif 200 < controlID < 212:
            self.pinEntryClicked(controlID)
        elif controlID == self.HOME_BUTTON_ID:
            self.home_button_clicked()

    def onFocus(self, controlID):
        if controlID == self.USER_LIST_ID:
            item = self.userList.getSelectedItem()
            item.setProperty('editing.pin', '')

    def showServers(self, from_refresh=False, mouse=False):
        selection = None
        if from_refresh:
            mli = self.serverList.getSelectedItem()
            if mli:
                selection = mli.dataSource
        else:
            plexapp.refreshResources()

        servers = sorted(
            plexapp.SERVERMANAGER.getServers(),
            key=lambda x: (x.owned and '0' or '1') + x.name.lower()
        )
        servers = PF.plex_gdm()

        items = []
        for s in servers:
            item = ServerListItem(s.name,
                                  not s.owned and s.owner or '',
                                  data_source=s).init()
            item.onUpdate()
            item.setProperty(
                'current',
                plexapp.SERVERMANAGER.selectedServer == s and '1' or '')
            items.append(item)

        if len(items) > 1:
            items[0].setProperty('first', '1')
            items[-1].setProperty('last', '1')
        elif items:
            items[0].setProperty('only', '1')

        self.serverList.replaceItems(items)

        self.getControl(800).setHeight((min(len(items), 9) * 100) + 80)

        if selection:
            for mli in self.serverList:
                if mli.dataSource == selection:
                    self.serverList.selectItem(mli.pos())
        if not from_refresh and items and not mouse:
            self.setFocusId(self.SERVER_LIST_ID)

    def start(self):
        self.setProperty('busy', '1')
        self.showServers()
        self.setProperty('initialized', '1')
        self.setProperty('busy', '')

    def home_button_clicked(self):
        """
        Action taken if user clicked the home button
        """
        self.server = None
        self.aborted = True
        self.doClose()

    def finished(self):
        for task in self.tasks:
            task.cancel()


def start():
    """
    Hit this function to open a dialog to choose the Plex user

    Returns
    =======
    tuple (server, aborted)
    server : PlexServer
        Or None if server switch failed or aborted by the server
    aborted : bool
        True if the server cancelled the dialog
    """
    w = ServerSelectWindow.open()
    server, aborted = w.server, w.aborted
    del w
    return server, aborted
