import mediachoice
import serverdecision
import plexapp
import util


class MediaDecisionEngine(object):
    proxyTypes = util.AttributeDict({
        'NORMAL': 0,
        'LOCAL': 42,
        'CLOUD': 43
    })

    def __init__(self):
        self.softSubLanguages = None

    # TODO(schuyler): Do we need to allow this to be async? We may have to request
    # the media again to fetch details, and we may need to make multiple requests to
    # resolve an indirect. We can do it all async, we can block, or we can allow
    # both.

    def chooseMedia(self, item, forceUpdate=False):
        # If we've already evaluated this item, use our previous choice.
        if not forceUpdate and item.mediaChoice is not None and item.mediaChoice.media is not None and not item.mediaChoice.media.isIndirect():
            return item.mediaChoice

        # See if we're missing media/stream details for this item.
        if item.isLibraryItem() and item.isVideoItem() and len(item.media) > 0 and not item.media[0].hasStreams():
            # TODO(schuyler): Fetch the details
            util.WARN_LOG("Can't make media choice, missing details")

        # Take a first pass through the media items to create an array of candidates
        # that we'll evaluate more completely. If we find a forced item, we use it.
        # If we find an indirect, we only keep a single candidate.
        indirect = False
        candidates = []
        maxResolution = item.settings.getMaxResolution(item.getQualityType())
        for mediaIndex in range(len(item.media)):
            media = item.media[mediaIndex]
            media.mediaIndex = mediaIndex
            if media.isSelected():
                candidates = []
                candidates.append(media)
                break
            if media.isIndirect():
                # Only add indirect media if the resolution fits. We cannot
                # exit early as the user may have selected media.

                indirect = True
                if media.getVideoResolution() <= maxResolution:
                    candidates.append(media)

            elif media.isAccessible():
                # Only consider testing available media
                candidates.append(media)

        # Only use the first indirect media item
        if indirect and candidates:
            candidates = candidates[0]

        # Make sure we have at least one valid item, regardless of availability
        if len(candidates) == 0:
            candidates.append(item.media[0])

        # Now that we have an array of candidates, evaluate them completely.
        choices = []
        for media in candidates:
            choice = None
            if media is not None:
                if item.isVideoItem():
                    choice = self.evaluateMediaVideo(item, media)
                elif item.isMusicItem():
                    choice = self.evaluateMediaMusic(item, media)
                else:
                    choice = mediachoice.MediaChoice(media)
                choices.append(choice)
        item.mediaChoice = self.sortChoices(choices)[-1]
        util.LOG("MDE: MediaChoice: {0}".format(item.mediaChoice))
        return item.mediaChoice

    def sortChoices(self, choices):
        if choices is None:
            return []

        if len(choices) > 1:
            self.sort(choices, "bitrate")
            self.sort(choices, "audioChannels")
            self.sort(choices, "audioDS")
            self.sort(choices, "resolution")
            self.sort(choices, "videoDS")
            self.sort(choices, "directPlay")
            self.sort(choices, self.higherResIfCapable)
            self.sort(choices, self.cloudIfRemote)

        return choices

    def evaluateMediaVideo(self, item, media, partIndex=0):
        # Resolve indirects before doing anything else.
        if media.isIndirect():
            util.LOG("Resolve indirect media for {0}".format(item))
            media = media.resolveIndirect()

        choice = mediachoice.MediaChoice(media, partIndex)
        server = item.getServer()

        if not media:
            return choice

        choice.isSelected = media.isSelected()
        choice.protocol = media.protocol("http")

        maxResolution = item.settings.getMaxResolution(item.getQualityType(), self.isSupported4k(media, choice.videoStream))
        maxBitrate = item.settings.getMaxBitrate(item.getQualityType())

        choice.resolution = media.getVideoResolution()
        if choice.resolution > maxResolution or media.bitrate.asInt() > maxBitrate:
            choice.forceTranscode = True

        if choice.subtitleStream:
            choice.subtitleDecision = self.evaluateSubtitles(choice.subtitleStream)
            choice.hasBurnedInSubtitles = (choice.subtitleDecision != choice.SUBTITLES_SOFT_DP and choice.subtitleDecision != choice.SUBTITLES_SOFT_ANY)
        else:
            choice.hasBurnedInSubtitles = False

        # For evaluation purposes, we only care about the first part
        part = media.parts[partIndex]
        if not part:
            return choice

        # Although PMS has already told us which streams are selected, we can't
        # necessarily tell the video player which streams we want. So we need to
        # iterate over the streams and see if there are any red flags that would
        # prevent direct play. If there are multiple video streams, we're hosed.
        # For audio streams, we have a fighting chance if the selected stream can
        # be selected by language, but we need to be careful about guessing which
        # audio stream the Roku will pick for a given language.

        numVideoStreams = 0
        problematicAudioStream = False

        if part.get('hasChapterVideoStream').asBool():
            numVideoStreams = 1

        for stream in part.streams:
            streamType = stream.streamType.asInt()
            if streamType == stream.TYPE_VIDEO:
                numVideoStreams = numVideoStreams + 1

                if stream.codec == "h264" or (
                    stream.codec == "hevc" and item.settings.getPreference("allow_hevc", False)
                ) or (
                    stream.codec == "vp9" and item.settings.getGlobal("vp9Support")
                ):
                    choice.sorts.videoDS = 1

        # Special cases to force direct play
        forceDirectPlay = False
        if choice.protocol == "hls":
            util.LOG("MDE: Assuming HLS is direct playable")
            forceDirectPlay = True
        elif not server.supportsVideoTranscoding:
            # See if we can use another server to transcode, otherwise force direct play
            transcodeServer = item.getTranscodeServer(True, "video")
            if not transcodeServer or not transcodeServer.supportsVideoTranscoding:
                util.LOG("MDE: force direct play because the server does not support video transcoding")
                forceDirectPlay = True

        # See if we found any red flags based on the streams. Otherwise, go ahead
        # with our codec checks.

        if forceDirectPlay:
            # Consider the choice DP, but continue to allow the
            # choice to have the sorts set properly.
            choice.isDirectPlayable = True
        elif choice.hasBurnedInSubtitles:
            util.LOG("MDE: Need to burn in subtitles")
        elif choice.protocol != "http":
            util.LOG("MDE: " + choice.protocol + " not supported")
        elif numVideoStreams > 1:
            util.LOG("MDE: Multiple video streams, won't try to direct play")
        elif problematicAudioStream:
            util.LOG("MDE: Problematic AAC stream with more than 2 channels prevents direct play")
        elif self.canDirectPlay(item, choice):
            choice.isDirectPlayable = True
        elif item.isMediaSynthesized:
            util.LOG("MDE: assuming synthesized media can direct play")
            choice.isDirectPlayable = True

        # Check for a server decision. This is authority as it's the only playback type
        # the server will allow. This will also support forcing direct play, overriding
        # only our local MDE checks based on the user pref, and only if the server
        # agrees.
        decision = part.get("decision")
        if decision:
            if decision != serverdecision.ServerDecision.DECISION_DIRECT_PLAY:
                util.LOG("MDE: Server has decided this cannot direct play")
                choice.isDirectPlayable = False
            else:
                util.LOG("MDE: Server has allowed direct play")
                choice.isDirectPlayable = True

        # Setup sorts
        if choice.videoStream is not None:
            choice.sorts.bitrate = choice.videoStream.bitrate.asInt()
        elif choice.media is not None:
            choice.sorts.bitrate = choice.media.bitrate.asInt()
        else:
            choice.sorts.bitrate = 0

        if choice.audioStream is not None:
            choice.sorts.audioChannels = choice.audioStream.channels.asInt()
        elif choice.media is not None:
            choice.sorts.audioChannels = choice.media.audioChannels.asInt()
        else:
            choice.sorts.audioChannels = 0

        choice.sorts.videoDS = not (choice.sorts.videoDS is None or choice.forceTranscode is True) and choice.sorts.videoDS or 0
        choice.sorts.resolution = choice.resolution

        # Server properties probably don't need to be associated with each choice
        choice.sorts.canTranscode = server.supportsVideoTranscoding and 1 or 0
        choice.sorts.canRemuxOnly = server.supportsVideoRemuxOnly and 1 or 0
        choice.sorts.directPlay = (choice.isDirectPlayable is True and choice.forceTranscode is not True) and 1 or 0
        choice.sorts.proxyType = choice.media.proxyType and choice.media.proxyType or self.proxyTypes.NORMAL

        return choice

    def canDirectPlay(self, item, choice):
        maxResolution = item.settings.getMaxResolution(item.getQualityType(), self.isSupported4k(choice.media, choice.videoStream))
        height = choice.media.getVideoResolution()
        if height > maxResolution:
            util.LOG("MDE: (DP) Video height is greater than max allowed: {0} > {1}".format(height, maxResolution))
            if height > 1088 and item.settings.getPreference("allow_4k", True):
                util.LOG("MDE: (DP) Unsupported 4k media")
            return False

        maxBitrate = item.settings.getMaxBitrate(item.getQualityType())
        bitrate = choice.media.bitrate.asInt()
        if bitrate > maxBitrate:
            util.LOG("MDE: (DP) Video bitrate is greater than the allowed max: {0} > {1}".format(bitrate, maxBitrate))
            return False

        if choice.videoStream is None:
            util.ERROR_LOG("MDE: (DP) No video stream")
            return True

        if not item.settings.getGlobal("supports1080p60"):
            videoFrameRate = choice.videoStream.asInt()
            if videoFrameRate > 30 and height >= 1080:
                util.LOG("MDE: (DP) Frame rate is not supported for resolution: {0}@{1}".format(height, videoFrameRate))
                return False

        if choice.videoStream.codec == "hevc" and not item.settings.getPreference("allow_hevc", False):
            util.LOG("MDE: (DP) Codec is HEVC, which is disabled")
            return False

        return True

        # container = choice.media.get('container')
        # videoCodec = choice.videoStream.codec
        # if choice.audioStream is None:
        #     audioCodec = None
        #     numChannels = 0
        # else:
        #     audioCodec = choice.audioStream.codec
        #     numChannels = choice.audioStream.channels.asInt()

        # Formats: https://support.roku.com/hc/en-us/articles/208754908-Roku-Media-Player-Playing-your-personal-videos-music-photos
        #  All Models: H.264/AVC  (MKV, MP4, MOV),
        # Roku 4 only: H.265/HEVC (MKV, MP4, MOV); VP9 (.MKV)

        # if True:  # container in ("mp4", "mov", "m4v", "mkv"):
        #     util.LOG("MDE: {0} container looks OK, checking streams".format(container))

        #     isHEVC = videoCodec == "hevc" and item.settings.getPreference("allow_hevc", False)
        #     isVP9 = videoCodec == "vp9" and container == "mkv" and item.settings.getGlobal("vp9Support")

        #     if videoCodec != "h264" and videoCodec != "mpeg4" and not isHEVC and not isVP9:
        #         util.LOG("MDE: Unsupported video codec: {0}".format(videoCodec))
        #         return False

        #     # TODO(schuyler): Fix ref frames check. It's more nuanced than this.
        #     if choice.videoStream.refFrames.asInt() > 8:
        #         util.LOG("MDE: Too many ref frames: {0}".format(choice.videoStream.refFrames))
        #         return False

        #     # HEVC supports a bitDepth of 10, otherwise 8 is the limit
        #     if choice.videoStream.bitDepth.asInt() > (isHEVC and 10 or 8):
        #         util.LOG("MDE: Bit depth too high: {0}".format(choice.videoStream.bitDepth))
        #         return False

        #     # We shouldn't have to whitelist particular audio codecs, we can just
        #     # check to see if the Roku can decode this codec with the number of channels.
        #     if not item.settings.supportsAudioStream(audioCodec, numChannels):
        #         util.LOG("MDE: Unsupported audio track: {0} ({1} channels)".format(audioCodec, numChannels))
        #         return False

        #     # # TODO(schuyler): We've reported this to Roku, they may fix it. If/when
        #     # # they do, we should move this behind a firmware version check.
        #     # if container == "mkv" and choice.videoStream.headerStripping.asBool() and audioCodec == "ac3":
        #     #     util.ERROR_LOG("MDE: Header stripping with AC3 audio")
        #     #     return False

        #     # Those were our problems, everything else should be OK.
        #     return True
        # else:
        #     util.LOG("MDE: Unsupported container: {0}".format(container))

        # return False

    def evaluateSubtitles(self, stream):
        if plexapp.INTERFACE.getPreference("burn_subtitles") == "always":
            # If the user prefers them burned, always burn
            return mediachoice.MediaChoice.SUBTITLES_BURN
        # elif stream.codec != "srt":
        #     # We only support soft subtitles for SRT. Anything else has to use the
        #     # transcoder, and we defer to it on whether the subs will have to be
        #     # burned or can be converted to SRT and muxed.

        #     return mediachoice.MediaChoice.SUBTITLES_DEFAULT
        elif stream.key is None:
            # Embedded subs don't have keys and can only be direct played
            result = mediachoice.MediaChoice.SUBTITLES_SOFT_DP
        else:
            # Sidecar subs can be direct played or used alongside a transcode
            result = mediachoice.MediaChoice.SUBTITLES_SOFT_ANY

        # # TODO(schuyler) If Roku adds support for non-Latin characters, remove
        # # this hackery. To the extent that we continue using this hackery, it
        # # seems that the Roku requires UTF-8 subtitles but only supports characters
        # # from Windows-1252. This should be the full set of languages that are
        # # completely representable in Windows-1252. PMS should specifically be
        # # returning ISO 639-2/B language codes.
        # # Update: Roku has added support for additional characters, but still only
        # # Latin characters. We can now basically support anything from the various
        # # ISO-8859 character sets, but nothing non-Latin.

        # if not self.softSubLanguages:
        #     self.softSubLanguages = frozenset((
        #         'afr',
        #         'alb',
        #         'baq',
        #         'bre',
        #         'cat',
        #         'cze',
        #         'dan',
        #         'dut',
        #         'eng',
        #         'epo',
        #         'est',
        #         'fao',
        #         'fin',
        #         'fre',
        #         'ger',
        #         'gla',
        #         'gle',
        #         'glg',
        #         'hrv',
        #         'hun',
        #         'ice',
        #         'ita',
        #         'lat',
        #         'lav',
        #         'lit',
        #         'ltz',
        #         'may',
        #         'mlt',
        #         'nno',
        #         'nob',
        #         'nor',
        #         'oci',
        #         'pol',
        #         'por',
        #         'roh',
        #         'rum',
        #         'slo',
        #         'slv',
        #         'spa',
        #         'srd',
        #         'swa',
        #         'swe',
        #         'tur',
        #         'vie',
        #         'wel',
        #         'wln'
        #     ))

        # if not (stream.languageCode or 'eng') in self.softSubLanguages:
        #     # If the language is unsupported,: we need to force burning
        #     result = mediachoice.MediaChoice.SUBTITLES_BURN

        return result

    def evaluateMediaMusic(self, item, media):
        # Resolve indirects before doing anything else.
        if media.isIndirect():
            util.LOG("Resolve indirect media for {0}".format(item))
            media = media.resolveIndirect()

        choice = mediachoice.MediaChoice(media)
        if media is None:
            return choice

        # Verify the server supports audio transcoding, otherwise force direct play
        if not item.getServer().supportsAudioTranscoding:
            util.LOG("MDE: force direct play because the server does not support audio transcoding")
            choice.isDirectPlayable = True
            return choice

        # See if this part has a server decision to transcode and obey it
        if choice.part and choice.part.get(
                "decision", serverdecision.ServerDecision.DECISION_DIRECT_PLAY
        ) != serverdecision.ServerDecision.DECISION_DIRECT_PLAY:
            util.WARN_LOG("MDE: Server has decided this cannot direct play")
            return choice

        # Verify the codec and container are compatible
        codec = media.audioCodec
        container = media.get('container')
        canPlayCodec = item.settings.supportsAudioStream(codec, media.audioChannels.asInt())
        canPlayContainer = (codec == container) or True  # (container in ("mp4", "mka", "mkv"))

        choice.isDirectPlayable = (canPlayCodec and canPlayContainer)
        if choice.isDirectPlayable:
            # Inspect the audio stream attributes if the codec/container can direct
            # play. For now we only need to verify the sample rate.

            if choice.audioStream is not None and choice.audioStream.samplingRate.asInt() >= 192000:
                util.LOG("MDE: sampling rate is not compatible")
                choice.isDirectPlayable = False
        else:
            util.LOG("MDE: container or codec is incompatible")

        return choice

    # Simple Quick sort function modeled after roku sdk function
    def sort(self, choices, key=None):
        if not isinstance(choices, list):
            return

        if key is None:
            choices.sort()
        elif isinstance(key, basestring):
            choices.sort(key=lambda x: getattr(x.media, key))
        elif hasattr(key, '__call__'):
            choices.sort(key=key)

    def higherResIfCapable(self, choice):
        if choice.media is not None:
            server = choice.media.getServer()
            if server.supportsVideoTranscoding and not server.supportsVideoRemuxOnly and (choice.sorts.directPlay == 1 or choice.sorts.videoDS == 1):
                return util.validInt(choice.sorts.resolution)

        return 0

    def cloudIfRemote(self, choice):
        if choice.media is not None and choice.media.getServer().isLocalConnection() and choice.media.proxyType != self.proxyTypes.CLOUD:
            return 1

        return 0

    def isSupported4k(self, media, videoStream):
        if videoStream is None or not plexapp.INTERFACE.getPreference("allow_4k", True):
            return False

        # # Roku 4 only: H.265/HEVC (MKV, MP4, MOV); VP9 (.MKV)
        # if media.get('container') in ("mp4", "mov", "m4v", "mkv"):
        #     isHEVC = (videoStream.codec == "hevc" and plexapp.INTERFACE.getPreference("allow_hevc"))
        #     isVP9 = (videoStream.codec == "vp9" and media.get('container') == "mkv" and plexapp.INTERFACE.getGlobal("vp9Support"))
        #     return (isHEVC or isVP9)

        # return False

        return True
