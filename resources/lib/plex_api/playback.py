#!/usr/bin/env python
# -*- coding: utf-8 -*-
from ..utils import cast


class Playback(object):
    def decision_code(self):
        """
        Returns the general_play_decision_code or mde_play_decision_code if
        not available. Returns None if something went wrong
        """
        return self.general_play_decision_code() or self.mde_play_decision_code()

    def general_play_decision_code(self):
        """
        Returns the 'generalDecisionCode' as an int or None
        Generally, the 1xxx codes constitute a a success decision, 2xxx a
        general playback error, 3xxx a direct play error, and 4xxx a transcode
        error.

        General decisions can include:

        1000: Direct play OK.
        1001: Direct play not available; Conversion OK.
        2000: Neither direct play nor conversion is available.
        2001: Not enough bandwidth for any playback of this item.
        2002: Number of allowed streams has been reached. Stop a playback or ask
              admin for more permissions.
        2003: File is unplayable.
        2004: Streaming Session doesn’t exist or timed out.
        2005: Client stopped playback.
        2006: Admin Terminated Playback.
        """
        return cast(int, self.xml.get('generalDecisionCode'))

    def general_play_decision_text(self):
        """
        Returns the text associated with the general_play_decision_code() as
        text in unicode or None
        """
        return self.xml.get('generalDecisionText')

    def mde_play_decision_code(self):
        return cast(int, self.xml.get('mdeDecisionCode'))

    def mde_play_decision_text(self):
        """
        Returns the text associated with the mde_play_decision_code() as
        text in unicode or None
        """
        return self.xml.get('mdeDecisionText')

    def direct_play_decision_code(self):
        return cast(int, self.xml.get('directPlayDecisionCode'))

    def direct_play_decision_text(self):
        """
        Returns the text associated with the mde_play_decision_code() as
        text in unicode or None
        """
        return self.xml.get('directPlayDecisionText')

    def transcode_decision_code(self):
        return cast(int, self.xml.get('directPlayDecisionCode'))

    def transcode_decision_text(self):
        """
        Returns the text associated with the mde_play_decision_code() as
        text in unicode or None
        """
        return self.xml.get('directPlayDecisionText')

    def video_decision(self):
        """
        Returns "copy" if PMS streaming brain decided to DirectStream, so copy
        an existing video stream into a new container. Returns "transcode" if
        the video stream will be transcoded.

        Raises IndexError if something went wrong. Might also return None
        """
        for stream in self.xml[0][0][0]:
            if stream.get('streamType') == '1':
                return stream.get('decision')

    def audio_decision(self):
        """
        Returns "copy" if PMS streaming brain decided to DirectStream, so copy
        an existing audio stream into a new container. Returns "transcode" if
        the audio stream will be transcoded.

        Raises IndexError if something went wrong. Might also return None
        """
        for stream in self.xml[0][0][0]:
            if stream.get('streamType') == '2':
                return stream.get('decision')

    def subtitle_decision(self):
        """
        Returns the PMS' decision on the subtitle stream.

        Raises IndexError if something went wrong. Might also return None
        """
        for stream in self.xml[0][0][0]:
            if stream.get('streamType') == '3':
                return stream.get('decision')
