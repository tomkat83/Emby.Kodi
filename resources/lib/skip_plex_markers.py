#!/usr/bin/env python
# -*- coding: utf-8 -*-
from .windows.skip_marker import SkipMarkerDialog
from . import app, utils, variables as v


# Supported types of markers that can be skipped; values here will be
# displayed to the user when skipping is available
MARKERS = {
    'intro': (utils.lang(30525), 'enableSkipIntro', 'enableAutoSkipIntro'), # Skip intro
    'credits': (utils.lang(30526), 'enableSkipCredits', 'enableAutoSkipCredits'),  # Skip credits
    'commercial': (utils.lang(30530), 'enableSkipCommercials', 'enableAutoSkipCommercials'),  # Skip commercial
}

def skip_markers(markers):
    try:
        progress = app.APP.player.getTime()
    except RuntimeError:
        # XBMC is not playing any media file yet
        return
    within_marker = False
    marker_definition = None
    for start, end, typus, _ in markers:
        marker_definition = MARKERS[typus]
        if utils.settings(marker_definition[1]) == "true" and start <= progress < end:
            within_marker = True
            break
    if within_marker and app.APP.skip_markers_dialog is None:
        # WARNING: This Dialog only seems to work if called from the main
        # thread. Otherwise, onClick and onAction won't work
        app.APP.skip_markers_dialog = SkipMarkerDialog(
            'script-plex-skip_marker.xml',
            v.ADDON_PATH,
            'default',
            '1080i',
            marker_message=marker_definition[0],
            marker_end=end)
        if utils.settings(marker_definition[2]) == "true":
            app.APP.skip_markers_dialog.seekTimeToEnd()
        else:
            app.APP.skip_markers_dialog.show()
    elif not within_marker and app.APP.skip_markers_dialog is not None:
        app.APP.skip_markers_dialog.close()
        app.APP.skip_markers_dialog = None


def check():
    with app.APP.lock_playqueues:
        if len(app.PLAYSTATE.active_players) != 1:
            return
        playerid = list(app.PLAYSTATE.active_players)[0]
        markers = app.PLAYSTATE.player_states[playerid]['markers']
    if not markers:
        return
    skip_markers(markers)
