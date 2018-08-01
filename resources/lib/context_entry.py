#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
import xbmc
import xbmcgui

from . import context
from . import plexdb_functions as plexdb
from . import utils
from . import plex_functions as PF
from .plex_api import API
from . import playqueue as PQ
from . import variables as v
from . import state

###############################################################################

LOG = getLogger('PLEX.context_entry')

OPTIONS = {
    'Refresh': utils.lang(30410),
    'Delete': utils.lang(30409),
    'Addon': utils.lang(30408),
    # 'AddFav': utils.lang(30405),
    # 'RemoveFav': utils.lang(30406),
    # 'RateSong': utils.lang(30407),
    'Transcode': utils.lang(30412),
    'PMS_Play': utils.lang(30415),  # Use PMS to start playback
    'Extras': utils.lang(30235)
}

###############################################################################


class ContextMenu(object):
    """
    Class initiated if user opens "Plex options" on a PLEX item using the Kodi
    context menu
    """
    _selected_option = None

    def __init__(self, kodi_id=None, kodi_type=None):
        """
        Simply instantiate with ContextMenu() - no need to call any methods
        """
        self.kodi_id = kodi_id
        self.kodi_type = kodi_type
        self.plex_id = self._get_plex_id(self.kodi_id, self.kodi_type)
        if self.kodi_type:
            self.plex_type = v.PLEX_TYPE_FROM_KODI_TYPE[self.kodi_type]
        else:
            self.plex_type = None
        LOG.debug("Found plex_id: %s plex_type: %s",
                  self.plex_id, self.plex_type)
        if not self.plex_id:
            return
        xml = PF.GetPlexMetadata(self.plex_id)
        try:
            xml[0].attrib
        except (TypeError, IndexError, KeyError):
            self.api = None
        else:
            self.api = API(xml[0])
        if self._select_menu():
            self._action_menu()
            if self._selected_option in (OPTIONS['Delete'],
                                         OPTIONS['Refresh']):
                LOG.info("refreshing container")
                xbmc.sleep(500)
                xbmc.executebuiltin('Container.Refresh')

    @staticmethod
    def _get_plex_id(kodi_id, kodi_type):
        plex_id = xbmc.getInfoLabel('ListItem.Property(plexid)') or None
        if not plex_id and kodi_id and kodi_type:
            with plexdb.Get_Plex_DB() as plexcursor:
                item = plexcursor.getItem_byKodiId(kodi_id, kodi_type)
            try:
                plex_id = item[0]
            except TypeError:
                LOG.info('Could not get the Plex id for context menu')
        return plex_id

    def _select_menu(self):
        """
        Display select dialog
        """
        options = []
        # if user uses direct paths, give option to initiate playback via PMS
        if self.api and self.api.extras():
            options.append(OPTIONS['Extras'])
        if state.DIRECT_PATHS and self.kodi_type in v.KODI_VIDEOTYPES:
            options.append(OPTIONS['PMS_Play'])
        if self.kodi_type in v.KODI_VIDEOTYPES:
            options.append(OPTIONS['Transcode'])

        # Delete item, only if the Plex Home main user is logged in
        if (utils.window('plex_restricteduser') != 'true' and
                utils.window('plex_allows_mediaDeletion') == 'true'):
            options.append(OPTIONS['Delete'])
        # Addon settings
        options.append(OPTIONS['Addon'])
        context_menu = context.ContextMenu(
            "script-plex-context.xml",
            utils.try_encode(v.ADDON_PATH),
            "default",
            "1080i")
        context_menu.set_options(options)
        context_menu.doModal()
        if context_menu.is_selected():
            self._selected_option = context_menu.get_selected()
        return self._selected_option

    def _action_menu(self):
        """
        Do whatever the user selected to do
        """
        selected = self._selected_option
        if selected == OPTIONS['Transcode']:
            state.FORCE_TRANSCODE = True
            self._PMS_play()
        elif selected == OPTIONS['PMS_Play']:
            self._PMS_play()
        elif selected == OPTIONS['Extras']:
            self._extras()

        elif selected == OPTIONS['Addon']:
            xbmc.executebuiltin(
                'Addon.OpenSettings(plugin.video.plexkodiconnect)')
        elif selected == OPTIONS['Delete']:
            self._delete_item()

    def _delete_item(self):
        """
        Delete item on PMS
        """
        delete = True
        if utils.settings('skipContextMenu') != "true":
            if not utils.dialog("yesno", heading="{plex}", line1=utils.lang(33041)):
                LOG.info("User skipped deletion for: %s", self.plex_id)
                delete = False
        if delete:
            LOG.info("Deleting Plex item with id %s", self.plex_id)
            if PF.delete_item_from_pms(self.plex_id) is False:
                utils.dialog("ok", heading="{plex}", line1=utils.lang(30414))

    def _PMS_play(self):
        """
        For using direct paths: Initiates playback using the PMS
        """
        playqueue = PQ.get_playqueue_from_type(
            v.KODI_PLAYLIST_TYPE_FROM_KODI_TYPE[self.kodi_type])
        playqueue.clear()
        state.CONTEXT_MENU_PLAY = True
        handle = self.api.path(force_first_media=False, force_addon=True)
        xbmc.executebuiltin('RunPlugin(%s)' % handle)

    def _extras(self):
        """
        Displays a list of elements for all the extras of the Plex element
        """
        handle = ('plugin://plugin.video.plexkodiconnect?mode=extras&plex_id=%s'
                  % self.plex_id)
        if xbmcgui.getCurrentWindowId() == 10025:
            # Video Window
            xbmc.executebuiltin('Container.Update(\"%s\")' % handle)
        else:
            xbmc.executebuiltin('ActivateWindow(videos, \"%s\")' % handle)
