# -*- coding: utf-8 -*-

###############################################################################

import logging
from urllib import urlencode

import xbmcgui
import xbmcvfs

from utils import window, settings, tryEncode, language as lang

import PlexAPI

###############################################################################

log = logging.getLogger("PLEX."+__name__)

###############################################################################


class PlayUtils():

    def __init__(self, item):

        self.item = item
        self.API = PlexAPI.API(item)

        self.userid = window('currUserId')
        self.server = window('pms_server')
        self.machineIdentifier = window('plex_machineIdentifier')

    def getPlayUrl(self, partNumber=None):
        """
        Returns the playurl for the part with number partNumber
        (movie might consist of several files)

        playurl is utf-8 encoded!
        """
        self.API.setPartNumber(partNumber)
        self.API.getMediastreamNumber()
        playurl = self.isDirectPlay()

        if playurl is not None:
            log.info("File is direct playing.")
            playurl = tryEncode(playurl)
            # Set playmethod property
            window('emby_%s.playmethod' % playurl, "DirectPlay")

        elif self.isDirectStream():
            log.info("File is direct streaming.")
            playurl = tryEncode(
                self.API.getTranscodeVideoPath('DirectStream'))
            # Set playmethod property
            window('emby_%s.playmethod' % playurl, "DirectStream")

        else:
            log.info("File is transcoding.")
            playurl = tryEncode(self.API.getTranscodeVideoPath(
                'Transcode',
                quality={
                    'maxVideoBitrate': self.get_bitrate(),
                    'videoResolution': self.get_resolution(),
                    'videoQuality': '100'
                }))
            # Set playmethod property
            window('emby_%s.playmethod' % playurl, value="Transcode")

        log.info("The playurl is: %s" % playurl)
        return playurl

    def httpPlay(self):
        # Audio, Video, Photo

        itemid = self.item['Id']
        mediatype = self.item['MediaType']

        if mediatype == "Audio":
            playurl = "%s/emby/Audio/%s/stream" % (self.server, itemid)
        else:
            playurl = "%s/emby/Videos/%s/stream?static=true" % (self.server, itemid)

        return playurl

    def isDirectPlay(self):
        """
        Returns the path/playurl if we can direct play, None otherwise
        """
        # True for e.g. plex.tv watch later
        if self.API.shouldStream() is True:
            log.info("Plex item optimized for direct streaming")
            return
        # set to either 'Direct Stream=1' or 'Transcode=2'
        # and NOT to 'Direct Play=0'
        if settings('playType') != "0":
            # User forcing to play via HTTP
            log.info("User chose to not direct play")
            return
        if self.mustTranscode():
            return
        return self.API.validatePlayurl(self.API.getFilePath(),
                                        self.API.getType(),
                                        forceCheck=True)

    def directPlay(self):

        try:
            playurl = self.item['MediaSources'][0]['Path']
        except (IndexError, KeyError):
            playurl = self.item['Path']

        if self.item.get('VideoType'):
            # Specific format modification
            if self.item['VideoType'] == "Dvd":
                playurl = "%s/VIDEO_TS/VIDEO_TS.IFO" % playurl
            elif self.item['VideoType'] == "BluRay":
                playurl = "%s/BDMV/index.bdmv" % playurl

        # Assign network protocol
        if playurl.startswith('\\\\'):
            playurl = playurl.replace("\\\\", "smb://")
            playurl = playurl.replace("\\", "/")

        if "apple.com" in playurl:
            USER_AGENT = "QuickTime/7.7.4"
            playurl += "?|User-Agent=%s" % USER_AGENT

        return playurl

    def fileExists(self):

        if 'Path' not in self.item:
            # File has no path defined in server
            return False

        # Convert path to direct play
        path = self.directPlay()
        log.info("Verifying path: %s" % path)

        if xbmcvfs.exists(path):
            log.info("Path exists.")
            return True

        elif ":" not in path:
            log.info("Can't verify path, assumed linux. Still try to direct play.")
            return True

        else:
            log.info("Failed to find file.")
            return False

    def mustTranscode(self):
        """
        Returns True if we need to transcode because
            - codec is in h265
            - 10bit video codec
            - HEVC codec
            - window variable 'plex_forcetranscode' set to 'true'
                (excepting trailers etc.)
            - video bitrate above specified settings bitrate
        if the corresponding file settings are set to 'true'
        """
        if self.API.getType() == 'track':
            #We are dealing with a music file here, returning False to asume Kodi can play all audio files 
            return False
        videoCodec = self.API.getVideoCodec()
        log.info("videoCodec: %s" % videoCodec)
        if self.API.getType() in ('clip', 'track'):
            log.info('Plex clip or music track, not transcoding')
            return False
        if window('plex_forcetranscode') == 'true':
            log.info('User chose to force-transcode')
            return True
        if (settings('transcodeHi10P') == 'true' and
                videoCodec['bitDepth'] == '10'):
            log.info('Option to transcode 10bit video content enabled.')
            return True
        codec = videoCodec['videocodec']
        if codec is None:
            # e.g. trailers. Avoids TypeError with "'h265' in codec"
            log.info('No codec from PMS, not transcoding.')
            return False
        try:
            bitrate = int(videoCodec['bitrate'])
        except (TypeError, ValueError):
            log.info('No video bitrate from PMS, not transcoding.')
            return False
        if bitrate > self.get_max_bitrate():
            log.info('Video bitrate of %s is higher than the maximal video'
                     'bitrate of %s that the user chose. Transcoding'
                     % (bitrate, self.get_max_bitrate()))
            return True
        try:
            resolution = int(videoCodec['resolution'])
        except (TypeError, ValueError):
            log.info('No video resolution from PMS, not transcoding.')
            return False
        if 'h265' in codec or 'hevc' in codec:
            if resolution >= self.getH265():
                log.info("Option to transcode h265/HEVC enabled. Resolution "
                         "of the media: %s, transcoding limit resolution: %s"
                         % (str(resolution), str(self.getH265())))
                return True
        return False

    def isDirectStream(self):
        # Never transcode Music
        if self.API.getType() == 'track':
            return True
        # set to 'Transcode=2'
        if settings('playType') == "2":
            # User forcing to play via HTTP
            log.info("User chose to transcode")
            return False
        if self.mustTranscode():
            return False
        return True

    def get_max_bitrate(self):
        # get the addon video quality
        videoQuality = settings('maxVideoQualities')
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
        return H265[settings('transcodeH265')]

    def get_bitrate(self):
        """
        Get the desired transcoding bitrate from the settings
        """
        videoQuality = settings('transcoderVideoQualities')
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
        chosen = settings('transcoderVideoQualities')
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

    def audioSubsPref(self, listitem, url, part=None):
        dialog = xbmcgui.Dialog()
        # For transcoding only
        # Present the list of audio to select from
        audioStreamsList = []
        audioStreams = []
        # audioStreamsChannelsList = []
        subtitleStreamsList = []
        subtitleStreams = ['1 No subtitles']
        downloadableStreams = []
        # selectAudioIndex = ""
        selectSubsIndex = ""
        playurlprefs = {}

        # Set part where we're at
        self.API.setPartNumber(part)
        if part is None:
            part = 0
        try:
            mediastreams = self.item[0][part]
        except (TypeError, KeyError, IndexError):
            return url

        audioNum = 0
        # Remember 'no subtitles'
        subNum = 1
        defaultSub = None
        for stream in mediastreams:
            # Since Plex returns all possible tracks together, have to sort
            # them.
            index = stream.attrib.get('id')
            type = stream.attrib.get('streamType')

            # Audio
            if type == "2":
                codec = stream.attrib.get('codec')
                channelLayout = stream.attrib.get('audioChannelLayout', "")
               
                try:
                    track = "%s %s - %s %s" % (audioNum+1, stream.attrib['language'], codec, channelLayout)
                except:
                    track = "%s 'unknown' - %s %s" % (audioNum+1, codec, channelLayout)
                audioStreamsList.append(index)
                audioStreams.append(tryEncode(track))
                audioNum += 1

            # Subtitles
            elif type == "3":
                try:
                    track = "%s %s" % (subNum+1, stream.attrib['language'])
                except:
                    track = "%s 'unknown' (%s)" % (subNum+1, stream.attrib.get('codec'))

                default = stream.attrib.get('default')
                forced = stream.attrib.get('forced')
                downloadable = stream.attrib.get('key')

                if default:
                    track = "%s - Default" % track
                if forced:
                    track = "%s - Forced" % track
                if downloadable:
                    downloadableStreams.append(index)
                else:
                    track = "%s (burn-in)" % track
                if stream.attrib.get('selected') == '1' and downloadable:
                    # Only show subs without asking user if they can be
                    # turned off
                    defaultSub = index

                subtitleStreamsList.append(index)
                subtitleStreams.append(tryEncode(track))
                subNum += 1

        if audioNum > 1:
            resp = dialog.select(lang(33013), audioStreams)
            if resp > -1:
                # User selected audio
                playurlprefs['audioStreamID'] = audioStreamsList[resp]
            else: # User backed out of selection - let PMS decide
                pass
        else: # There's only one audiotrack.
            playurlprefs['audioStreamID'] = audioStreamsList[0]

        # Add audio boost
        playurlprefs['audioBoost'] = settings('audioBoost')

        selectSubsIndex = None
        if subNum > 1:
            if (settings('pickPlexSubtitles') == 'true' and
                    defaultSub is not None):
                log.info('Using default Plex subtitle: %s' % defaultSub)
                selectSubsIndex = defaultSub
            else:
                resp = dialog.select(lang(33014), subtitleStreams)
                if resp > 0:
                    selectSubsIndex = subtitleStreamsList[resp-1]
                else:
                    # User selected no subtitles or backed out of dialog
                    playurlprefs["skipSubtitles"] = 1
            if selectSubsIndex is not None:
                # Load subtitles in the listitem if downloadable
                if selectSubsIndex in downloadableStreams:
                    sub_url = self.API.addPlexHeadersToUrl(
                        "%s/library/streams/%s"
                        % (self.server, selectSubsIndex))
                    log.info("Downloadable sub: %s: %s"
                             % (selectSubsIndex, sub_url))
                    listitem.setSubtitles([tryEncode(sub_url)])
                    # Don't additionally burn in subtitles
                    playurlprefs["skipSubtitles"] = 1
                else:
                    log.info('Need to burn in subtitle %s' % selectSubsIndex)
                    playurlprefs["subtitleStreamID"] = selectSubsIndex
                    playurlprefs["subtitleSize"] = settings('subtitleSize')

        url += '&' + urlencode(playurlprefs)

        # Get number of channels for selected audio track
        # audioChannels = audioStreamsChannelsList.get(selectAudioIndex, 0)
        # if audioChannels > 2:
        #     playurlprefs += "&AudioBitrate=384000"
        # else:
        #     playurlprefs += "&AudioBitrate=192000"

        return url
