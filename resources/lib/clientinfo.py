#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

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
        'Connection': 'keep-alive',
        "Content-Type": "application/x-www-form-urlencoded",
        # "Access-Control-Allow-Origin": "*",
        # 'X-Plex-Language': 'en',
        'X-Plex-Device': v.ADDON_NAME,
        'X-Plex-Client-Platform': v.PLATFORM,
        'X-Plex-Device-Name': v.DEVICENAME,
        'X-Plex-Platform': v.PLATFORM,
        # 'X-Plex-Platform-Version': 'unknown',
        # 'X-Plex-Model': 'unknown',
        'X-Plex-Product': v.ADDON_NAME,
        'X-Plex-Version': v.ADDON_VERSION,
        'X-Plex-Client-Identifier': getDeviceId(),
        'X-Plex-Provides': 'client,controller,player,pubsub-player',
    }
    if include_token and utils.window('pms_token'):
        xargs['X-Plex-Token'] = utils.window('pms_token')
    if options is not None:
        xargs.update(options)
    return xargs


def getDeviceId(reset=False):
    """
    Returns a unique Plex client id "X-Plex-Client-Identifier" from Kodi
    settings file.
    Also loads Kodi window property 'plex_client_Id'

    If id does not exist, create one and save in Kodi settings file.
    """
    if reset is True:
        v.PKC_MACHINE_IDENTIFIER = None
        utils.window('plex_client_Id', clear=True)
        utils.settings('plex_client_Id', value="")

    client_id = v.PKC_MACHINE_IDENTIFIER
    if client_id:
        return client_id

    client_id = utils.settings('plex_client_Id')
    # Because Kodi appears to cache file settings!!
    if client_id != "" and reset is False:
        v.PKC_MACHINE_IDENTIFIER = client_id
        utils.window('plex_client_Id', value=client_id)
        LOG.info("Unique device Id plex_client_Id loaded: %s", client_id)
        return client_id

    LOG.info("Generating a new deviceid.")
    from uuid import uuid4
    client_id = str(uuid4())
    utils.settings('plex_client_Id', value=client_id)
    v.PKC_MACHINE_IDENTIFIER = client_id
    utils.window('plex_client_Id', value=client_id)
    LOG.info("Unique device Id plex_client_Id generated: %s", client_id)
    return client_id
