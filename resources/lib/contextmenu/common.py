# -*- coding: utf-8 -*-
from xbmc import getInfoLabel

from ..plex_db import PlexDB


def kodi_item_from_listitem():
    kodi_id = getInfoLabel('ListItem.DBID') or None
    kodi_type = getInfoLabel('ListItem.DBTYPE') or None
    return int(kodi_id) if kodi_id else None, kodi_type


def plex_id_from_listitem():
    plex_id = getInfoLabel('ListItem.Property(plexid)')
    plex_id = int(plex_id) if plex_id else None
    if plex_id is None:
        kodi_id, kodi_type = kodi_item_from_listitem()
        if kodi_id is None or kodi_type is None:
            return
        with PlexDB(lock=False) as plexdb:
            item = plexdb.item_by_kodi_id(kodi_id, kodi_type)
        if item:
            plex_id = item['plex_id']
    return plex_id
