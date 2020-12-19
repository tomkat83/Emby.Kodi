#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import xbmc
###############################################################################
LEVELS = {
    logging.ERROR: xbmc.LOGERROR,
    logging.WARNING: xbmc.LOGWARNING,
    logging.INFO: xbmc.LOGINFO,
    logging.DEBUG: xbmc.LOGDEBUG
}
###############################################################################


def config():
    logger = logging.getLogger('PLEX')
    logger.addHandler(LogHandler())
    logger.setLevel(logging.DEBUG)


class LogHandler(logging.StreamHandler):
    def __init__(self):
        logging.StreamHandler.__init__(self)
        self.setFormatter(logging.Formatter(fmt='%(name)s: %(message)s'))

    def emit(self, record):
        xbmc.log(self.format(record), level=LEVELS[record.levelno])
