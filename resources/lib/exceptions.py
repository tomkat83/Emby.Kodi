#!/usr/bin/env python
# -*- coding: utf-8 -*-


class PlaylistError(Exception):
    """
    Exception for our playlist constructs
    """
    pass


class LockedDatabase(Exception):
    """
    Dedicated class to make sure we're not silently catching locked DBs.
    """
    pass


class SubtitleError(Exception):
    """
    Exceptions relating to subtitles
    """
    pass


class ProcessingNotDone(Exception):
    """
    Exception to detect whether we've completed our sync and did not have to
    abort or suspend.
    """
    pass
