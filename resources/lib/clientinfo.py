#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

import xbmc

from . import utils
from . import variables as v

###############################################################################

LOG = getLogger('PLEX.clientinfo')

###############################################################################


def getXArgsDeviceInfo(options=None, include_token=True):
    """
    Returns a dictionary that can be used as headers for GET and POST
    requests. An authentication option is NOT yet added.

    Inputs:
        options:        dictionary of options that will override the
                        standard header options otherwise set.
        include_token:  set to False if you don't want to include the Plex token
                        (e.g. for Companion communication)
    Output:
        header dictionary
    """
    xargs = {
        'Accept': '*/*',
        "Content-Type": "application/x-www-form-urlencoded",
        # "Access-Control-Allow-Origin": "*",
        'Accept-Language': xbmc.getLanguage(xbmc.ISO_639_1),
        'X-Plex-Device': v.DEVICE,
        'X-Plex-Model': v.MODEL,
        'X-Plex-Device-Name': v.DEVICENAME,
        'X-Plex-Platform': v.PLATFORM,
        'X-Plex-Platform-Version': v.PLATFORM_VERSION,
        'X-Plex-Product': v.ADDON_NAME,
        'X-Plex-Version': v.ADDON_VERSION,
        'X-Plex-Client-Identifier': getDeviceId(),
        'X-Plex-Provides': 'client,controller,player,pubsub-player',
        'X-Plex-Protocol': '1.0',
        'Cache-Control': 'no-cache'
    }
    if include_token and utils.window('pms_token'):
        xargs['X-Plex-Token'] = utils.window('pms_token')
    if options is not None:
        xargs.update(options)
    return xargs


def generate_device_id():
    LOG.info("Generating a new deviceid.")
    from uuid import uuid4
    client_id = str(uuid4())
    utils.settings('plex_client_Id', value=client_id)
    v.PKC_MACHINE_IDENTIFIER = client_id
    utils.window('plex_client_Id', value=client_id)
    LOG.info("Unique device Id plex_client_Id generated: %s", client_id)
    # IF WE EXIT KODI NOW, THE SETTING WON'T STICK!
    # 'Kodi will now restart to apply the changes'
    # utils.messageDialog(utils.lang(29999), utils.lang(33033))
    # xbmc.executebuiltin('RestartApp')
    utils.messageDialog(utils.lang(29999), 'Please restart Kodi now!')
    return client_id


def getDeviceId(reset=False):
    """
    Returns a unique Plex client id "X-Plex-Client-Identifier" from Kodi
    settings file.
    Also loads Kodi window property 'plex_client_Id'

    If id does not exist, create one and save in Kodi settings file.
    """
    if reset:
        return generate_device_id()

    client_id = v.PKC_MACHINE_IDENTIFIER
    if client_id:
        return client_id

    client_id = utils.settings('plex_client_Id')
    if client_id != "":
        v.PKC_MACHINE_IDENTIFIER = client_id
        utils.window('plex_client_Id', value=client_id)
        LOG.info("Unique device Id plex_client_Id loaded: %s", client_id)
        return client_id
    else:
        return generate_device_id()
