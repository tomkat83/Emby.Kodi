#!/usr/bin/env python
# -*- coding: utf-8 -*-
from logging import getLogger
from requests import exceptions

from .downloadutils import DownloadUtils as DU
from .plex_api import API
from . import plex_functions as PF, utils, variables as v


LOG = getLogger('PLEX.playback_decision')

# largest signed 32bit integer: 2147483
MAX_SIGNED_INT = int(2**31 - 1)
# PMS answer codes
DIRECT_PLAY_OK = 1000
CONVERSION_OK = 1001  # PMS can either direct stream or transcode


def set_pkc_playmethod(api, item):
    item.playmethod = int(utils.settings('playType'))
    LOG.info('User chose playback method %s in PKC settings',
             v.EXPLICIT_PLAYBACK_METHOD[item.playmethod])
    _initial_best_playback_method(api, item)
    LOG.info('PKC decided on playback method %s',
             v.EXPLICIT_PLAYBACK_METHOD[item.playmethod])


def set_playurl(api, item):
    try:
        if item.playmethod == v.PLAYBACK_METHOD_DIRECT_PATH:
            # No need to ask the PMS whether we can play - we circumvent
            # the PMS entirely
            return
        LOG.info('Lets ask the PMS next')
        try:
            _pms_playback_decision(api, item)
        except (exceptions.RequestException,
                AttributeError,
                IndexError,
                SystemExit):
            LOG.warn('Could not find suitable settings for playback, aborting')
            utils.ERROR(notify=True)
            item.playmethod = None
            item.file = None
        else:
            item.file = api.transcode_video_path(item.playmethod,
                                                 quality=item.quality)
    finally:
        LOG.info('The playurl for %s is: %s',
                 v.EXPLICIT_PLAYBACK_METHOD[item.playmethod], item.file)


def _initial_best_playback_method(api, item):
    """
    Sets the highest available playback method without talking to the PMS
    Also sets self.path for a direct path, if available and accessible
    """
    item.file = api.file_path()
    item.file = api.validate_playurl(item.file, api.plex_type, force_check=True)
    # Check whether we have a strm file that we need to throw at Kodi 1:1
    if item.file is not None and item.file.endswith('.strm'):
        # Use direct path in any case, regardless of user setting
        LOG.debug('.strm file detected')
        item.playmethod = v.PLAYBACK_METHOD_DIRECT_PATH
    elif _must_transcode(api, item):
        item.playmethod = v.PLAYBACK_METHOD_TRANSCODE
    elif item.playmethod in (v.PLAYBACK_METHOD_DIRECT_PLAY,
                             v.PLAYBACK_METHOD_DIRECT_STREAM):
        pass
    elif item.file is None:
        # E.g. direct path was not possible to access
        item.playmethod = v.PLAYBACK_METHOD_DIRECT_PLAY
    else:
        item.playmethod = v.PLAYBACK_METHOD_DIRECT_PATH


def _pms_playback_decision(api, item):
    """
    We CANNOT distinguish direct playing from direct streaming from the PMS'
    answer
    """
    ask_for_user_quality_settings = False
    if item.playmethod <= 2:
        LOG.info('Asking PMS with maximal quality settings')
        item.quality = _max_quality()
        decision_api = _ask_pms(api, item)
        if decision_api.decision_code() > CONVERSION_OK:
            ask_for_user_quality_settings = True
    else:
        ask_for_user_quality_settings = True
    if ask_for_user_quality_settings:
        item.quality = _transcode_quality()
        LOG.info('Asking PMS with user quality settings')
        decision_api = _ask_pms(api, item)

    # Process the PMS answer
    if decision_api.decision_code() > CONVERSION_OK:
        LOG.error('Neither DirectPlay, DirectStream nor transcoding possible')
        error = '%s\n%s' % (decision_api.general_play_decision_text(),
                            decision_api.transcode_decision_text())
        utils.messageDialog(heading=utils.lang(29999),
                            msg=error)
        raise AttributeError('Neither DirectPlay, DirectStream nor transcoding possible')
    if (item.playmethod == v.PLAYBACK_METHOD_DIRECT_PLAY and
            decision_api.decision_code() == DIRECT_PLAY_OK):
        # All good
        return
    LOG.info('PMS video stream decision: %s, PMS audio stream decision: %s, '
             'PMS subtitle stream decision: %s',
             decision_api.video_decision(),
             decision_api.audio_decision(),
             decision_api.subtitle_decision())
    # Only look at the video stream since that'll be most CPU-intensive for
    # the PMS
    video_direct_streaming = decision_api.video_decision() == 'copy'
    if video_direct_streaming:
        if item.playmethod < v.PLAYBACK_METHOD_DIRECT_STREAM:
            LOG.warn('The PMS forces us to direct stream')
            # "PMS enforced direct streaming"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(33005),
                         icon='{plex}')
        item.playmethod = v.PLAYBACK_METHOD_DIRECT_STREAM
    else:
        if item.playmethod < v.PLAYBACK_METHOD_TRANSCODE:
            LOG.warn('The PMS forces us to transcode')
            # "PMS enforced transcoding"
            utils.dialog('notification',
                         utils.lang(29999),
                         utils.lang(33004),
                         icon='{plex}')
        item.playmethod = v.PLAYBACK_METHOD_TRANSCODE


def _ask_pms(api, item):
    xml = PF.playback_decision(path=api.path_and_plex_id(),
                               media=api.mediastream,
                               part=api.part,
                               playmethod=item.playmethod,
                               video=api.plex_type in v.PLEX_VIDEOTYPES,
                               args=item.quality)
    decision_api = API(xml)
    LOG.info('PMS general decision %s: %s',
             decision_api.general_play_decision_code(),
             decision_api.general_play_decision_text())
    LOG.info('PMS Direct Play decision %s: %s',
             decision_api.direct_play_decision_code(),
             decision_api.direct_play_decision_text())
    LOG.info('PMS MDE decision %s: %s',
             decision_api.mde_play_decision_code(),
             decision_api.mde_play_decision_text())
    LOG.info('PMS transcoding decision %s: %s',
             decision_api.transcode_decision_code(),
             decision_api.transcode_decision_text())
    return decision_api


def _must_transcode(api, item):
    """
    Returns True if we need to transcode because
        - codec is in h265
        - 10bit video codec
        - HEVC codec
        - playqueue_item force_transcode is set to True
        - state variable FORCE_TRANSCODE set to True
            (excepting trailers etc.)
        - video bitrate above specified settings bitrate
    if the corresponding file settings are set to 'true'
    """
    if api.plex_type in (v.PLEX_TYPE_CLIP, v.PLEX_TYPE_SONG):
        LOG.info('Plex clip or music track, not transcoding')
        return False
    if item.playmethod == v.PLAYBACK_METHOD_TRANSCODE:
        return True
    videoCodec = api.video_codec()
    LOG.debug("videoCodec received from the PMS: %s", videoCodec)
    if item.force_transcode is True:
        LOG.info('User chose to force-transcode')
        return True
    codec = videoCodec['videocodec']
    if codec is None:
        # e.g. trailers. Avoids TypeError with "'h265' in codec"
        LOG.info('No codec from PMS, not transcoding.')
        return False
    if ((utils.settings('transcodeHi10P') == 'true' and
            videoCodec['bitDepth'] == '10') and
            ('h264' in codec)):
        LOG.info('Option to transcode 10bit h264 video content enabled.')
        return True
    try:
        bitrate = int(videoCodec['bitrate'])
    except (TypeError, ValueError):
        LOG.info('No video bitrate from PMS, not transcoding.')
        return False
    if bitrate > _get_max_bitrate():
        LOG.info('Video bitrate of %s is higher than the maximal video'
                 'bitrate of %s that the user chose. Transcoding',
                 bitrate, _get_max_bitrate())
        return True
    try:
        resolution = int(videoCodec['resolution'])
    except (TypeError, ValueError):
        if videoCodec['resolution'] == '4k':
            resolution = 2160
        else:
            LOG.info('No video resolution from PMS, not transcoding.')
            return False
    if 'h265' in codec or 'hevc' in codec:
        if resolution >= _getH265():
            LOG.info('Option to transcode h265/HEVC enabled. Resolution '
                     'of the media: %s, transcoding limit resolution: %s',
                     resolution, _getH265())
            return True
    return False


def _transcode_quality():
    return {
        'maxVideoBitrate': get_bitrate(),
        'videoResolution': get_resolution(),
        'videoQuality': 100,
        'mediaBufferSize': int(float(utils.settings('kodi_video_cache')) / 1024.0),
    }


def _max_quality():
    return {
        'maxVideoBitrate': MAX_SIGNED_INT,
        'videoResolution': '3840x2160',  # 4K
        'videoQuality': 100,
        'mediaBufferSize': int(float(utils.settings('kodi_video_cache')) / 1024.0),
    }


def get_bitrate():
    """
    Get the desired transcoding bitrate from the settings
    """
    videoQuality = utils.settings('transcoderVideoQualities')
    bitrate = {
        '0': 320,
        '1': 720,
        '2': 1500,
        '3': 2000,
        '4': 3000,
        '5': 4000,
        '6': 8000,
        '7': 10000,
        '8': 12000,
        '9': 20000,
        '10': 40000,
        '11': 35000,
        '12': 50000
    }
    # max bit rate supported by server (max signed 32bit integer)
    return bitrate.get(videoQuality, MAX_SIGNED_INT)


def get_resolution():
    """
    Get the desired transcoding resolutions from the settings
    """
    chosen = utils.settings('transcoderVideoQualities')
    res = {
        '0': '720x480',
        '1': '1024x768',
        '2': '1280x720',
        '3': '1280x720',
        '4': '1920x1080',
        '5': '1920x1080',
        '6': '1920x1080',
        '7': '1920x1080',
        '8': '1920x1080',
        '9': '3840x2160',
        '10': '3840x2160'
    }
    return res[chosen]


def _get_max_bitrate():
    max_bitrate = utils.settings('maxVideoQualities')
    bitrate = {
        '0': 320,
        '1': 720,
        '2': 1500,
        '3': 2000,
        '4': 3000,
        '5': 4000,
        '6': 8000,
        '7': 10000,
        '8': 12000,
        '9': 20000,
        '10': 40000,
        '11': MAX_SIGNED_INT  # deactivated
    }
    # max bit rate supported by server (max signed 32bit integer)
    return bitrate.get(max_bitrate, MAX_SIGNED_INT)


def _getH265():
    """
    Returns the user settings for transcoding h265: boundary resolutions
    of 480, 720 or 1080 as an int

    OR 2147483 (MAX_SIGNED_INT, int) if user chose not to transcode
    """
    H265 = {
        '0': MAX_SIGNED_INT,
        '1': 480,
        '2': 720,
        '3': 1080,
        '4': 2160
    }
    return H265[utils.settings('transcodeH265')]


def audio_subtitle_prefs(api, item):
    """
    Sets the stage for transcoding, letting the user potentially choose both
    audio and subtitle streams; subtitle streams to burn-into the video file.

    Uses a PUT request to the PMS, simulating e.g. the user using Plex Web,
    choosing a different stream in the video's metadata and THEN initiating
    playback.

    Returns None if user cancelled or we need to abort, True otherwise
    """
    # Set media and part where we're at
    if api.mediastream is None and api.mediastream_number() is None:
        return
    if item.playmethod != v.PLAYBACK_METHOD_TRANSCODE:
        return True
    return setup_transcoding_audio_subtitle_prefs(api.plex_media_streams(),
                                                  api.part_id())


def setup_transcoding_audio_subtitle_prefs(mediastreams, part_id):
    audio_streams_list = []
    audio_streams = []
    audio_default = None
    subtitle_default = None
    subtitle_streams_list = []
    # "Don't burn-in any subtitle"
    subtitle_streams = ['1 %s' % utils.lang(39706)]
    # selectAudioIndex = ""
    select_subs_index = ""
    audio_numb = 0
    # Remember 'no subtitles'
    sub_num = 1

    for stream in mediastreams:
        # Since Plex returns all possible tracks together, have to sort
        # them.
        index = stream.get('id')
        typus = stream.get('streamType')
        # Audio
        if typus == "2":
            codec = stream.get('codec')
            channellayout = stream.get('audioChannelLayout', "")
            try:
                track = "%s %s - %s %s" % (audio_numb + 1,
                                           stream.attrib['language'],
                                           codec,
                                           channellayout)
            except KeyError:
                track = "%s %s - %s %s" % (audio_numb + 1,
                                           utils.lang(39707),  # unknown
                                           codec,
                                           channellayout)
            if stream.get('default'):
                audio_default = audio_numb
            audio_streams_list.append(index)
            audio_streams.append(track)
            audio_numb += 1

        # Subtitles
        elif typus == "3":
            if stream.get('key'):
                # Subtitle can and will be downloaded - don't let user choose
                # this subtitle to burn-in
                continue
            # Subtitle is available within the video file
            # Burn in the subtitle, if user chooses to do so
            forced = stream.get('forced')
            try:
                track = '{} {}'.format(sub_num + 1,
                                       stream.attrib['displayTitle'])
            except KeyError:
                track = '{} {} ({})'.format(sub_num + 1,
                                            utils.lang(39707),  # unknown
                                            stream.get('codec'))
            if stream.get('default'):
                subtitle_default = sub_num
                track = "%s - %s" % (track, utils.lang(39708))  # Default
            if forced:
                track = "%s - %s" % (track, utils.lang(39709))  # Forced
            track = "%s (%s)" % (track, utils.lang(39710))  # burn-in
            subtitle_streams_list.append(index)
            subtitle_streams.append(track)
            sub_num += 1

    if audio_numb > 1:
        # "Transcoding: Auto-pick audio and subtitle stream using Plex defaults"
        if utils.settings('bestQuality') == 'true' and audio_default is not None:
            resp = audio_default
        else:
            resp = utils.dialog('select', utils.lang(33013), audio_streams)
            if resp == -1:
                LOG.info('User aborted dialog to select audio stream')
                return
        args = {
            'audioStreamID': audio_streams_list[resp],
            'allParts': 1
        }
        DU().downloadUrl('{server}/library/parts/%s' % part_id,
                         action_type='PUT',
                         parameters=args)

    # Zero telling the PMS to deactivate subs altogether
    select_subs_index = 0
    if sub_num == 1:
        # Note: we DO need to tell the PMS that we DONT want any sub
        # Otherwise, the PMS might pick-up the last one
        LOG.info('No subtitles to burn-in')
    else:
        # "Transcoding: Auto-pick audio and subtitle stream using Plex defaults"
        if utils.settings('bestQuality') == 'true' and subtitle_default is not None:
            resp = subtitle_default
        else:
            resp = utils.dialog('select', utils.lang(33014), subtitle_streams)
            if resp == -1:
                LOG.info('User aborted dialog to select subtitle stream')
                return
            elif resp == 0:
                # User did not select a subtitle or backed out of the dialog
                LOG.info('User chose to not burn-in any subtitles')
            else:
                LOG.info('User chose to burn-in subtitle %s: %s',
                         select_subs_index, subtitle_streams[resp])
                select_subs_index = subtitle_streams_list[resp - 1]
    # Now prep the PMS for our choice
    PF.change_subtitle(select_subs_index, part_id)
    return True
