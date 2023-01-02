# -*- coding: utf-8 -*-
"""
Grabs the Plex id for the Kodi item the context menu was called for
and displays a menu displaying extras like trailers.
"""
from xbmc import executebuiltin

from resources.lib.contextmenu.common import plex_id_from_listitem


def main():
    plex_id = plex_id_from_listitem()
    if plex_id is None:
        return
    handle = ('plugin://plugin.video.plexkodiconnect?mode=extras&plex_id=%s'
              % plex_id)
    executebuiltin('ActivateWindow(videos,\"%s\",return)' % handle)


if __name__ == "__main__":
    main()
