#!/usr/bin/env python
# -*- coding: utf-8 -*-
from ..utils import cast
from .. import timing, variables as v, app


class User(object):
    def viewcount(self):
        """
        Returns the play count for the item as an int or the int 0 if not found
        """
        return cast(int, self.xml.get('viewCount')) or 0

    def resume_point(self):
        """
        Returns the resume point of time in seconds as float. 0.0 if not found
        """
        resume = cast(float, self.xml.get('viewOffset')) or 0.0
        return resume * v.PLEX_TO_KODI_TIMEFACTOR

    def resume_point_plex(self):
        """
        Returns the resume point of time in microseconds as float.
        0.0 if not found
        """
        return cast(float, self.xml.get('viewOffset')) or 0.0

    def userrating(self):
        """
        Returns the userRating [int].
        If the user chose to replace user ratings with the number of different
        file versions for a specific video, that number is returned instead
        (at most 10)

        0 is returned if something goes wrong
        """
        if (app.SYNC.indicate_media_versions is True and
                self.plex_type in (v.PLEX_TYPE_MOVIE, v.PLEX_TYPE_EPISODE)):
            userrating = 0
            for _ in self.xml.findall('./Media'):
                userrating += 1
            # Don't show a value of '1' - which we'll always have for normal
            # Plex library items
            return 0 if userrating == 1 else min(userrating, 10)
        else:
            return cast(int, self.xml.get('userRating')) or 0

    def lastplayed(self):
        """
        Returns the Kodi timestamp [unicode] for the last point of time, when
        this item was played.
        Returns None if this fails - item has never been played
        """
        try:
            return timing.plex_date_to_kodi(int(self.xml.get('lastViewedAt')))
        except TypeError:
            pass
