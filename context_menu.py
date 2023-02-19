# -*- coding: utf-8 -*-
"""
Grabs kodi_id and kodi_type for the Kodi item the context menu was called for
and sends a request to our main Python instance that the PKC context menu needs
to be displayed
"""
from urllib.parse import urlencode

from xbmc import sleep
from xbmcgui import Window

from resources.lib.contextmenu.common import kodi_item_from_listitem


def main():
    kodi_id, kodi_type = kodi_item_from_listitem()
    args = {
        'kodi_id': kodi_id,
        'kodi_type': kodi_type
    }
    window = Window(10000)
    while window.getProperty('plexkodiconnect.command'):
        sleep(20)
    window.setProperty('plexkodiconnect.command',
                       'CONTEXT_menu?%s' % urlencode(args))


if __name__ == "__main__":
    main()
