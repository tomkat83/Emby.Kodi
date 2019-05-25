#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .plex_api import API
from . import utils, context_entry, transfer, backgroundthread, variables as v
from . import app, plex_functions as PF, playqueue as PQ

###############################################################################

LOG = getLogger('PLEX.playback_starter')

###############################################################################


class PlaybackTask(backgroundthread.Task):
    """
    Processes new plays
    """
    def __init__(self, command):
        self.command = command
        super(PlaybackTask, self).__init__()

    def run(self):
        LOG.debug('Starting PlaybackTask with %s', self.command)
        item = self.command
        try:
            _, params = item.split('?', 1)
        except ValueError:
            # E.g. other add-ons scanning for Extras folder
            LOG.debug('Detected 3rd party add-on call - ignoring')
            transfer.send(True)
            return
        params = dict(utils.parse_qsl(params))
        mode = params.get('mode')
        resolve = False if params.get('handle') == '-1' else True
        LOG.debug('Received mode: %s, params: %s', mode, params)
        if mode == 'plex_node':
            process_indirect(params['key'],
                             params['offset'],
                             resolve=resolve)
        elif mode == 'context_menu':
            context_entry.ContextMenu(kodi_id=params.get('kodi_id'),
                                      kodi_type=params.get('kodi_type'))
        LOG.debug('Finished PlaybackTask')


def process_indirect(key, offset, resolve=True):
    """
    Called e.g. for Plex "Play later" - Plex items where we need to fetch an
    additional xml for the actual playurl. In the PMS metadata, indirect="1" is
    set.

    Will release default.py with setResolvedUrl

    Set resolve to False if playback should be kicked off directly, not via
    setResolvedUrl
    """
    LOG.info('process_indirect called with key: %s, offset: %s, resolve: %s',
             key, offset, resolve)
    global RESOLVE
    RESOLVE = resolve
    offset = int(v.PLEX_TO_KODI_TIMEFACTOR * float(offset)) if offset != '0' else None
    if key.startswith('http') or key.startswith('{server}'):
        xml = PF.get_playback_xml(key, app.CONN.server_name)
    elif key.startswith('/system/services'):
        xml = PF.get_playback_xml('http://node.plexapp.com:32400%s' % key,
                                  'plexapp.com',
                                  authenticate=False,
                                  token=app.ACCOUNT.plex_token)
    else:
        xml = PF.get_playback_xml('{server}%s' % key, app.CONN.server_name)
    if xml is None:
        _ensure_resolve(abort=True)
        return

    api = API(xml[0])
    listitem = transfer.PKCListItem()
    api.create_listitem(listitem)
    playqueue = PQ.get_playqueue_from_type(
        v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[api.plex_type()])
    playqueue.clear()
    item = PQ.PlaylistItem(xml_video_element=xml[0])
    item.offset = offset
    item.playmethod = 'DirectStream'

    # Need to get yet another xml to get the final playback url
    try:
        xml = PF.get_playback_xml('http://node.plexapp.com:32400%s'
                                  % xml[0][0][0].attrib['key'],
                                  'plexapp.com',
                                  authenticate=False,
                                  token=app.ACCOUNT.plex_token)
    except (TypeError, IndexError, AttributeError):
        LOG.error('XML malformed: %s', xml.attrib)
        xml = None
    if xml is None:
        _ensure_resolve(abort=True)
        return
    try:
        playurl = xml[0].attrib['key']
    except (TypeError, IndexError, AttributeError):
        LOG.error('Last xml malformed: %s\n%s', xml.tag, xml.attrib)
        _ensure_resolve(abort=True)
        return

    item.file = playurl
    listitem.setPath(playurl.encode('utf-8'))
    playqueue.items.append(item)
    if resolve is True:
        transfer.send(listitem)
    else:
        LOG.info('Done initializing PKC playback, starting Kodi player')
        app.APP.player.play(item=playurl.encode('utf-8'),
                            listitem=listitem)


def _ensure_resolve(abort=False):
    """
    Will check whether RESOLVE=True and if so, fail Kodi playback startup
    with the path 'PKC_Dummy_Path_Which_Fails' using setResolvedUrl (and some
    pickling)

    This way we're making sure that other Python instances (calling default.py)
    will be destroyed.
    """
    if RESOLVE:
        # Releases the other Python thread without a ListItem
        transfer.send(True)
        # Shows PKC error message
        # transfer.send(None)
    if abort:
        # Reset some playback variables
        app.PLAYSTATE.context_menu_play = False
        app.PLAYSTATE.force_transcode = False
        app.PLAYSTATE.resume_playback = False
