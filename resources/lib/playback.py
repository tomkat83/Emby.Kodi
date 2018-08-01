#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Used to kick off Kodi playback
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from threading import Thread
from xbmc import Player, sleep

from .plex_api import API
from . import plex_functions as PF
from . import utils
from .downloadutils import DownloadUtils as DU
from . import plexdb_functions as plexdb
from . import kodidb_functions as kodidb
from . import playlist_func as PL
from . import playqueue as PQ
from . import json_rpc as js
from . import pickler
from .playutils import PlayUtils
from .pkc_listitem import PKCListItem
from . import variables as v
from . import state

###############################################################################
LOG = getLogger('PLEX.playback')
# Do we need to return ultimately with a setResolvedUrl?
RESOLVE = True
###############################################################################


def playback_triage(plex_id=None, plex_type=None, path=None, resolve=True):
    """
    Hit this function for addon path playback, Plex trailers, etc.
    Will setup playback first, then on second call complete playback.

    Will set Playback_Successful() with potentially a PKCListItem() attached
    (to be consumed by setResolvedURL in default.py)

    If trailers or additional (movie-)parts are added, default.py is released
    and a completely new player instance is called with a new playlist. This
    circumvents most issues with Kodi & playqueues

    Set resolve to False if you do not want setResolvedUrl to be called on
    the first pass - e.g. if you're calling this function from the original
    service.py Python instance
    """
    LOG.info('playback_triage called with plex_id %s, plex_type %s, path %s, '
             'resolve %s', plex_id, plex_type, path, resolve)
    global RESOLVE
    # If started via Kodi context menu, we never resolve
    RESOLVE = resolve if not state.CONTEXT_MENU_PLAY else False
    if not state.AUTHENTICATED:
        LOG.error('Not yet authenticated for PMS, abort starting playback')
        # "Unauthorized for PMS"
        utils.dialog('notification', utils.lang(29999), utils.lang(30017))
        _ensure_resolve(abort=True)
        return
    playqueue = PQ.get_playqueue_from_type(
        v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[plex_type])
    try:
        pos = js.get_position(playqueue.playlistid)
    except KeyError:
        # Kodi bug - Playlist plays (not Playqueue) will ALWAYS be audio for
        # add-on paths
        LOG.info('No position returned from Kodi player! Assuming playlist')
        playqueue = PQ.get_playqueue_from_type(v.KODI_PLAYLIST_TYPE_AUDIO)
        try:
            pos = js.get_position(playqueue.playlistid)
        except KeyError:
            LOG.info('Assuming video instead of audio playlist playback')
            playqueue = PQ.get_playqueue_from_type(v.KODI_PLAYLIST_TYPE_VIDEO)
            try:
                pos = js.get_position(playqueue.playlistid)
            except KeyError:
                LOG.error('Still no position - abort')
                # "Play error"
                utils.dialog('notification',
                             utils.lang(29999),
                             utils.lang(30128),
                             icon='{error}')
                _ensure_resolve(abort=True)
                return
    # HACK to detect playback of playlists for add-on paths
    items = js.playlist_get_items(playqueue.playlistid)
    try:
        item = items[pos]
    except IndexError:
        LOG.info('Could not apply playlist hack! Probably Widget playback')
    else:
        if ('id' not in item and
                item.get('type') == 'unknown' and item.get('title') == ''):
            LOG.info('Kodi playlist play detected')
            _playlist_playback(plex_id, plex_type)
            return

    # Can return -1 (as in "no playlist")
    pos = pos if pos != -1 else 0
    LOG.debug('playQueue position %s for %s', pos, playqueue)
    # Have we already initiated playback?
    try:
        item = playqueue.items[pos]
    except IndexError:
        LOG.debug('PKC playqueue yet empty, need to initialize playback')
        initiate = True
    else:
        if item.plex_id != plex_id:
            LOG.debug('Received new plex_id %s, expected %s. Init playback',
                      plex_id, item.plex_id)
            initiate = True
        else:
            initiate = False
    with state.LOCK_PLAYQUEUES:
        if initiate:
            _playback_init(plex_id, plex_type, playqueue, pos)
        else:
            # kick off playback on second pass
            _conclude_playback(playqueue, pos)


def _playlist_playback(plex_id, plex_type):
    """
    Really annoying Kodi behavior: Kodi will throw the ENTIRE playlist some-
    where, causing Playlist.onAdd to fire for each item like this:
    Playlist.OnAdd Data: {u'item': {u'type': u'episode', u'id': 164},
                          u'playlistid': 0,
                          u'position': 2}
    This does NOT work for Addon paths, type and id will be unknown:
        {u'item': {u'type': u'unknown'},
         u'playlistid': 0,
         u'position': 7}
    At the end, only the element being played actually shows up in the Kodi
    playqueue.
    Hence: if we fail the first addon paths call, Kodi will start playback
    for the next item in line :-)
    (by the way: trying to get active Kodi player id will return [])
    """
    xml = PF.GetPlexMetadata(plex_id)
    try:
        xml[0].attrib
    except (IndexError, TypeError, AttributeError):
        LOG.error('Could not get a PMS xml for plex id %s', plex_id)
        # "Play error"
        utils.dialog('notification',
                     utils.lang(29999),
                     utils.lang(30128),
                     icon='{error}')
        _ensure_resolve(abort=True)
        return
    # Kodi bug: playqueue will ALWAYS be audio playqueue UNTIL playback
    # has actually started. Need to tell Kodimonitor
    playqueue = PQ.get_playqueue_from_type(v.KODI_PLAYLIST_TYPE_AUDIO)
    playqueue.clear(kodi=False)
    # Set the flag for the potentially WRONG audio playlist so Kodimonitor
    # can pick up on it
    playqueue.kodi_playlist_playback = True
    playlist_item = PL.playlist_item_from_xml(xml[0])
    playqueue.items.append(playlist_item)
    _conclude_playback(playqueue, pos=0)


def _playback_init(plex_id, plex_type, playqueue, pos):
    """
    Playback setup if Kodi starts playing an item for the first time.
    """
    LOG.info('Initializing PKC playback')
    xml = PF.GetPlexMetadata(plex_id)
    try:
        xml[0].attrib
    except (IndexError, TypeError, AttributeError):
        LOG.error('Could not get a PMS xml for plex id %s', plex_id)
        # "Play error"
        utils.dialog('notification',
                     utils.lang(29999),
                     utils.lang(30128),
                     icon='{error}')
        _ensure_resolve(abort=True)
        return
    if playqueue.kodi_pl.size() > 1:
        # Special case - we already got a filled Kodi playqueue
        try:
            _init_existing_kodi_playlist(playqueue, pos)
        except PL.PlaylistError:
            LOG.error('Playback_init for existing Kodi playlist failed')
            _ensure_resolve(abort=True)
            return
        # Now we need to use setResolvedUrl for the item at position ZERO
        # playqueue.py will pick up the missing items
        _conclude_playback(playqueue, 0)
        return
    # "Usual" case - consider trailers and parts and build both Kodi and Plex
    # playqueues
    # Pass dummy PKC video with 0 length so Kodi immediately stops playback
    # and we can build our own playqueue.
    _ensure_resolve()
    api = API(xml[0])
    trailers = False
    if (plex_type == v.PLEX_TYPE_MOVIE and not api.resume_point() and
            utils.settings('enableCinema') == "true"):
        if utils.settings('askCinema') == "true":
            # "Play trailers?"
            trailers = utils.dialog('yesno',
                                    utils.lang(29999),
                                    utils.lang(33016))
            trailers = True if trailers else False
        else:
            trailers = True
    LOG.debug('Playing trailers: %s', trailers)
    if RESOLVE:
        # Sleep a bit to let setResolvedUrl do its thing - bit ugly
        sleep_timer = 0
        while not state.PKC_CAUSED_STOP_DONE:
            sleep(50)
            sleep_timer += 1
            if sleep_timer > 100:
                break
    playqueue.clear()
    if plex_type != v.PLEX_TYPE_CLIP:
        # Post to the PMS to create a playqueue - in any case due to Companion
        xml = PF.init_plex_playqueue(plex_id,
                                     xml.attrib.get('librarySectionUUID'),
                                     mediatype=plex_type,
                                     trailers=trailers)
        if xml is None:
            LOG.error('Could not get a playqueue xml for plex id %s, UUID %s',
                      plex_id, xml.attrib.get('librarySectionUUID'))
            # "Play error"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(30128),
                         icon='{error}')
            # Do NOT use _ensure_resolve() because we resolved above already
            state.CONTEXT_MENU_PLAY = False
            state.FORCE_TRANSCODE = False
            state.RESUME_PLAYBACK = False
            return
        PL.get_playlist_details_from_xml(playqueue, xml)
    stack = _prep_playlist_stack(xml)
    _process_stack(playqueue, stack)
    # Always resume if playback initiated via PMS and there IS a resume
    # point
    offset = api.resume_point() * 1000 if state.CONTEXT_MENU_PLAY else None
    # Reset some playback variables
    state.CONTEXT_MENU_PLAY = False
    state.FORCE_TRANSCODE = False
    # New thread to release this one sooner (e.g. harddisk spinning up)
    thread = Thread(target=threaded_playback,
                    args=(playqueue.kodi_pl, pos, offset))
    thread.setDaemon(True)
    LOG.info('Done initializing playback, starting Kodi player at pos %s and '
             'resume point %s', pos, offset)
    # By design, PKC will start Kodi playback using Player().play(). Kodi
    # caches paths like our plugin://pkc. If we use Player().play() between
    # 2 consecutive startups of exactly the same Kodi library item, Kodi's
    # cache will have been flushed for some reason. Hence the 2nd call for
    # plugin://pkc will be lost; Kodi will try to startup playback for an empty
    # path: log entry is "CGUIWindowVideoBase::OnPlayMedia <missing path>"
    thread.start()
    # Ensure that PKC playqueue monitor ignores the changes we just made
    playqueue.pkc_edit = True


def _ensure_resolve(abort=False):
    """
    Will check whether RESOLVE=True and if so, fail Kodi playback startup
    with the path 'PKC_Dummy_Path_Which_Fails' using setResolvedUrl (and some
    pickling)

    This way we're making sure that other Python instances (calling default.py)
    will be destroyed.
    """
    if RESOLVE:
        LOG.debug('Passing dummy path to Kodi')
        # if not state.CONTEXT_MENU_PLAY:
        # Because playback won't start with context menu play
        state.PKC_CAUSED_STOP = True
        state.PKC_CAUSED_STOP_DONE = False
        if not abort:
            result = pickler.Playback_Successful()
            result.listitem = PKCListItem(path=v.NULL_VIDEO)
            pickler.pickle_me(result)
        else:
            # Shows PKC error message
            pickler.pickle_me(None)
    if abort:
        # Reset some playback variables
        state.CONTEXT_MENU_PLAY = False
        state.FORCE_TRANSCODE = False
        state.RESUME_PLAYBACK = False


def _init_existing_kodi_playlist(playqueue, pos):
    """
    Will take the playqueue's kodi_pl with MORE than 1 element and initiate
    playback (without adding trailers)
    """
    LOG.debug('Kodi playlist size: %s', playqueue.kodi_pl.size())
    kodi_items = js.playlist_get_items(playqueue.playlistid)
    if not kodi_items:
        LOG.error('No Kodi items returned')
        raise PL.PlaylistError('No Kodi items returned')
    item = PL.init_plex_playqueue(playqueue, kodi_item=kodi_items[pos])
    item.force_transcode = state.FORCE_TRANSCODE
    # playqueue.py will add the rest - this will likely put the PMS under
    # a LOT of strain if the following Kodi setting is enabled:
    # Settings -> Player -> Videos -> Play next video automatically
    LOG.debug('Done init_existing_kodi_playlist')


def _prep_playlist_stack(xml):
    stack = []
    for item in xml:
        api = API(item)
        if (state.CONTEXT_MENU_PLAY is False and
                api.plex_type() not in (v.PLEX_TYPE_CLIP, v.PLEX_TYPE_EPISODE)):
            # If user chose to play via PMS or force transcode, do not
            # use the item path stored in the Kodi DB
            with plexdb.Get_Plex_DB() as plex_db:
                plex_dbitem = plex_db.getItem_byId(api.plex_id())
            kodi_id = plex_dbitem[0] if plex_dbitem else None
            kodi_type = plex_dbitem[4] if plex_dbitem else None
        else:
            # We will never store clips (trailers) in the Kodi DB.
            # Also set kodi_id to None for playback via PMS, so that we're
            # using add-on paths.
            # Also do NOT associate episodes with library items for addon paths
            # as artwork lookup is broken (episode path does not link back to
            # season and show)
            kodi_id = None
            kodi_type = None
        for part, _ in enumerate(item[0]):
            api.set_part_number(part)
            if kodi_id is None:
                # Need to redirect again to PKC to conclude playback
                path = api.path()
                listitem = api.create_listitem()
                listitem.setPath(utils.try_encode(path))
            else:
                # Will add directly via the Kodi DB
                path = None
                listitem = None
            stack.append({
                'kodi_id': kodi_id,
                'kodi_type': kodi_type,
                'file': path,
                'xml_video_element': item,
                'listitem': listitem,
                'part': part,
                'playcount': api.viewcount(),
                'offset': api.resume_point(),
                'id': api.item_id()
            })
    return stack


def _process_stack(playqueue, stack):
    """
    Takes our stack and adds the items to the PKC and Kodi playqueues.
    """
    # getposition() can return -1
    pos = max(playqueue.kodi_pl.getposition(), 0) + 1
    for item in stack:
        if item['kodi_id'] is None:
            playlist_item = PL.add_listitem_to_Kodi_playlist(
                playqueue,
                pos,
                item['listitem'],
                file=item['file'],
                xml_video_element=item['xml_video_element'])
        else:
            # Directly add element so we have full metadata
            playlist_item = PL.add_item_to_kodi_playlist(
                playqueue,
                pos,
                kodi_id=item['kodi_id'],
                kodi_type=item['kodi_type'],
                xml_video_element=item['xml_video_element'])
        playlist_item.playcount = item['playcount']
        playlist_item.offset = item['offset']
        playlist_item.part = item['part']
        playlist_item.id = item['id']
        playlist_item.force_transcode = state.FORCE_TRANSCODE
        pos += 1


def _conclude_playback(playqueue, pos):
    """
    ONLY if actually being played (e.g. at 5th position of a playqueue).

        Decide on direct play, direct stream, transcoding
        path to
            direct paths: file itself
            PMS URL
            Web URL
        audiostream (e.g. let user choose)
        subtitle stream (e.g. let user choose)
        Init Kodi Playback (depending on situation):
            start playback
            return PKC listitem attached to result
    """
    LOG.info('Concluding playback for playqueue position %s', pos)
    result = pickler.Playback_Successful()
    listitem = PKCListItem()
    item = playqueue.items[pos]
    if item.xml is not None:
        # Got a Plex element
        api = API(item.xml)
        api.set_part_number(item.part)
        api.create_listitem(listitem)
        playutils = PlayUtils(api, item)
        playurl = playutils.getPlayUrl()
    else:
        playurl = item.file
    listitem.setPath(utils.try_encode(playurl))
    if item.playmethod == 'DirectStream':
        listitem.setSubtitles(api.cache_external_subs())
    elif item.playmethod == 'Transcode':
        playutils.audio_subtitle_prefs(listitem)

    if state.RESUME_PLAYBACK is True:
        state.RESUME_PLAYBACK = False
        if (item.offset is None and
                item.plex_type not in (v.PLEX_TYPE_SONG, v.PLEX_TYPE_CLIP)):
            with plexdb.Get_Plex_DB() as plex_db:
                plex_dbitem = plex_db.getItem_byId(item.plex_id)
                file_id = plex_dbitem[1] if plex_dbitem else None
            with kodidb.GetKodiDB('video') as kodi_db:
                item.offset = kodi_db.get_resume(file_id)
        LOG.info('Resuming playback at %s', item.offset)
        listitem.setProperty('StartOffset', str(item.offset))
        listitem.setProperty('resumetime', str(item.offset))
    # Reset the resumable flag
    result.listitem = listitem
    pickler.pickle_me(result)
    LOG.info('Done concluding playback')


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
    result = pickler.Playback_Successful()
    if key.startswith('http') or key.startswith('{server}'):
        xml = DU().downloadUrl(key)
    elif key.startswith('/system/services'):
        xml = DU().downloadUrl('http://node.plexapp.com:32400%s' % key)
    else:
        xml = DU().downloadUrl('{server}%s' % key)
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not download PMS metadata')
        _ensure_resolve(abort=True)
        return
    if offset != '0':
        offset = int(v.PLEX_TO_KODI_TIMEFACTOR * float(offset))
        # Todo: implement offset
    api = API(xml[0])
    listitem = PKCListItem()
    api.create_listitem(listitem)
    playqueue = PQ.get_playqueue_from_type(
        v.KODI_PLAYLIST_TYPE_FROM_PLEX_TYPE[api.plex_type()])
    playqueue.clear()
    item = PL.Playlist_Item()
    item.xml = xml[0]
    item.offset = int(offset)
    item.plex_type = v.PLEX_TYPE_CLIP
    item.playmethod = 'DirectStream'
    # Need to get yet another xml to get the final playback url
    xml = DU().downloadUrl('http://node.plexapp.com:32400%s'
                           % xml[0][0][0].attrib['key'])
    try:
        xml[0].attrib
    except (TypeError, IndexError, AttributeError):
        LOG.error('Could not download last xml for playurl')
        _ensure_resolve(abort=True)
        return
    playurl = xml[0].attrib['key']
    item.file = playurl
    listitem.setPath(utils.try_encode(playurl))
    playqueue.items.append(item)
    if resolve is True:
        result.listitem = listitem
        pickler.pickle_me(result)
    else:
        thread = Thread(target=Player().play,
                        args={'item': utils.try_encode(playurl),
                              'listitem': listitem})
        thread.setDaemon(True)
        LOG.info('Done initializing PKC playback, starting Kodi player')
        thread.start()


def play_xml(playqueue, xml, offset=None, start_plex_id=None):
    """
    Play all items contained in the xml passed in. Called by Plex Companion.

    Either supply the ratingKey of the starting Plex element. Or set
    playqueue.selectedItemID
    """
    LOG.info("play_xml called with offset %s, start_plex_id %s",
             offset, start_plex_id)
    stack = _prep_playlist_stack(xml)
    _process_stack(playqueue, stack)
    LOG.debug('Playqueue after play_xml update: %s', playqueue)
    if start_plex_id is not None:
        for startpos, item in enumerate(playqueue.items):
            if item.plex_id == start_plex_id:
                break
        else:
            startpos = 0
    else:
        for startpos, item in enumerate(playqueue.items):
            if item.id == playqueue.selectedItemID:
                break
        else:
            startpos = 0
    thread = Thread(target=threaded_playback,
                    args=(playqueue.kodi_pl, startpos, offset))
    LOG.info('Done play_xml, starting Kodi player at position %s', startpos)
    thread.start()


def threaded_playback(kodi_playlist, startpos, offset):
    """
    Seek immediately after kicking off playback is not reliable.
    """
    player = Player()
    player.play(kodi_playlist, None, False, startpos)
    if offset and offset != '0':
        i = 0
        while not player.isPlaying():
            sleep(100)
            i += 1
            if i > 100:
                LOG.error('Could not seek to %s', offset)
                return
        js.seek_to(int(offset))
