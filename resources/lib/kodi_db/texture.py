#!/usr/bin/env python
# -*- coding: utf-8 -*-
from . import common


class KodiTextureDB(common.KodiDBBase):
    db_kind = 'texture'

    def url_not_yet_cached(self, url):
        """
        Returns True if url has not yet been cached to the Kodi texture cache
        """
        self.artcursor.execute('SELECT url FROM texture WHERE url = ? LIMIT 1',
                               (url, ))
        return self.artcursor.fetchone() is None
