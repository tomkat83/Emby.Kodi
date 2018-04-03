# -*- coding: utf-8 -*-

###############################################################################
from logging import getLogger

from utils import window, settings
import variables as v

###############################################################################

log = getLogger("PLEX."+__name__)

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
    if include_token and window('pms_token'):
        xargs['X-Plex-Token'] = window('pms_token')
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
        window('plex_client_Id', clear=True)
        settings('plex_client_Id', value="")

    client_id = v.PKC_MACHINE_IDENTIFIER
    if client_id:
        return client_id

    client_id = settings('plex_client_Id')
    # Because Kodi appears to cache file settings!!
    if client_id != "" and reset is False:
        v.PKC_MACHINE_IDENTIFIER = client_id
        window('plex_client_Id', value=client_id)
        log.info("Unique device Id plex_client_Id loaded: %s", client_id)
        return client_id

    log.info("Generating a new deviceid.")
    from uuid import uuid4
    client_id = str(uuid4())
    settings('plex_client_Id', value=client_id)
    v.PKC_MACHINE_IDENTIFIER = client_id
    window('plex_client_Id', value=client_id)
    log.info("Unique device Id plex_client_Id generated: %s", client_id)
    return client_id
