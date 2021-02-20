# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from xbmcgui import WindowXMLDialog

from .. import app

logger = getLogger('PLEX.skipintro')


class SkipIntroDialog(WindowXMLDialog):

    def __init__(self, *args, **kwargs):
        self.intro_end = kwargs.pop('intro_end', None)

        self._showing = False
        self._on_hold = False

        logger.debug('SkipIntroDialog initialized, ends at %s',
                     self.intro_end)
        WindowXMLDialog.__init__(self, *args, **kwargs)

    def show(self):
        if not self.intro_end:
            self.close()
            return

        if not self.on_hold and not self.showing:
            logger.debug('Showing dialog')
            self.showing = True
            WindowXMLDialog.show(self)

    def close(self):
        if self.showing:
            self.showing = False
            logger.debug('Closing dialog')
            WindowXMLDialog.close(self)

    def onClick(self, control_id):  # pylint: disable=invalid-name
        if self.intro_end and control_id == 3002:  # 3002 = Skip Intro button
            if app.APP.is_playing:
                self.on_hold = True
                logger.info('Skipping intro, seeking to %s', self.intro_end)
                app.APP.player.seekTime(self.intro_end)
                self.close()

    def onAction(self, action):  # pylint: disable=invalid-name
        close_actions = [10, 13, 92]
        # 10 = previousmenu, 13 = stop, 92 = back
        if action in close_actions:
            self.on_hold = True
            self.close()

    @property
    def showing(self):
        return self._showing

    @showing.setter
    def showing(self, value):
        self._showing = bool(value)

    @property
    def on_hold(self):
        return self._on_hold

    @on_hold.setter
    def on_hold(self, value):
        self._on_hold = bool(value)
