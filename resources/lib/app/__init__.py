#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Used to save PKC's application state and share between modules. Be careful
if you invoke another PKC Python instance (!!) when e.g. PKC.movies is called
"""

from .account import Account
from .application import App
from .connection import Connection
from .libsync import Sync
from .playstate import PlayState

ACCOUNT = None
APP = None
CONN = None
SYNC = None
PLAYSTATE = None


def init(entrypoint=False):
    """
    entrypoint=True initiates only the bare minimum - for other PKC python
    instances
    """
    global ACCOUNT, APP, CONN, SYNC, PLAYSTATE
    APP = App(entrypoint)
    CONN = Connection(entrypoint)
    ACCOUNT = Account(entrypoint)
    SYNC = Sync(entrypoint)
    if not entrypoint:
        PLAYSTATE = PlayState()
