#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger

from .common import update_kodi_library, PLAYLIST_SYNC_ENABLED
from .additional_metadata import ProcessMetadataTask
from ..plex_api import API
from ..plex_db import PlexDB
from .. import kodi_db
from .. import backgroundthread, plex_functions as PF, itemtypes
from .. import artwork, utils, timing, variables as v, app

if PLAYLIST_SYNC_ENABLED:
    from .. import playlists

LOG = getLogger('PLEX.sync.websocket')

CACHING_ENALBED = utils.settings('enableTextureCache') == "true"

WEBSOCKET_MESSAGES = []
# Dict to save info for Plex items currently being played somewhere
PLAYSTATE_SESSIONS = {}


def multi_delete(input_list, delete_list):
    """
    Deletes the list items of input_list at the positions in delete_list
    (which can be in any arbitrary order)
    """
    for index in sorted(delete_list, reverse=True):
        del input_list[index]
    return input_list


def store_websocket_message(message):
    """
    processes json.loads() messages from websocket. Triage what we need to
    do with "process_" methods
    """
    if message['type'] == 'playing':
        process_playing(message['PlaySessionStateNotification'])
    elif message['type'] == 'timeline':
        store_timeline_message(message['TimelineEntry'])
    elif message['type'] == 'activity':
        store_activity_message(message['ActivityNotification'])


def process_websocket_messages():
    """
    Periodically called to process new/updated PMS items

    PMS needs a while to download info from internet AFTER it
    showed up under 'timeline' websocket messages

    data['type']:
        1:      movie
        2:      tv show??
        3:      season??
        4:      episode
        8:      artist (band)
        9:      album
        10:     track (song)
        12:     trailer, extras?

    data['state']:
        0: 'created',
        2: 'matching',
        3: 'downloading',
        4: 'loading',
        5: 'finished',
        6: 'analyzing',
        9: 'deleted'
    """
    global WEBSOCKET_MESSAGES
    now = timing.unix_timestamp()
    update_kodi_video_library, update_kodi_music_library = False, False
    delete_list = []
    for i, message in enumerate(WEBSOCKET_MESSAGES):
        if message['state'] == 9:
            successful, video, music = process_delete_message(message)
        elif now - message['timestamp'] < app.SYNC.backgroundsync_saftymargin:
            # We haven't waited long enough for the PMS to finish processing the
            # item. Do it later (excepting deletions)
            continue
        else:
            successful, video, music = process_new_item_message(message)
            if successful:
                task = ProcessMetadataTask()
                task.setup(message['plex_id'],
                           message['plex_type'],
                           refresh=False)
                backgroundthread.BGThreader.addTask(task)
        if successful is True:
            delete_list.append(i)
            update_kodi_video_library = True if video else update_kodi_video_library
            update_kodi_music_library = True if music else update_kodi_music_library
        else:
            # Safety net if we can't process an item
            message['attempt'] += 1
            if message['attempt'] > 3:
                LOG.error('Repeatedly could not process message %s, abort',
                          message)
                delete_list.append(i)

    # Get rid of the items we just processed
    if delete_list:
        WEBSOCKET_MESSAGES = multi_delete(WEBSOCKET_MESSAGES, delete_list)
    # Let Kodi know of the change
    if update_kodi_video_library or update_kodi_music_library:
        update_kodi_library(video=update_kodi_video_library,
                            music=update_kodi_music_library)


def process_new_item_message(message):
    LOG.debug('Message: %s', message)
    xml = PF.GetPlexMetadata(message['plex_id'])
    try:
        plex_type = xml[0].attrib['type']
    except (IndexError, KeyError, TypeError):
        LOG.error('Could not download metadata for %s', message['plex_id'])
        return False, False, False
    LOG.debug("Processing new/updated PMS item: %s", message['plex_id'])
    with itemtypes.ITEMTYPE_FROM_PLEXTYPE[plex_type](timing.unix_timestamp()) as typus:
        typus.add_update(xml[0],
                         section_name=xml.get('librarySectionTitle'),
                         section_id=utils.cast(int, xml.get('librarySectionID')))
    cache_artwork(message['plex_id'], plex_type)
    return True, plex_type in v.PLEX_VIDEOTYPES, plex_type in v.PLEX_AUDIOTYPES


def process_delete_message(message):
    plex_type = message['plex_type']
    with itemtypes.ITEMTYPE_FROM_PLEXTYPE[plex_type](None) as typus:
        typus.remove(message['plex_id'], plex_type=plex_type)
    return True, plex_type in v.PLEX_VIDEOTYPES, plex_type in v.PLEX_AUDIOTYPES


def store_timeline_message(data):
    """
    PMS is messing with the library items, e.g. new or changed. Put in our
    "processing queue" for later
    """
    global WEBSOCKET_MESSAGES
    for message in data:
        if 'tv.plex' in message.get('identifier', ''):
            # Ommit Plex DVR messages - the Plex IDs are not corresponding
            # (DVR ratingKeys are not unique and might correspond to a
            # movie or episode)
            continue
        try:
            typus = v.PLEX_TYPE_FROM_WEBSOCKET[int(message['type'])]
        except KeyError:
            # E.g. -1 - thanks Plex!
            LOG.info('Ignoring invalid message %s', data)
            continue
        if typus in (v.PLEX_TYPE_CLIP, v.PLEX_TYPE_SET):
            # No need to process extras or trailers
            continue
        if message.get('sectionID') is not None and \
            not is_section_synced(message.get('sectionID')):
            # The item is in a section that is not being synced to kodi
            continue
        status = int(message['state'])
        if typus == 'playlist' and PLAYLIST_SYNC_ENABLED:
            playlists.websocket(plex_id=str(message['itemID']),
                                status=status)
        elif status == 9:
            # Immediately and always process deletions (as the PMS will
            # send additional message with other codes)
            WEBSOCKET_MESSAGES.append({
                'state': status,
                'plex_type': typus,
                'plex_id': utils.cast(int, message['itemID']),
                'timestamp': timing.unix_timestamp(),
                'attempt': 0
            })
        elif typus in (v.PLEX_TYPE_MOVIE,
                       v.PLEX_TYPE_EPISODE,
                       v.PLEX_TYPE_SONG) and status == 5:
            plex_id = int(message['itemID'])
            # Have we already added this element for processing?
            for existing_message in WEBSOCKET_MESSAGES:
                if existing_message['plex_id'] == plex_id:
                    break
            else:
                # Haven't added this element to the queue yet
                WEBSOCKET_MESSAGES.append({
                    'state': status,
                    'plex_type': typus,
                    'plex_id': plex_id,
                    'timestamp': timing.unix_timestamp(),
                    'attempt': 0
                })


def store_activity_message(data):
    """
    PMS is re-scanning an item, e.g. after having changed a movie poster.
    WATCH OUT for this if it's triggered by our PKC library scan!
    """
    global WEBSOCKET_MESSAGES
    for message in data:
        if message['event'] != 'ended':
            # Scan still going on, so skip for now
            continue
        elif message['Activity'].get('Context') is None:
            # Not related to any Plex element, but entire library
            continue
        elif message['Activity']['type'] != 'library.refresh.items':
            # Not the type of message relevant for us
            continue
        elif message['Activity']['Context'].get('refreshed') is not None and \
                message['Activity']['Context']['refreshed'] == False:
            # The item was scanned but not actually refreshed
            continue
        elif message['Activity']['Context'].get('librarySectionID') is not None and \
                not is_section_synced(message['Activity']['Context'].get('librarySectionID')):
            # The item is in a section that is not being synced to kodi
            continue
        plex_id = PF.GetPlexKeyNumber(message['Activity']['Context']['key'])[1]
        if not plex_id:
            # Likely a Plex id like /library/metadata/3/children
            continue
        # We're only looking at existing elements - have we synced yet?
        with PlexDB(lock=False) as plexdb:
            typus = plexdb.item_by_id(plex_id, plex_type=None)
        if not typus:
            LOG.debug('plex_id %s not synced yet - skipping', plex_id)
            continue
        # Have we already added this element?
        for existing_message in WEBSOCKET_MESSAGES:
            if existing_message['plex_id'] == plex_id:
                break
        else:
            # Haven't added this element to the queue yet
            WEBSOCKET_MESSAGES.append({
                'state': None,  # Don't need a state here
                'plex_type': typus['plex_type'],
                'plex_id': plex_id,
                'timestamp': timing.unix_timestamp(),
                'attempt': 0
            })


def process_playing(data):
    """
    Someone (not necessarily the user signed in) is playing something some-
    where
    """
    global PLAYSTATE_SESSIONS
    for message in data:
        status = message['state']
        if status == 'buffering' or status == 'stopped':
            # Drop buffering and stop messages immediately - no value
            continue
        plex_id = utils.cast(int, message['ratingKey'])
        skip = False
        for pid in (0, 1, 2):
            if plex_id == app.PLAYSTATE.player_states[pid]['plex_id']:
                # Kodi is playing this message - no need to set the playstate
                skip = True
        if skip:
            continue
        if 'sessionKey' not in message:
            LOG.warn('Received malformed message from the PMS: %s', message)
            continue
        session_key = message['sessionKey']
        # Do we already have a sessionKey stored?
        if session_key not in PLAYSTATE_SESSIONS:
            with PlexDB(lock=False) as plexdb:
                typus = plexdb.item_by_id(plex_id, plex_type=None)
            if not typus or 'kodi_fileid' not in typus:
                # Item not (yet) in Kodi library or not affiliated with a file
                continue
            if utils.settings('plex_serverowned') == 'false':
                # Not our PMS, we are not authorized to get the sessions
                # On the bright side, it must be us playing :-)
                PLAYSTATE_SESSIONS[session_key] = {}
            else:
                # PMS is ours - get all current sessions
                pms_sessions = PF.GetPMSStatus(app.ACCOUNT.plex_token)
                if session_key not in pms_sessions:
                    LOG.info('Session key %s still unknown! Skip '
                             'playstate update', session_key)
                    continue
                PLAYSTATE_SESSIONS[session_key] = pms_sessions[session_key]
                LOG.debug('Updated current sessions. They are: %s',
                          PLAYSTATE_SESSIONS)
            # Attach Kodi info to the session
            PLAYSTATE_SESSIONS[session_key]['kodi_fileid'] = typus['kodi_fileid']
            if typus['plex_type'] == v.PLEX_TYPE_EPISODE:
                PLAYSTATE_SESSIONS[session_key]['kodi_fileid_2'] = typus['kodi_fileid_2']
            else:
                PLAYSTATE_SESSIONS[session_key]['kodi_fileid_2'] = None
            PLAYSTATE_SESSIONS[session_key]['kodi_id'] = typus['kodi_id']
            PLAYSTATE_SESSIONS[session_key]['kodi_type'] = typus['kodi_type']
        session = PLAYSTATE_SESSIONS[session_key]
        if utils.settings('plex_serverowned') != 'false':
            # Identify the user - same one as signed on with PKC? Skip
            # update if neither session's username nor userid match
            # (Owner sometime's returns id '1', not always)
            if not app.ACCOUNT.plex_token and session['userId'] == '1':
                # PKC not signed in to plex.tv. Plus owner of PMS is
                # playing (the '1').
                # Hence must be us (since several users require plex.tv
                # token for PKC)
                pass
            elif not (session['userId'] == app.ACCOUNT.plex_user_id or
                      session['username'] == app.ACCOUNT.plex_username):
                LOG.debug('Our username %s, userid %s did not match '
                          'the session username %s with userid %s',
                          app.ACCOUNT.plex_username,
                          app.ACCOUNT.plex_user_id,
                          session['username'],
                          session['userId'])
                continue
        # Get an up-to-date XML from the PMS because PMS will NOT directly
        # tell us: duration of item viewCount
        if not session.get('duration'):
            xml = PF.GetPlexMetadata(plex_id)
            if xml in (None, 401):
                LOG.error('Could not get up-to-date xml for item %s',
                          plex_id)
                continue
            api = API(xml[0])
            session['duration'] = api.runtime()
            session['viewCount'] = api.viewcount()
        # Sometimes, Plex tells us resume points in milliseconds and
        # not in seconds - thank you very much!
        if message['viewOffset'] > session['duration']:
            resume = message['viewOffset'] / 1000
        else:
            resume = message['viewOffset']
        if resume < v.IGNORE_SECONDS_AT_START:
            continue
        try:
            completed = float(resume) / float(session['duration'])
        except (ZeroDivisionError, TypeError):
            LOG.error('Could not mark playstate for %s and session %s',
                      data, session)
            continue
        if completed >= v.MARK_PLAYED_AT:
            # Only mark completely watched ONCE
            if session.get('marked_played') is None:
                session['marked_played'] = True
                mark_played = True
            else:
                # Don't mark it as completely watched again
                continue
        else:
            mark_played = False
        LOG.debug('Update playstate for user %s for %s with plex id %s to '
                  'viewCount %s, resume %s, mark_played %s for item %s',
                  app.ACCOUNT.plex_username, session['kodi_type'], plex_id,
                  session['viewCount'], resume, mark_played, PLAYSTATE_SESSIONS[session_key])
        func = itemtypes.ITEMTYPE_FROM_KODITYPE[session['kodi_type']]
        with func(None) as fkt:
            fkt.update_playstate(mark_played,
                                 session['viewCount'],
                                 resume,
                                 session['duration'],
                                 session['kodi_fileid'],
                                 session['kodi_fileid_2'],
                                 timing.unix_timestamp())


def cache_artwork(plex_id, plex_type, kodi_id=None, kodi_type=None):
    """
    Triggers caching of artwork (if so enabled in the PKC settings)
    """
    if not CACHING_ENALBED:
        return
    if not kodi_id:
        with PlexDB(lock=False) as plexdb:
            item = plexdb.item_by_id(plex_id, plex_type)
        if not item:
            LOG.error('Could not retrieve Plex db info for %s', plex_id)
            return
        kodi_id, kodi_type = item['kodi_id'], item['kodi_type']
    with kodi_db.KODIDB_FROM_PLEXTYPE[plex_type](lock=False) as kodidb:
        for url in kodidb.art_urls(kodi_id, kodi_type):
            artwork.cache_url(url)

def is_section_synced(section_id):
    """
    Returns true if the specified section is synced to kodi
    """
    return next((section for section in app.SYNC.sections if section.sync_to_kodi and section.section_id == int(section_id)), None) is not None
