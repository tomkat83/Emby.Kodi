# -*- coding: utf-8 -*-
from logging import getLogger

from xbmcgui import WindowXMLDialog

from .. import app, variables as v

log = getLogger('PLEX.skipmarkerdialog')


class SkipMarkerDialog(WindowXMLDialog):
    xmlFile = 'script-plex-skip_marker.xml'
    path = v.ADDON_PATH
    theme = 'default'
    res = '1080i'
    width = 1920
    height = 1080

    def __init__(self, *args, **kwargs):
        self.marker_message = kwargs.pop('marker_message')
        self.setProperty('marker_message', self.marker_message)
        self.marker_end = kwargs.pop('marker_end', None)
        self.creation_time = kwargs.pop('creation_time', None)

        log.debug('SkipMarkerDialog with message %s, ends at %s',
                  self.marker_message, self.marker_end)
        super().__init__(*args, **kwargs)

    def seekTimeToEnd(self):
        log.info('Skipping marker, seeking to %s', self.marker_end)
        app.APP.player.seekTime(self.marker_end)

    def onClick(self, control_id):  # pylint: disable=invalid-name
        if self.marker_end and control_id == 3002:  # 3002 = Skip Marker button
            if app.APP.is_playing:
                self.on_hold = True
                self.seekTimeToEnd()
                self.close()

    def onAction(self, action):  # pylint: disable=invalid-name
        close_actions = [10, 13, 92]
        # 10 = previousmenu, 13 = stop, 92 = back
        if action in close_actions:
            self.on_hold = True
            self.close()

    @property
    def on_hold(self):
        return self._on_hold

    @on_hold.setter
    def on_hold(self, value):
        self._on_hold = bool(value)
