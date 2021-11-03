#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .windows.skip_intro import SkipIntroDialog
from . import app, utils, variables as v


def skip_intro(intros):
    try:
        progress = app.APP.player.getTime()
    except RuntimeError:
        # XBMC is not playing any media file yet
        return
    in_intro = False
    for start, end in intros:
        if start <= progress < end:
            in_intro = True
    if in_intro and app.APP.skip_intro_dialog is None:
        app.APP.skip_intro_dialog = SkipIntroDialog('script-plex-skip_intro.xml',
                                                    v.ADDON_PATH,
                                                    'default',
                                                    '1080i',
                                                    intro_end=end)

        if utils.settings('enableAutoSkipIntro') == "true":
            app.APP.skip_intro_dialog.seekTimeToIntroEnd()
        else:
            app.APP.skip_intro_dialog.show()
    elif not in_intro and app.APP.skip_intro_dialog is not None:
        app.APP.skip_intro_dialog.close()
        app.APP.skip_intro_dialog = None


def check():
    with app.APP.lock_playqueues:
        playerid = list(app.PLAYSTATE.active_players)[0]
        intros = app.PLAYSTATE.player_states[playerid]['intro_markers']
    if not intros:
        return
    skip_intro(intros)
