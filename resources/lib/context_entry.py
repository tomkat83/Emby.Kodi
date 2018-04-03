# -*- coding: utf-8 -*-
###############################################################################
from logging import getLogger

from xbmc import getInfoLabel, sleep, executebuiltin
from xbmcaddon import Addon

import plexdb_functions as plexdb
from utils import window, settings, dialog, language as lang
from dialogs import context
from PlexFunctions import delete_item_from_pms
import playqueue as PQ
import variables as v
import state

###############################################################################

LOG = getLogger("PLEX." + __name__)

OPTIONS = {
    'Refresh': lang(30410),
    'Delete': lang(30409),
    'Addon': lang(30408),
    # 'AddFav': lang(30405),
    # 'RemoveFav': lang(30406),
    # 'RateSong': lang(30407),
    'Transcode': lang(30412),
    'PMS_Play': lang(30415)  # Use PMS to start playback
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
        if self._select_menu():
            self._action_menu()
            if self._selected_option in (OPTIONS['Delete'],
                                         OPTIONS['Refresh']):
                LOG.info("refreshing container")
                sleep(500)
                executebuiltin('Container.Refresh')

    @staticmethod
    def _get_plex_id(kodi_id, kodi_type):
        plex_id = getInfoLabel('ListItem.Property(plexid)') or None
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
        if state.DIRECT_PATHS and self.kodi_type in v.KODI_VIDEOTYPES:
            options.append(OPTIONS['PMS_Play'])
        if self.kodi_type in v.KODI_VIDEOTYPES:
            options.append(OPTIONS['Transcode'])
        # userdata = self.api.userdata()
        # if userdata['Favorite']:
        #     # Remove from emby favourites
        #     options.append(OPTIONS['RemoveFav'])
        # else:
        #     # Add to emby favourites
        #     options.append(OPTIONS['AddFav'])
        # if self.kodi_type == "song":
        #     # Set custom song rating
        #     options.append(OPTIONS['RateSong'])
        # Refresh item
        # options.append(OPTIONS['Refresh'])
        # Delete item, only if the Plex Home main user is logged in
        if (window('plex_restricteduser') != 'true' and
                window('plex_allows_mediaDeletion') == 'true'):
            options.append(OPTIONS['Delete'])
        # Addon settings
        options.append(OPTIONS['Addon'])
        context_menu = context.ContextMenu(
            "script-emby-context.xml",
            Addon('plugin.video.plexkodiconnect').getAddonInfo('path'),
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
        # elif selected == OPTIONS['Refresh']:
        #     self.emby.refreshItem(self.item_id)
        # elif selected == OPTIONS['AddFav']:
        #     self.emby.updateUserRating(self.item_id, favourite=True)
        # elif selected == OPTIONS['RemoveFav']:
        #     self.emby.updateUserRating(self.item_id, favourite=False)
        # elif selected == OPTIONS['RateSong']:
        #     self._rate_song()
        elif selected == OPTIONS['Addon']:
            executebuiltin('Addon.OpenSettings(plugin.video.plexkodiconnect)')
        elif selected == OPTIONS['Delete']:
            self._delete_item()

    def _delete_item(self):
        """
        Delete item on PMS
        """
        delete = True
        if settings('skipContextMenu') != "true":
            if not dialog("yesno", heading="{plex}", line1=lang(33041)):
                LOG.info("User skipped deletion for: %s", self.plex_id)
                delete = False
        if delete:
            LOG.info("Deleting Plex item with id %s", self.plex_id)
            if delete_item_from_pms(self.plex_id) is False:
                dialog("ok", heading="{plex}", line1=lang(30414))

    def _PMS_play(self):
        """
        For using direct paths: Initiates playback using the PMS
        """
        playqueue = PQ.get_playqueue_from_type(
            v.KODI_PLAYLIST_TYPE_FROM_KODI_TYPE[self.kodi_type])
        playqueue.clear()
        state.CONTEXT_MENU_PLAY = True
        handle = ('plugin://%s/?plex_id=%s&plex_type=%s&mode=play'
                  % (v.ADDON_TYPE[self.plex_type],
                     self.plex_id,
                     self.plex_type))
        executebuiltin('RunPlugin(%s)' % handle)
