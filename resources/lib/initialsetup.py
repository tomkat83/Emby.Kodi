#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from Queue import Queue
import xml.etree.ElementTree as etree

from xbmc import executebuiltin, translatePath

from . import utils
from . import path_ops
from . import migration
from .downloadutils import DownloadUtils as DU
from . import videonodes
from . import userclient
from . import clientinfo
from . import plex_functions as PF
from . import plex_tv
from . import json_rpc as js
from . import playqueue as PQ
from . import state
from . import variables as v

###############################################################################

LOG = getLogger('PLEX.initialsetup')

###############################################################################

if not path_ops.exists(v.EXTERNAL_SUBTITLE_TEMP_PATH):
    path_ops.makedirs(v.EXTERNAL_SUBTITLE_TEMP_PATH)


WINDOW_PROPERTIES = (
    "plex_online", "plex_serverStatus", "plex_shouldStop", "plex_dbScan",
    "plex_customplayqueue", "plex_playbackProps",
    "pms_token", "plex_token", "pms_server", "plex_machineIdentifier",
    "plex_servername", "plex_authenticated", "PlexUserImage", "useDirectPaths",
    "countError", "countUnauthorized", "plex_restricteduser",
    "plex_allows_mediaDeletion", "plex_command", "plex_result",
    "plex_force_transcode_pix"
)


def reload_pkc():
    """
    Will reload state.py entirely and then initiate some values from the Kodi
    settings file
    """
    LOG.info('Start (re-)loading PKC settings')
    # Reset state.py
    reload(state)
    # Reset window props
    for prop in WINDOW_PROPERTIES:
        utils.window(prop, clear=True)
    # Clear video nodes properties
    videonodes.VideoNodes().clearProperties()

    # Initializing
    state.VERIFY_SSL_CERT = utils.settings('sslverify') == 'true'
    state.SSL_CERT_PATH = utils.settings('sslcert') \
        if utils.settings('sslcert') != 'None' else None
    state.FULL_SYNC_INTERVALL = int(utils.settings('fullSyncInterval')) * 60
    state.SYNC_THREAD_NUMBER = int(utils.settings('syncThreadNumber'))
    state.SYNC_DIALOG = utils.settings('dbSyncIndicator') == 'true'
    state.ENABLE_MUSIC = utils.settings('enableMusic') == 'true'
    state.BACKGROUND_SYNC_DISABLED = utils.settings(
        'enableBackgroundSync') == 'false'
    state.BACKGROUNDSYNC_SAFTYMARGIN = int(
        utils.settings('backgroundsync_saftyMargin'))
    state.REPLACE_SMB_PATH = utils.settings('replaceSMB') == 'true'
    state.REMAP_PATH = utils.settings('remapSMB') == 'true'
    state.KODI_PLEX_TIME_OFFSET = float(utils.settings('kodiplextimeoffset'))
    state.FETCH_PMS_ITEM_NUMBER = utils.settings('fetch_pms_item_number')
    state.FORCE_RELOAD_SKIN = \
        utils.settings('forceReloadSkinOnPlaybackStop') == 'true'
    # Init some Queues()
    state.COMMAND_PIPELINE_QUEUE = Queue()
    state.COMPANION_QUEUE = Queue(maxsize=100)
    state.WEBSOCKET_QUEUE = Queue()
    set_replace_paths()
    set_webserver()
    # To detect Kodi profile switches
    utils.window('plex_kodiProfile',
                 value=utils.try_decode(translatePath("special://profile")))
    clientinfo.getDeviceId()
    # Initialize the PKC playqueues
    PQ.init_playqueues()
    LOG.info('Done (re-)loading PKC settings')


def set_replace_paths():
    """
    Sets our values for direct paths correctly (including using lower-case
    protocols like smb:// and NOT SMB://)
    """
    for typus in v.REMAP_TYPE_FROM_PLEXTYPE.values():
        for arg in ('Org', 'New'):
            key = 'remapSMB%s%s' % (typus, arg)
            value = utils.settings(key)
            if '://' in value:
                protocol = value.split('://', 1)[0]
                value = value.replace(protocol, protocol.lower())
            setattr(state, key, value)


def set_webserver():
    """
    Set the Kodi webserver details - used to set the texture cache
    """
    if js.get_setting('services.webserver') in (None, False):
        # Enable the webserver, it is disabled
        js.set_setting('services.webserver', True)
        # Set standard port and username
        # set_setting('services.webserverport', 8080)
        # set_setting('services.webserverusername', 'kodi')
    # Webserver already enabled
    state.WEBSERVER_PORT = js.get_setting('services.webserverport')
    state.WEBSERVER_USERNAME = js.get_setting('services.webserverusername')
    state.WEBSERVER_PASSWORD = js.get_setting('services.webserverpassword')


def _write_pms_settings(url, token):
    """
    Sets certain settings for server by asking for the PMS' settings
    Call with url: scheme://ip:port
    """
    xml = PF.get_PMS_settings(url, token)
    try:
        xml.attrib
    except AttributeError:
        LOG.error('Could not get PMS settings for %s', url)
        return
    for entry in xml:
        if entry.attrib.get('id', '') == 'allowMediaDeletion':
            value = 'true' if entry.get('value', '1') == '1' else 'false'
            utils.settings('plex_allows_mediaDeletion', value=value)
            utils.window('plex_allows_mediaDeletion', value=value)


class InitialSetup(object):
    """
    Will load Plex PMS settings (e.g. address) and token
    Will ask the user initial questions on first PKC boot
    """
    def __init__(self):
        LOG.debug('Entering initialsetup class')
        self.server = userclient.UserClient().get_server()
        self.serverid = utils.settings('plex_machineIdentifier')
        # Get Plex credentials from settings file, if they exist
        plexdict = PF.GetPlexLoginFromSettings()
        self.myplexlogin = plexdict['myplexlogin'] == 'true'
        self.plex_login = plexdict['plexLogin']
        self.plex_token = plexdict['plexToken']
        self.plexid = plexdict['plexid']
        # Token for the PMS, not plex.tv
        self.pms_token = utils.settings('accessToken')
        if self.plex_token:
            LOG.debug('Found a plex.tv token in the settings')

    def plex_tv_sign_in(self):
        """
        Signs (freshly) in to plex.tv (will be saved to file settings)

        Returns True if successful, or False if not
        """
        result = plex_tv.sign_in_with_pin()
        if result:
            self.plex_login = result['username']
            self.plex_token = result['token']
            self.plexid = result['plexid']
            return True
        return False

    def check_plex_tv_sign_in(self):
        """
        Checks existing connection to plex.tv. If not, triggers sign in

        Returns True if signed in, False otherwise
        """
        answer = True
        chk = PF.check_connection('plex.tv', token=self.plex_token)
        if chk in (401, 403):
            # HTTP Error: unauthorized. Token is no longer valid
            LOG.info('plex.tv connection returned HTTP %s', str(chk))
            # Delete token in the settings
            utils.settings('plexToken', value='')
            utils.settings('plexLogin', value='')
            # Could not login, please try again
            utils.dialog('ok', utils.lang(29999), utils.lang(39009))
            answer = self.plex_tv_sign_in()
        elif chk is False or chk >= 400:
            # Problems connecting to plex.tv. Network or internet issue?
            LOG.info('Problems connecting to plex.tv; connection returned '
                     'HTTP %s', str(chk))
            utils.dialog('ok', utils.lang(29999), utils.lang(39010))
            answer = False
        else:
            LOG.info('plex.tv connection with token successful')
            utils.settings('plex_status', value=utils.lang(39227))
            # Refresh the info from Plex.tv
            xml = DU().downloadUrl('https://plex.tv/users/account',
                                   authenticate=False,
                                   headerOptions={'X-Plex-Token': self.plex_token})
            try:
                self.plex_login = xml.attrib['title']
            except (AttributeError, KeyError):
                LOG.error('Failed to update Plex info from plex.tv')
            else:
                utils.settings('plexLogin', value=self.plex_login)
                home = 'true' if xml.attrib.get('home') == '1' else 'false'
                utils.settings('plexhome', value=home)
                utils.settings('plexAvatar', value=xml.attrib.get('thumb'))
                utils.settings('plexHomeSize',
                               value=xml.attrib.get('homeSize', '1'))
                LOG.info('Updated Plex info from plex.tv')
        return answer

    def check_existing_pms(self):
        """
        Check the PMS that was set in file settings.
        Will return False if we need to reconnect, because:
            PMS could not be reached (no matter the authorization)
            machineIdentifier did not match

        Will also set the PMS machineIdentifier in the file settings if it was
        not set before
        """
        answer = True
        chk = PF.check_connection(self.server, verifySSL=False)
        if chk is False:
            LOG.warn('Could not reach PMS %s', self.server)
            answer = False
        if answer is True and not self.serverid:
            LOG.info('No PMS machineIdentifier found for %s. Trying to '
                     'get the PMS unique ID', self.server)
            self.serverid = PF.GetMachineIdentifier(self.server)
            if self.serverid is None:
                LOG.warn('Could not retrieve machineIdentifier')
                answer = False
            else:
                utils.settings('plex_machineIdentifier', value=self.serverid)
        elif answer is True:
            temp_server_id = PF.GetMachineIdentifier(self.server)
            if temp_server_id != self.serverid:
                LOG.warn('The current PMS %s was expected to have a '
                         'unique machineIdentifier of %s. But we got '
                         '%s. Pick a new server to be sure',
                         self.server, self.serverid, temp_server_id)
                answer = False
        return answer

    @staticmethod
    def _check_pms_connectivity(server):
        """
        Checks for server's connectivity. Returns check_connection result
        """
        # Re-direct via plex if remote - will lead to the correct SSL
        # certificate
        if server['local']:
            url = ('%s://%s:%s'
                   % (server['scheme'], server['ip'], server['port']))
            # Deactive SSL verification if the server is local!
            verifySSL = False
        else:
            url = server['baseURL']
            verifySSL = True
        chk = PF.check_connection(url,
                                  token=server['token'],
                                  verifySSL=verifySSL)
        return chk

    def pick_pms(self, showDialog=False):
        """
        Searches for PMS in local Lan and optionally (if self.plex_token set)
        also on plex.tv
            showDialog=True: let the user pick one
            showDialog=False: automatically pick PMS based on machineIdentifier

        Returns the picked PMS' detail as a dict:
        {
        'machineIdentifier'     [str] unique identifier of the PMS
        'name'                  [str] name of the PMS
        'token'                 [str] token needed to access that PMS
        'ownername'             [str] name of the owner of this PMS or None if
                                the owner itself supplied tries to connect
        'product'               e.g. 'Plex Media Server' or None
        'version'               e.g. '1.11.2.4772-3e...' or None
        'device':               e.g. 'PC' or 'Windows' or None
        'platform':             e.g. 'Windows', 'Android' or None
        'local'                 [bool] True if plex.tv supplied
                                'publicAddressMatches'='1'
                                or if found using Plex GDM in the local LAN
        'owned'                 [bool] True if it's the owner's PMS
        'relay'                 [bool] True if plex.tv supplied 'relay'='1'
        'presence'              [bool] True if plex.tv supplied 'presence'='1'
        'httpsRequired'         [bool] True if plex.tv supplied
                                'httpsRequired'='1'
        'scheme'                [str] either 'http' or 'https'
        'ip':                   [str] IP of the PMS, e.g. '192.168.1.1'
        'port':                 [str] Port of the PMS, e.g. '32400'
        'baseURL':              [str] <scheme>://<ip>:<port> of the PMS
        }
        or None if unsuccessful
        """
        server = None
        # If no server is set, let user choose one
        if not self.server or not self.serverid:
            showDialog = True
        if showDialog is True:
            server = self._user_pick_pms()
        else:
            server = self._auto_pick_pms()
        if server is not None:
            _write_pms_settings(server['baseURL'], server['token'])
        return server

    def _auto_pick_pms(self):
        """
        Will try to pick PMS based on machineIdentifier saved in file settings
        but only once

        Returns server or None if unsuccessful
        """
        https_updated = False
        server = None
        while True:
            if https_updated is False:
                serverlist = PF.discover_pms(self.plex_token)
                for item in serverlist:
                    if item.get('machineIdentifier') == self.serverid:
                        server = item
                if server is None:
                    name = utils.settings('plex_servername')
                    LOG.warn('The PMS you have used before with a unique '
                             'machineIdentifier of %s and name %s is '
                             'offline', self.serverid, name)
                    return
            chk = self._check_pms_connectivity(server)
            if chk == 504 and https_updated is False:
                # switch HTTPS to HTTP or vice-versa
                if server['scheme'] == 'https':
                    server['scheme'] = 'http'
                else:
                    server['scheme'] = 'https'
                https_updated = True
                continue
            # Problems connecting
            elif chk >= 400 or chk is False:
                LOG.warn('Problems connecting to server %s. chk is %s',
                         server['name'], chk)
                return
            LOG.info('We found a server to automatically connect to: %s',
                     server['name'])
            return server

    def _user_pick_pms(self):
        """
        Lets user pick his/her PMS from a list

        Returns server or None if unsuccessful
        """
        https_updated = False
        # Searching for PMS
        utils.dialog('notification',
                     heading='{plex}',
                     message=utils.lang(30001),
                     icon='{plex}',
                     time=5000)
        while True:
            if https_updated is False:
                serverlist = PF.discover_pms(self.plex_token)
                # Exit if no servers found
                if not serverlist:
                    LOG.warn('No plex media servers found!')
                    utils.dialog('ok', utils.lang(29999), utils.lang(39011))
                    return
                # Get a nicer list
                dialoglist = []
                for server in serverlist:
                    if server['local']:
                        # server is in the same network as client.
                        # Add"local"
                        msg = utils.lang(39022)
                    else:
                        # Add 'remote'
                        msg = utils.lang(39054)
                    if server.get('ownername'):
                        # Display username if its not our PMS
                        dialoglist.append('%s (%s, %s)'
                                          % (server['name'],
                                             server['ownername'],
                                             msg))
                    else:
                        dialoglist.append('%s (%s)'
                                          % (server['name'], msg))
                # Let user pick server from a list
                resp = utils.dialog('select', utils.lang(39012), dialoglist)
                if resp == -1:
                    # User cancelled
                    return

            server = serverlist[resp]
            chk = self._check_pms_connectivity(server)
            if chk == 504 and https_updated is False:
                # Not able to use HTTP, try HTTPs for now
                serverlist[resp]['scheme'] = 'https'
                https_updated = True
                continue
            https_updated = False
            if chk == 401:
                LOG.warn('Not yet authorized for Plex server %s',
                         server['name'])
                # Please sign in to plex.tv
                utils.dialog('ok',
                             utils.lang(29999),
                             utils.lang(39013) + server['name'],
                             utils.lang(39014))
                if self.plex_tv_sign_in() is False:
                    # Exit while loop if user cancels
                    return
            # Problems connecting
            elif chk >= 400 or chk is False:
                # Problems connecting to server. Pick another server?
                answ = utils.dialog('yesno',
                                    utils.lang(29999),
                                    utils.lang(39015))
                # Exit while loop if user chooses No
                if not answ:
                    return
            # Otherwise: connection worked!
            else:
                return server

    @staticmethod
    def write_pms_to_settings(server):
        """
        Saves server to file settings
        """
        utils.settings('plex_machineIdentifier', server['machineIdentifier'])
        utils.settings('plex_servername', server['name'])
        utils.settings('plex_serverowned',
                       'true' if server['owned'] else 'false')
        # Careful to distinguish local from remote PMS
        if server['local']:
            scheme = server['scheme']
            utils.settings('ipaddress', server['ip'])
            utils.settings('port', server['port'])
            LOG.debug("Setting SSL verify to false, because server is "
                      "local")
            utils.settings('sslverify', 'false')
        else:
            baseURL = server['baseURL'].split(':')
            scheme = baseURL[0]
            utils.settings('ipaddress', baseURL[1].replace('//', ''))
            utils.settings('port', baseURL[2])
            LOG.debug("Setting SSL verify to true, because server is not "
                      "local")
            utils.settings('sslverify', 'true')

        if scheme == 'https':
            utils.settings('https', 'true')
        else:
            utils.settings('https', 'false')
        # And finally do some logging
        LOG.debug("Writing to Kodi user settings file")
        LOG.debug("PMS machineIdentifier: %s, ip: %s, port: %s, https: %s ",
                  server['machineIdentifier'], server['ip'], server['port'],
                  server['scheme'])

    def setup(self):
        """
        Initial setup. Run once upon startup.

        Check server, user, direct paths, music, direct stream if not direct
        path.
        """
        LOG.info("Initial setup called.")
        try:
            with utils.XmlKodiSetting('advancedsettings.xml',
                                      force_create=True,
                                      top_element='advancedsettings') as xml:
                # Get current Kodi video cache setting
                cache = xml.get_setting(['cache', 'memorysize'])
                # Disable foreground "Loading media information from files"
                # (still used by Kodi, even though the Wiki says otherwise)
                xml.set_setting(['musiclibrary', 'backgroundupdate'],
                                value='true')
                # Disable cleaning of library - not compatible with PKC
                xml.set_setting(['videolibrary', 'cleanonupdate'],
                                value='false')
                # Set completely watched point same as plex (and not 92%)
                xml.set_setting(['video', 'ignorepercentatend'], value='10')
                xml.set_setting(['video', 'playcountminimumpercent'],
                                value='90')
                xml.set_setting(['video', 'ignoresecondsatstart'],
                                value='60')
                reboot = xml.write_xml
        except etree.ParseError:
            cache = None
            reboot = False
        # Kodi default cache if no setting is set
        cache = str(cache.text) if cache is not None else '20971520'
        LOG.info('Current Kodi video memory cache in bytes: %s', cache)
        utils.settings('kodi_video_cache', value=cache)

        # Hack to make PKC Kodi master lock compatible
        try:
            with utils.XmlKodiSetting('sources.xml',
                                      force_create=True,
                                      top_element='sources') as xml:
                root = xml.set_setting(['video'])
                count = 2
                for source in root.findall('.//path'):
                    if source.text == "smb://":
                        count -= 1
                    if count == 0:
                        # sources already set
                        break
                else:
                    # Missing smb:// occurences, re-add.
                    for _ in range(0, count):
                        source = etree.SubElement(root, 'source')
                        etree.SubElement(
                            source,
                            'name').text = "PlexKodiConnect Masterlock Hack"
                        etree.SubElement(
                            source,
                            'path',
                            attrib={'pathversion': "1"}).text = "smb://"
                        etree.SubElement(source, 'allowsharing').text = "true"
                if reboot is False:
                    reboot = xml.write_xml
        except etree.ParseError:
            pass

        # Do we need to migrate stuff?
        migration.check_migration()
        # Reload the server IP cause we might've deleted it during migration
        self.server = userclient.UserClient().get_server()

        # Display a warning if Kodi puts ALL movies into the queue, basically
        # breaking playback reporting for PKC
        if js.settings_getsettingvalue('videoplayer.autoplaynextitem'):
            LOG.warn('Kodi setting videoplayer.autoplaynextitem is enabled!')
            if utils.settings('warned_setting_videoplayer.autoplaynextitem') == 'false':
                # Only warn once
                utils.settings('warned_setting_videoplayer.autoplaynextitem',
                               value='true')
                # Warning: Kodi setting "Play next video automatically" is
                # enabled. This could break PKC. Deactivate?
                if utils.dialog('yesno', utils.lang(29999), utils.lang(30003)):
                    js.settings_setsettingvalue('videoplayer.autoplaynextitem',
                                                False)
        # Set any video library updates to happen in the background in order to
        # hide "Compressing database"
        js.settings_setsettingvalue('videolibrary.backgroundupdate', True)

        # If a Plex server IP has already been set
        # return only if the right machine identifier is found
        if self.server:
            LOG.info("PMS is already set: %s. Checking now...", self.server)
            if self.check_existing_pms():
                LOG.info("Using PMS %s with machineIdentifier %s",
                         self.server, self.serverid)
                _write_pms_settings(self.server, self.pms_token)
                if reboot is True:
                    utils.reboot_kodi()
                return

        # If not already retrieved myplex info, optionally let user sign in
        # to plex.tv. This DOES get called on very first install run
        if not self.plex_token and self.myplexlogin:
            self.plex_tv_sign_in()

        server = self.pick_pms()
        if server is not None:
            # Write our chosen server to Kodi settings file
            self.write_pms_to_settings(server)

        # User already answered the installation questions
        if utils.settings('InstallQuestionsAnswered') == 'true':
            if reboot is True:
                utils.reboot_kodi()
            return

        # Additional settings where the user needs to choose
        # Direct paths (\\NAS\mymovie.mkv) or addon (http)?
        goto_settings = False
        if utils.dialog('yesno',
                        utils.lang(29999),
                        utils.lang(39027),
                        utils.lang(39028),
                        nolabel="Addon (Default)",
                        yeslabel="Native (Direct Paths)"):
            LOG.debug("User opted to use direct paths.")
            utils.settings('useDirectPaths', value="1")
            state.DIRECT_PATHS = True
            # Are you on a system where you would like to replace paths
            # \\NAS\mymovie.mkv with smb://NAS/mymovie.mkv? (e.g. Windows)
            if utils.dialog('yesno',
                            heading=utils.lang(29999),
                            line1=utils.lang(39033)):
                LOG.debug("User chose to replace paths with smb")
            else:
                utils.settings('replaceSMB', value="false")

            # complete replace all original Plex library paths with custom SMB
            if utils.dialog('yesno',
                            heading=utils.lang(29999),
                            line1=utils.lang(39043)):
                LOG.debug("User chose custom smb paths")
                utils.settings('remapSMB', value="true")
                # Please enter your custom smb paths in the settings under
                # "Sync Options" and then restart Kodi
                utils.dialog('ok',
                             heading=utils.lang(29999),
                             line1=utils.lang(39044))
                goto_settings = True

            # Go to network credentials?
            if utils.dialog('yesno',
                            heading=utils.lang(29999),
                            line1=utils.lang(39029),
                            line2=utils.lang(39030)):
                LOG.debug("Presenting network credentials dialog.")
                utils.passwords_xml()
        # Disable Plex music?
        if utils.dialog('yesno',
                        heading=utils.lang(29999),
                        line1=utils.lang(39016)):
            LOG.debug("User opted to disable Plex music library.")
            utils.settings('enableMusic', value="false")

        # Download additional art from FanArtTV
        if utils.dialog('yesno',
                        heading=utils.lang(29999),
                        line1=utils.lang(39061)):
            LOG.debug("User opted to use FanArtTV")
            utils.settings('FanartTV', value="true")
        # Do you want to replace your custom user ratings with an indicator of
        # how many versions of a media item you posses?
        if utils.dialog('yesno',
                        heading=utils.lang(29999),
                        line1=utils.lang(39718)):
            LOG.debug("User opted to replace user ratings with version number")
            utils.settings('indicate_media_versions', value="true")

        # If you use several Plex libraries of one kind, e.g. "Kids Movies" and
        # "Parents Movies", be sure to check https://goo.gl/JFtQV9
        # dialog.ok(heading=utils.lang(29999), line1=utils.lang(39076))

        # Need to tell about our image source for collections: themoviedb.org
        # dialog.ok(heading=utils.lang(29999), line1=utils.lang(39717))
        # Make sure that we only ask these questions upon first installation
        utils.settings('InstallQuestionsAnswered', value='true')

        if goto_settings is False:
            # Open Settings page now? You will need to restart!
            goto_settings = utils.dialog('yesno',
                                         heading=utils.lang(29999),
                                         line1=utils.lang(39017))
        if goto_settings:
            state.PMS_STATUS = 'Stop'
            executebuiltin(
                'Addon.Openutils.settings(plugin.video.plexkodiconnect)')
        elif reboot is True:
            utils.reboot_kodi()
