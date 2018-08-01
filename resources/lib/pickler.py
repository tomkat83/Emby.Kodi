#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from cPickle import dumps, loads
from xbmcgui import Window
from xbmc import log, LOGDEBUG

###############################################################################
WINDOW = Window(10000)
PREFIX = 'PLEX.pickler: '
###############################################################################


def try_encode(input_str, encoding='utf-8'):
    """
    Will try to encode input_str (in unicode) to encoding. This possibly
    fails with e.g. Android TV's Python, which does not accept arguments for
    string.encode()

    COPY to avoid importing utils on calling default.py
    """
    if isinstance(input_str, str):
        # already encoded
        return input_str
    try:
        input_str = input_str.encode(encoding, "ignore")
    except TypeError:
        input_str = input_str.encode()
    return input_str


def pickl_window(property, value=None, clear=False):
    """
    Get or set window property - thread safe! For use with Pickle
    Property and value must be string
    """
    if clear:
        WINDOW.clearProperty(property)
    elif value is not None:
        WINDOW.setProperty(property, value)
    else:
        return try_encode(WINDOW.getProperty(property))


def pickle_me(obj, window_var='plex_result'):
    """
    Pickles the obj to the window variable. Use to transfer Python
    objects between different PKC python instances (e.g. if default.py is
    called and you'd want to use the service.py instance)

    obj can be pretty much any Python object. However, classes and
    functions won't work. See the Pickle documentation
    """
    log('%sStart pickling' % PREFIX, level=LOGDEBUG)
    pickl_window(window_var, value=dumps(obj))
    log('%sSuccessfully pickled' % PREFIX, level=LOGDEBUG)


def unpickle_me(window_var='plex_result'):
    """
    Unpickles a Python object from the window variable window_var.
    Will then clear the window variable!
    """
    result = pickl_window(window_var)
    pickl_window(window_var, clear=True)
    log('%sStart unpickling' % PREFIX, level=LOGDEBUG)
    obj = loads(result)
    log('%sSuccessfully unpickled' % PREFIX, level=LOGDEBUG)
    return obj


class Playback_Successful(object):
    """
    Used to communicate with another PKC Python instance
    """
    listitem = None
