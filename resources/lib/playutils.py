#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger

from .downloadutils import DownloadUtils as DU
from . import utils
from . import variables as v

###############################################################################
LOG = getLogger('PLEX.playutils')
###############################################################################


class PlayUtils():

    def __init__(self, api, playqueue_item):
        """
        init with api (PlexAPI wrapper of the PMS xml element) and
        playqueue_item (Playlist_Item())
        """
        self.api = api
        self.item = playqueue_item

    def getPlayUrl(self):
        """
        Returns the playurl [unicode] for the part or returns None.
        (movie might consist of several files)
        """
        if self.api.mediastream_number() is None:
            return
        playurl = self.isDirectPlay()
        if playurl is not None:
            LOG.info("File is direct playing.")
            self.item.playmethod = 'DirectPlay'
        elif self.isDirectStream():
            LOG.info("File is direct streaming.")
            playurl = self.api.transcode_video_path('DirectStream')
            self.item.playmethod = 'DirectStream'
        else:
            LOG.info("File is transcoding.")
            playurl = self.api.transcode_video_path(
                'Transcode',
                quality={
                    'maxVideoBitrate': self.get_bitrate(),
                    'videoResolution': self.get_resolution(),
                    'videoQuality': '100',
                    'mediaBufferSize': int(
                        utils.settings('kodi_video_cache')) / 1024,
                })
            self.item.playmethod = 'Transcode'
        LOG.info("The playurl is: %s", playurl)
        self.item.file = playurl
        return playurl

    def isDirectPlay(self):
        """
        Returns the path/playurl if we can direct play, None otherwise
        """
        # True for e.g. plex.tv watch later
        if self.api.should_stream() is True:
            LOG.info("Plex item optimized for direct streaming")
            return
        # Check whether we have a strm file that we need to throw at Kodi 1:1
        path = self.api.file_path()
        if path is not None and path.endswith('.strm'):
            LOG.info('.strm file detected')
            playurl = self.api.validate_playurl(path,
                                                self.api.plex_type(),
                                                force_check=True)
            return playurl
        # set to either 'Direct Stream=1' or 'Transcode=2'
        # and NOT to 'Direct Play=0'
        if utils.settings('playType') != "0":
            # User forcing to play via HTTP
            LOG.info("User chose to not direct play")
            return
        if self.mustTranscode():
            return
        return self.api.validate_playurl(path,
                                         self.api.plex_type(),
                                         force_check=True)

    def mustTranscode(self):
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
        if self.api.plex_type() in (v.PLEX_TYPE_CLIP, v.PLEX_TYPE_SONG):
            LOG.info('Plex clip or music track, not transcoding')
            return False
        videoCodec = self.api.video_codec()
        LOG.info("videoCodec: %s", videoCodec)
        if self.item.force_transcode is True:
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
        if bitrate > self.get_max_bitrate():
            LOG.info('Video bitrate of %s is higher than the maximal video'
                     'bitrate of %s that the user chose. Transcoding',
                     bitrate, self.get_max_bitrate())
            return True
        try:
            resolution = int(videoCodec['resolution'])
        except (TypeError, ValueError):
            LOG.info('No video resolution from PMS, not transcoding.')
            return False
        if 'h265' in codec or 'hevc' in codec:
            if resolution >= self.getH265():
                LOG.info('Option to transcode h265/HEVC enabled. Resolution '
                         'of the media: %s, transcoding limit resolution: %s',
                         resolution, self.getH265())
                return True
        return False

    def isDirectStream(self):
        # Never transcode Music
        if self.api.plex_type() == 'track':
            return True
        # set to 'Transcode=2'
        if utils.settings('playType') == "2":
            # User forcing to play via HTTP
            LOG.info("User chose to transcode")
            return False
        if self.mustTranscode():
            return False
        return True

    def get_max_bitrate(self):
        # get the addon video quality
        videoQuality = utils.settings('maxVideoQualities')
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
            '11': 99999999  # deactivated
        }
        # max bit rate supported by server (max signed 32bit integer)
        return bitrate.get(videoQuality, 2147483)

    def getH265(self):
        """
        Returns the user settings for transcoding h265: boundary resolutions
        of 480, 720 or 1080 as an int

        OR 9999999 (int) if user chose not to transcode
        """
        H265 = {
            '0': 99999999,
            '1': 480,
            '2': 720,
            '3': 1080
        }
        return H265[utils.settings('transcodeH265')]

    def get_bitrate(self):
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
        }
        # max bit rate supported by server (max signed 32bit integer)
        return bitrate.get(videoQuality, 2147483)

    def get_resolution(self):
        """
        Get the desired transcoding resolutions from the settings
        """
        chosen = utils.settings('transcoderVideoQualities')
        res = {
            '0': '420x420',
            '1': '576x320',
            '2': '720x480',
            '3': '1024x768',
            '4': '1280x720',
            '5': '1280x720',
            '6': '1920x1080',
            '7': '1920x1080',
            '8': '1920x1080',
            '9': '1920x1080',
            '10': '1920x1080',
        }
        return res[chosen]

    def audio_subtitle_prefs(self, listitem):
        """
        For transcoding only

        Called at the very beginning of play; used to change audio and subtitle
        stream by a PUT request to the PMS
        """
        # Set media and part where we're at
        if (self.api.mediastream is None and
                self.api.mediastream_number() is None):
            return
        try:
            mediastreams = self.api.plex_media_streams()
        except (TypeError, IndexError):
            LOG.error('Could not get media %s, part %s',
                      self.api.mediastream, self.api.part)
            return
        part_id = mediastreams.attrib['id']
        audio_streams_list = []
        audio_streams = []
        subtitle_streams_list = []
        # No subtitles as an option
        subtitle_streams = [utils.lang(39706)]
        downloadable_streams = []
        download_subs = []
        # selectAudioIndex = ""
        select_subs_index = ""
        audio_numb = 0
        # Remember 'no subtitles'
        sub_num = 1
        default_sub = None

        for stream in mediastreams:
            # Since Plex returns all possible tracks together, have to sort
            # them.
            index = stream.attrib.get('id')
            typus = stream.attrib.get('streamType')
            # Audio
            if typus == "2":
                codec = stream.attrib.get('codec')
                channellayout = stream.attrib.get('audioChannelLayout', "")
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
                audio_streams_list.append(index)
                audio_streams.append(utils.try_encode(track))
                audio_numb += 1

            # Subtitles
            elif typus == "3":
                try:
                    track = "%s %s" % (sub_num + 1, stream.attrib['language'])
                except KeyError:
                    track = "%s %s (%s)" % (sub_num + 1,
                                            utils.lang(39707),  # unknown
                                            stream.attrib.get('codec'))
                default = stream.attrib.get('default')
                forced = stream.attrib.get('forced')
                downloadable = stream.attrib.get('key')

                if default:
                    track = "%s - %s" % (track, utils.lang(39708))  # Default
                if forced:
                    track = "%s - %s" % (track, utils.lang(39709))  # Forced
                if downloadable:
                    # We do know the language - temporarily download
                    if 'language' in stream.attrib:
                        path = self.api.download_external_subtitles(
                            '{server}%s' % stream.attrib['key'],
                            "subtitle.%s.%s" % (stream.attrib['languageCode'],
                                                stream.attrib['codec']))
                    # We don't know the language - no need to download
                    else:
                        path = self.api.attach_plex_token_to_url(
                            "%s%s" % (utils.window('pms_server'),
                                      stream.attrib['key']))
                    downloadable_streams.append(index)
                    download_subs.append(utils.try_encode(path))
                else:
                    track = "%s (%s)" % (track, utils.lang(39710))  # burn-in
                if stream.attrib.get('selected') == '1' and downloadable:
                    # Only show subs without asking user if they can be
                    # turned off
                    default_sub = index

                subtitle_streams_list.append(index)
                subtitle_streams.append(utils.try_encode(track))
                sub_num += 1

        if audio_numb > 1:
            resp = utils.dialog('select', utils.lang(33013), audio_streams)
            if resp > -1:
                # User selected some audio track
                args = {
                    'audioStreamID': audio_streams_list[resp],
                    'allParts': 1
                }
                DU().downloadUrl('{server}/library/parts/%s' % part_id,
                                 action_type='PUT',
                                 parameters=args)

        if sub_num == 1:
            # No subtitles
            return

        select_subs_index = None
        if (utils.settings('pickPlexSubtitles') == 'true' and
                default_sub is not None):
            LOG.info('Using default Plex subtitle: %s', default_sub)
            select_subs_index = default_sub
        else:
            resp = utils.dialog('select', utils.lang(33014), subtitle_streams)
            if resp > 0:
                select_subs_index = subtitle_streams_list[resp - 1]
            else:
                # User selected no subtitles or backed out of dialog
                select_subs_index = ''

        LOG.debug('Adding external subtitles: %s', download_subs)
        # Enable Kodi to switch autonomously to downloadable subtitles
        if download_subs:
            listitem.setSubtitles(download_subs)
        # Don't additionally burn in subtitles
        if select_subs_index in downloadable_streams:
            select_subs_index = ''
        # Now prep the PMS for our choice
        args = {
            'subtitleStreamID': select_subs_index,
            'allParts': 1
        }
        DU().downloadUrl('{server}/library/parts/%s' % part_id,
                         action_type='PUT',
                         parameters=args)
