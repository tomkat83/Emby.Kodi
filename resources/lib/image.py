#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from . import util, path_ops

CACHE_PATH = path_ops.path.join(util.PROFILE, 'avatars', '')
if not path_ops.exists(CACHE_PATH):
    path_ops.makedirs(CACHE_PATH)


def getImage(url, ID):
    return url, ''
