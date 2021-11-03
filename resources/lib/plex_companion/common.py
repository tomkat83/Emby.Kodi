#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .. import variables as v
from .. import app


def log_error(logger, error_message, response):
    logger('%s: %s: %s', error_message, response.status_code, response.reason)
    logger('headers received from the PMS: %s', response.headers)
    logger('Message received from the PMS: %s', response.text)


def proxy_headers():
    return {
        'X-Plex-Client-Identifier': v.PKC_MACHINE_IDENTIFIER,
        'X-Plex-Product': v.ADDON_NAME,
        'X-Plex-Version': v.ADDON_VERSION,
        'X-Plex-Platform': v.PLATFORM,
        'X-Plex-Platform-Version': v.PLATFORM_VERSION,
        'X-Plex-Device-Name': v.DEVICENAME,
        'Content-Type': 'text/xml;charset=utf-8'
    }


def proxy_params():
    params = {
        'deviceClass': 'pc',
        'protocolCapabilities': 'timeline,playback,navigation,playqueues',
        'protocolVersion': 3
    }
    if app.ACCOUNT.pms_token:
        params['X-Plex-Token'] = app.ACCOUNT.pms_token
    return params
