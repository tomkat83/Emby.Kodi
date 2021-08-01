#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from datetime import datetime, timedelta
from time import localtime, strftime

LOG = getLogger('PLEX.timing')

EPOCH = datetime.utcfromtimestamp(0)


def unix_timestamp(seconds_into_the_future=None):
    """
    Returns a Unix time stamp (seconds passed since January 1 1970) for NOW as
    an integer.

    Optionally, pass seconds_into_the_future: positive int's will result in a
    future timestamp, negative the past
    """
    if seconds_into_the_future:
        future = datetime.utcnow() + timedelta(seconds=seconds_into_the_future)
    else:
        future = datetime.utcnow()
    return int((future - EPOCH).total_seconds())


def unix_date_to_kodi(unix_kodi_time):
    """
    converts a Unix time stamp (seconds passed sinceJanuary 1 1970) to a
    propper, human-readable time stamp used by Kodi

    Output: Y-m-d h:m:s = 2009-04-05 23:16:04
    """
    try:
        return strftime('%Y-%m-%d %H:%M:%S', localtime(float(unix_kodi_time)))
    except Exception as exception:
        LOG.error(exception)
        LOG.error('Received an illegal timestamp from Plex: %s, type %s. '
                  'Using 1970-01-01 12:00:00',
                  unix_kodi_time, type(unix_kodi_time))
        return '1970-01-01 12:00:00'


def plex_date_to_kodi(plex_timestamp):
    """
    converts a PMS epoch time stamp (seconds passed since January 1 1970, Plex
    sends timezone-independent epoch) to a propper, human-readable time stamp
    used by Kodi (varies per time-zone!)

    Output: Y-m-d h:m:s = 2009-04-05 23:16:04

    Returns None if plex_timestamp is not valid (e.g. -1))
    """
    try:
        return unix_date_to_kodi(plex_timestamp)
    except ValueError:
        # the PMS can return -1 as plex_timestamp - great!
        pass


def plex_now():
    return unix_timestamp()


def kodi_timestamp(plex_timestamp):
    return unix_date_to_kodi(plex_timestamp)


def kodi_now():
    return unix_date_to_kodi(unix_timestamp())


def millis_to_kodi_time(milliseconds):
    """
    Converts time in milliseconds [int or float] to the time dict used by the
    Kodi JSON RPC:
    {
        'hours': [int],
        'minutes': [int],
        'seconds'[int],
        'milliseconds': [int]
    }
    """
    seconds = int(milliseconds / 1000)
    minutes = int(seconds / 60)
    return {'hours': int(minutes / 60),
            'minutes': int(minutes % 60),
            'seconds': int(seconds % 60),
            'milliseconds': int(milliseconds % 1000)}


def kodi_time_to_millis(time):
    """
    Converts the Kodi time dict
    {
        'hours': [int],
        'minutes': [int],
        'seconds'[int],
        'milliseconds': [int]
    }
    to milliseconds [int]. Will not return negative results but 0!
    """
    ret = (time['hours'] * 3600 +
           time['minutes'] * 60 +
           time['seconds']) * 1000 + time['milliseconds']
    return 0 if ret < 0 else ret
