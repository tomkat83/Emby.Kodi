#!/usr/bin/env python
# -*- coding: utf-8 -*-
###############################################################################
from __future__ import absolute_import, division, unicode_literals
import xbmc
import xbmcgui
import xbmcaddon


def start():
    # Safety net - Kodi starts PKC twice upon first installation!
    if xbmc.getInfoLabel(
            'Window(10000).Property(plugin.video.plexkodiconnect.running)').decode('utf-8') == '1':
        xbmc.log('PLEX: PlexKodiConnect is already running',
                 level=xbmc.LOGWARNING)
        return
    else:
        xbmcgui.Window(10000).setProperty(
            'plugin.video.plexkodiconnect.running', '1')
    try:
        # We might have to wait a bit before starting PKC
        delay = int(xbmcaddon.Addon(
            id='plugin.video.plexkodiconnect').getSetting('startupDelay'))
        xbmc.log('PLEX: Delaying PKC startup by: %s seconds'.format(delay),
                 level=xbmc.LOGNOTICE)
        if delay and xbmc.Monitor().waitForAbort(delay):
            xbmc.log('PLEX: Kodi shutdown while waiting for PKC startup',
                     level=xbmc.LOGWARNING)
            return
        from resources.lib import main
        main.main()
    finally:
        xbmcgui.Window(10000).setProperty(
            'plugin.video.plexkodiconnect.running', '')


if __name__ == '__main__':
    start()
