#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
plex_api interfaces with all Plex Media Server (and plex.tv) xml responses
"""
from .base import Base
from .artwork import Artwork
from .file import File
from .media import Media
from .user import User
from .playback import Playback

from ..plex_db import PlexDB


class API(Base, Artwork, File, Media, User, Playback):
    pass


def mass_api(xml, check_by_guid=False):
    """
    Pass in an entire XML PMS response with e.g. several movies or episodes
    Will Look-up Kodi ids in the Plex.db for every element (thus speeding up
    this process for several PMS items!)
    Avoid a lookup by guid instead of the plex id (check_by_guid=True) as
    it will be way slower
    """
    apis = [API(x) for x in xml]
    if check_by_guid:
        # A single guid might return a bunch of different plex id's
        # We extend the xml list with these ids
        new_apis = list()
        with PlexDB(lock=False) as plexdb:
            for i, api in enumerate(apis):
                items = api.check_by_guid(plexdb=plexdb)
                for item in items:
                    new_api = apis[i]
                    # Since we cannot simply set the plex_id and type.
                    # This will overwrite a weird "guid ratingKey" that
                    # plex set, originally looking e.g. like
                    # ratingKey="5d776883ebdf2200209c104e"
                    new_api.xml.set('ratingKey', str(item['plex_id']))
                    new_api.xml.set('key', f'/library/metadata/{item["plex_id"]}')
                    new_api.check_db(plexdb=plexdb)
                    new_apis.append(new_api)
        return new_apis
    else:
        with PlexDB(lock=False) as plexdb:
            for api in apis:
                api.check_db(plexdb=plexdb)
        return apis
