#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from . import kodigui
from .. import utils, variables as v

SEPARATOR = None


class DropdownDialog(kodigui.BaseDialog):
    xmlFile = 'script-plex-dropdown.xml'
    path = v.ADDON_PATH
    theme = 'Main'
    res = '1080i'
    width = 1920
    height = 1080

    GROUP_ID = 100
    OPTIONS_LIST_ID = 250

    def __init__(self, *args, **kwargs):
        kodigui.BaseDialog.__init__(self, *args, **kwargs)
        self.options = kwargs.get('options')
        self.pos = kwargs.get('pos')
        self.posIsBottom = kwargs.get('pos_is_bottom')
        self.closeDirection = kwargs.get('close_direction')
        self.setDropdownProp = kwargs.get('set_dropdown_prop', False)
        self.withIndicator = kwargs.get('with_indicator', False)
        self.suboptionCallback = kwargs.get('suboption_callback')
        self.closeOnPlaybackEnded = kwargs.get('close_on_playback_ended', False)
        self.header = kwargs.get('header')
        self.choice = None

    @property
    def x(self):
        return self.pos[0]

    @property
    def y(self):
        y = self.pos[1]
        if self.posIsBottom:
            y -= (len(self.options) * 66) + 80
        return y

    def onFirstInit(self):
        self.setProperty('dropdown', self.setDropdownProp and '1' or '')
        self.setProperty('header', self.header)
        self.optionsList = kodigui.ManagedControlList(self, self.OPTIONS_LIST_ID, 8)
        self.showOptions()
        height = min(66 * 14, (len(self.options) * 66)) + 80
        self.getControl(100).setPosition(self.x, self.y)

        shadowControl = self.getControl(110)
        if self.header:
            shadowControl.setHeight(height + 86)
            self.getControl(111).setHeight(height + 6)
        else:
            shadowControl.setHeight(height)

        self.setProperty('show', '1')
        self.setProperty('close.direction', self.closeDirection)
        if self.closeOnPlaybackEnded:
            from lib import player
            player.PLAYER.on('session.ended', self.playbackSessionEnded)

    def onAction(self, action):
        try:
            pass
        except:
            utils.ERROR()

        kodigui.BaseDialog.onAction(self, action)

    def onClick(self, controlID):
        if controlID == self.OPTIONS_LIST_ID:
            self.setChoice()
        else:
            self.doClose()

    def playbackSessionEnded(self, **kwargs):
        self.doClose()

    def setChoice(self):
        mli = self.optionsList.getSelectedItem()
        if not mli:
            return

        choice = self.options[self.optionsList.getSelectedPosition()]

        if choice.get('ignore'):
            return

        if self.suboptionCallback:
            options = self.suboptionCallback(choice)
            if options:
                sub = showDropdown(options, (self.x + 290, self.y + 10), close_direction='left', with_indicator=True)
                if not sub:
                    return

                choice['sub'] = sub

        self.choice = choice
        self.doClose()

    def showOptions(self):
        items = []
        options = []
        for o in self.options:
            if o:
                item = kodigui.ManagedListItem(o['display'], thumbnailImage=o.get('indicator', ''), data_source=o)
                item.setProperty('with.indicator', self.withIndicator and '1' or '')
                items.append(item)
                options.append(o)
            else:
                if items:
                    items[-1].setProperty('separator', '1')

        self.options = options

        if len(items) > 1:
            items[0].setProperty('first', '1')
            items[-1].setProperty('last', '1')
        elif items:
            items[0].setProperty('only', '1')

        self.optionsList.reset()
        self.optionsList.addItems(items)

        self.setFocusId(self.OPTIONS_LIST_ID)


class DropdownHeaderDialog(DropdownDialog):
    xmlFile = 'script-plex-dropdown_header.xml'


def showDropdown(
    options, pos=None,
    pos_is_bottom=False,
    close_direction='top',
    set_dropdown_prop=True,
    with_indicator=False,
    suboption_callback=None,
    close_on_playback_ended=False,
    header=None
):

    if header:
        pos = pos or (660, 400)
        w = DropdownHeaderDialog.open(
            options=options, pos=pos,
            pos_is_bottom=pos_is_bottom,
            close_direction=close_direction,
            set_dropdown_prop=set_dropdown_prop,
            with_indicator=with_indicator,
            suboption_callback=suboption_callback,
            close_on_playback_ended=close_on_playback_ended,
            header=header
        )
    else:
        pos = pos or (810, 400)
        w = DropdownDialog.open(
            options=options, pos=pos,
            pos_is_bottom=pos_is_bottom,
            close_direction=close_direction,
            set_dropdown_prop=set_dropdown_prop,
            with_indicator=with_indicator,
            suboption_callback=suboption_callback,
            close_on_playback_ended=close_on_playback_ended,
            header=header
        )
    choice = w.choice
    del w
    utils.garbageCollect()
    return choice
