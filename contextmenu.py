# -*- coding: utf-8 -*-
###############################################################################
from __future__ import absolute_import, division, unicode_literals
from sys import listitem
from urllib import urlencode

from xbmc import getCondVisibility, sleep
from xbmcgui import Window

###############################################################################


def _get_kodi_type():
    kodi_type = listitem.getVideoInfoTag().getMediaType().decode('utf-8')
    if not kodi_type:
        if getCondVisibility('Container.Content(albums)'):
            kodi_type = "album"
        elif getCondVisibility('Container.Content(artists)'):
            kodi_type = "artist"
        elif getCondVisibility('Container.Content(songs)'):
            kodi_type = "song"
        elif getCondVisibility('Container.Content(pictures)'):
            kodi_type = "picture"
    return kodi_type


def main():
    """
    Grabs kodi_id and kodi_type and sends a request to our main python instance
    that context menu needs to be displayed
    """
    window = Window(10000)
    kodi_id = listitem.getVideoInfoTag().getDbId()
    if kodi_id == -1:
        # There is no getDbId() method for getMusicInfoTag
        # YET TO BE IMPLEMENTED - lookup ID using path
        kodi_id = listitem.getMusicInfoTag().getURL()
    kodi_type = _get_kodi_type()
    args = {
        'kodi_id': kodi_id,
        'kodi_type': kodi_type
    }
    while window.getProperty('plex_command'):
        sleep(20)
    window.setProperty('plex_command', 'CONTEXT_menu?%s' % urlencode(args))


if __name__ == "__main__":
    main()
