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
from .. import backgroundthread, utils, plex_tv, variables as v

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


class UserSelectWindow(kodigui.BaseWindow):
    xmlFile = 'script-plex-user_select.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    USER_LIST_ID = 101
    PIN_ENTRY_GROUP_ID = 400
    HOME_BUTTON_ID = 500

    def __init__(self, *args, **kwargs):
        self.task = None
        self.user = None
        self.aborted = False
        kodigui.BaseWindow.__init__(self, *args, **kwargs)

    def onFirstInit(self):
        self.userList = kodigui.ManagedControlList(self, self.USER_LIST_ID, 6)

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

    def userThumbCallback(self, user, thumb, back):
        item = self.userList.getListItemByDataSource(user)
        if item:
            item.setThumbnailImage(thumb)
            item.setProperty('back.image', back)

    def start(self):
        self.setProperty('busy', '1')
        try:
            users = plex_tv.plex_home_users(utils.settings('plexToken'))

            items = []
            for user in users:
                # thumb, back = image.getImage(user.thumb, user.id)
                # mli = kodigui.ManagedListItem(user.title, thumbnailImage=thumb, data_source=user)
                mli = kodigui.ManagedListItem(user.title, user.title[0].upper(), data_source=user)
                mli.setProperty('pin', user.title)
                # mli.setProperty('back.image', back)
                mli.setProperty('protected', user.isProtected and '1' or '')
                mli.setProperty('admin', user.isAdmin and '1' or '')
                items.append(mli)

            self.userList.addItems(items)
            self.task = UserThumbTask().setup(users, self.userThumbCallback)
            backgroundthread.BGThreader.addTask(self.task)

            self.setFocusId(self.USER_LIST_ID)
            self.setProperty('initialized', '1')
        finally:
            self.setProperty('busy', '')

    def home_button_clicked(self):
        """
        Action taken if user clicked the home button
        """
        self.user = None
        self.aborted = True
        self.doClose()

    def pinEntryClicked(self, controlID):
        item = self.userList.getSelectedItem()
        pin = item.getProperty('editing.pin') or ''

        if len(pin) > 3:
            return

        if controlID < 210:
            pin += str(controlID - 200)
        elif controlID == 210:
            pin += '0'
        elif controlID == 211:
            pin = pin[:-1]

        if pin:
            item.setProperty('pin', ' '.join(list(u"\u2022" * len(pin))))
            item.setProperty('editing.pin', pin)
            if len(pin) > 3:
                self.userSelected(item, pin)
        else:
            item.setProperty('pin', item.dataSource.title)
            item.setProperty('editing.pin', '')

    def userSelected(self, item, pin=None):
        self.user = item.dataSource
        LOG.info('Home user selected: %s', self.user)
        self.user.authToken = plex_tv.switch_home_user(
            self.user.id,
            pin,
            utils.settings('plexToken'),
            utils.settings('plex_machineIdentifier'))
        if self.user.authToken is None:
            self.user = None
            item.setProperty('pin', item.dataSource.title)
            item.setProperty('editing.pin', '')
            # 'Error': 'Login failed with plex.tv for user'
            utils.messageDialog(utils.lang(30135),
                                '%s %s' % (utils.lang(39229),
                                           self.user.username))
            return
        self.doClose()

    def finished(self):
        if self.task:
            self.task.cancel()


def start():
    """
    Hit this function to open a dialog to choose the Plex user

    Returns
    =======
    tuple (user, aborted)
    user : HomeUser
        Or None if user switch failed or aborted by the user)
    aborted : bool
        True if the user cancelled the dialog
    """
    w = UserSelectWindow.open()
    user, aborted = w.user, w.aborted
    del w
    return user, aborted
