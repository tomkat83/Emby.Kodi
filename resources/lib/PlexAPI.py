# -*- coding: utf-8 -*-
"""
Taken from iBaa, https://github.com/iBaa/PlexConnect
Point of time: December 22, 2015


Collection of "connector functions" to Plex Media Server/MyPlex


PlexGDM:
loosely based on hippojay's plexGDM:
https://github.com/hippojay/script.plexbmc.helper... /resources/lib/plexgdm.py


Plex Media Server communication:
source (somewhat): https://github.com/hippojay/plugin.video.plexbmc
later converted from httplib to urllib2


Transcoder support:
PlexAPI_getTranscodePath() based on getTranscodeURL from pyplex/plexAPI
https://github.com/megawubs/pyplex/blob/master/plexAPI/info.py


MyPlex - Basic Authentication:
http://www.voidspace.org.uk/python/articles/urllib2.shtml
http://www.voidspace.org.uk/python/articles/authentication.shtml
http://stackoverflow.com/questions/2407126/python-urllib2-basic-auth-problem
http://stackoverflow.com/questions/111945/is-there-any-way-to-do-http-put-in-python
(and others...)
"""

import os
import logging
from time import time
import urllib2
import socket
from threading import Thread
import xml.etree.ElementTree as etree
from re import compile as re_compile, sub
from json import dumps
from urllib import urlencode, quote_plus, unquote

import xbmcgui
from xbmc import sleep, executebuiltin
from xbmcvfs import exists

import clientinfo as client
from downloadutils import DownloadUtils
from utils import window, settings, language as lang, tryDecode, tryEncode, \
    DateToKodi
from PlexFunctions import PMSHttpsEnabled
import plexdb_functions as plexdb
import variables as v

###############################################################################

log = logging.getLogger("PLEX."+__name__)

REGEX_IMDB = re_compile(r'''/(tt\d+)''')
REGEX_TVDB = re_compile(r'''thetvdb:\/\/(.+?)\?''')
###############################################################################


class PlexAPI():
    # CONSTANTS
    # Timeout for POST/GET commands, I guess in seconds
    timeout = 10

    def __init__(self):
        self.g_PMS = {}
        self.doUtils = DownloadUtils().downloadUrl

    def GetPlexLoginFromSettings(self):
        """
        Returns a dict:
            'plexLogin': settings('plexLogin'),
            'plexToken': settings('plexToken'),
            'plexhome': settings('plexhome'),
            'plexid': settings('plexid'),
            'myplexlogin': settings('myplexlogin'),
            'plexAvatar': settings('plexAvatar'),
            'plexHomeSize': settings('plexHomeSize')

        Returns strings or unicode

        Returns empty strings '' for a setting if not found.

        myplexlogin is 'true' if user opted to log into plex.tv (the default)
        plexhome is 'true' if plex home is used (the default)
        """
        return {
            'plexLogin': settings('plexLogin'),
            'plexToken': settings('plexToken'),
            'plexhome': settings('plexhome'),
            'plexid': settings('plexid'),
            'myplexlogin': settings('myplexlogin'),
            'plexAvatar': settings('plexAvatar'),
            'plexHomeSize': settings('plexHomeSize')
        }

    def GetPlexLoginAndPassword(self):
        """
        Signs in to plex.tv.

        plexLogin, authtoken = GetPlexLoginAndPassword()

        Input: nothing
        Output:
            plexLogin       plex.tv username
            authtoken       token for plex.tv

        Also writes 'plexLogin' and 'token_plex.tv' to Kodi settings file
        If not logged in, empty strings are returned for both.
        """
        retrievedPlexLogin = ''
        plexLogin = 'dummy'
        authtoken = ''
        dialog = xbmcgui.Dialog()
        while retrievedPlexLogin == '' and plexLogin != '':
            # Enter plex.tv username. Or nothing to cancel.
            plexLogin = dialog.input(lang(29999) + lang(39300),
                                     type=xbmcgui.INPUT_ALPHANUM)
            if plexLogin != "":
                # Enter password for plex.tv user
                plexPassword = dialog.input(
                    lang(39301) + plexLogin,
                    type=xbmcgui.INPUT_ALPHANUM,
                    option=xbmcgui.ALPHANUM_HIDE_INPUT)
                retrievedPlexLogin, authtoken = self.MyPlexSignIn(
                    plexLogin,
                    plexPassword,
                    {'X-Plex-Client-Identifier': window('plex_client_Id')})
                log.debug("plex.tv username and token: %s, %s"
                          % (plexLogin, authtoken))
                if plexLogin == '':
                    # Could not sign in user
                    dialog.ok(lang(29999), lang(39302) + plexLogin)
        # Write to Kodi settings file
        settings('plexLogin', value=retrievedPlexLogin)
        settings('plexToken', value=authtoken)
        return (retrievedPlexLogin, authtoken)

    def PlexTvSignInWithPin(self):
        """
        Prompts user to sign in by visiting https://plex.tv/pin

        Writes to Kodi settings file. Also returns:
        {
            'plexhome':          'true' if Plex Home, 'false' otherwise
            'username':
            'avatar':             URL to user avator
            'token':
            'plexid':             Plex user ID
            'homesize':           Number of Plex home users (defaults to '1')
        }
        Returns False if authentication did not work.
        """
        code, identifier = self.GetPlexPin()
        dialog = xbmcgui.Dialog()
        if not code:
            # Problems trying to contact plex.tv. Try again later
            dialog.ok(lang(29999), lang(39303))
            return False
        # Go to https://plex.tv/pin and enter the code:
        # Or press No to cancel the sign in.
        answer = dialog.yesno(lang(29999),
                              lang(39304) + "\n\n",
                              code + "\n\n",
                              lang(39311))
        if not answer:
            return False
        count = 0
        # Wait for approx 30 seconds (since the PIN is not visible anymore :-))
        while count < 30:
            xml = self.CheckPlexTvSignin(identifier)
            if xml is not False:
                break
            # Wait for 1 seconds
            sleep(1000)
            count += 1
        if xml is False:
            # Could not sign in to plex.tv Try again later
            dialog.ok(lang(29999), lang(39305))
            return False
        # Parse xml
        userid = xml.attrib.get('id')
        home = xml.get('home', '0')
        if home == '1':
            home = 'true'
        else:
            home = 'false'
        username = xml.get('username', '')
        avatar = xml.get('thumb', '')
        token = xml.findtext('authentication-token')
        homeSize = xml.get('homeSize', '1')
        result = {
            'plexhome': home,
            'username': username,
            'avatar': avatar,
            'token': token,
            'plexid': userid,
            'homesize': homeSize
        }
        settings('plexLogin', username)
        settings('plexToken', token)
        settings('plexhome', home)
        settings('plexid', userid)
        settings('plexAvatar', avatar)
        settings('plexHomeSize', homeSize)
        # Let Kodi log into plex.tv on startup from now on
        settings('myplexlogin', 'true')
        settings('plex_status', value='Logged in to plex.tv')
        return result

    def CheckPlexTvSignin(self, identifier):
        """
        Checks with plex.tv whether user entered the correct PIN on plex.tv/pin

        Returns False if not yet done so, or the XML response file as etree
        """
        # Try to get a temporary token
        xml = self.doUtils('https://plex.tv/pins/%s.xml' % identifier,
                           authenticate=False)
        try:
            temp_token = xml.find('auth_token').text
        except:
            log.error("Could not find token in plex.tv answer")
            return False
        if not temp_token:
            return False
        # Use temp token to get the final plex credentials
        xml = self.doUtils('https://plex.tv/users/account',
                           authenticate=False,
                           parameters={'X-Plex-Token': temp_token})
        return xml

    def GetPlexPin(self):
        """
        For plex.tv sign-in: returns 4-digit code and identifier as 2 str
        """
        code = None
        identifier = None
        # Download
        xml = self.doUtils('https://plex.tv/pins.xml',
                           authenticate=False,
                           action_type="POST")
        try:
            xml.attrib
        except:
            log.error("Error, no PIN from plex.tv provided")
            return None, None
        code = xml.find('code').text
        identifier = xml.find('id').text
        log.info('Successfully retrieved code and id from plex.tv')
        return code, identifier

    def CheckConnection(self, url, token=None, verifySSL=None):
        """
        Checks connection to a Plex server, available at url. Can also be used
        to check for connection with plex.tv.
        Will check up to 3x until reply with False

        Override SSL to skip the check by setting verifySSL=False
        if 'None', SSL will be checked (standard requests setting)
        if 'True', SSL settings from file settings are used (False/True)

        Input:
            url         URL to Plex server (e.g. https://192.168.1.1:32400)
            token       appropriate token to access server. If None is passed,
                        the current token is used
        Output:
            False       if server could not be reached or timeout occured
            200         if connection was successfull
            int         or other HTML status codes as received from the server
        """
        # Add '/clients' to URL because then an authentication is necessary
        # If a plex.tv URL was passed, this does not work.
        headerOptions = None
        if token is not None:
            headerOptions = {'X-Plex-Token': token}
        if verifySSL is True:
            verifySSL = None if settings('sslverify') == 'true' \
                else False
        if 'plex.tv' in url:
            url = 'https://plex.tv/api/home/users'
        else:
            url = url + '/library/onDeck'
        log.debug("Checking connection to server %s with verifySSL=%s"
                  % (url, verifySSL))
        # Check up to 3 times before giving up
        count = 0
        while count < 1:
            answer = self.doUtils(url,
                                  authenticate=False,
                                  headerOptions=headerOptions,
                                  verifySSL=verifySSL,
                                  timeout=4)
            if answer is None:
                log.debug("Could not connect to %s" % url)
                count += 1
                sleep(500)
                continue
            try:
                # xml received?
                answer.attrib
            except:
                if answer is True:
                    # Maybe no xml but connection was successful nevertheless
                    answer = 200
            else:
                # Success - we downloaded an xml!
                answer = 200
            # We could connect but maybe were not authenticated. No worries
            log.debug("Checking connection successfull. Answer: %s" % answer)
            return answer
        log.debug('Failed to connect to %s too many times. PMS is dead' % url)
        return False

    def GetgPMSKeylist(self):
        """
        Returns a list of all keys that are saved for every entry in the
        g_PMS variable. 
        """
        keylist = [
            'address',
            'baseURL',
            'enableGzip',
            'ip',
            'local',
            'name',
            'owned',
            'port',
            'scheme'
        ]
        return keylist

    def declarePMS(self, uuid, name, scheme, ip, port):
        """
        Plex Media Server handling

        parameters:
            uuid - PMS ID
            name, scheme, ip, port, type, owned, token
        """
        address = ip + ':' + port
        baseURL = scheme + '://' + ip + ':' + port
        self.g_PMS[uuid] = {
            'name': name,
            'scheme': scheme,
            'ip': ip,
            'port': port,
            'address': address,
            'baseURL': baseURL,
            'local': '1',
            'owned': '1',
            'accesstoken': '',
            'enableGzip': False
        }

    def updatePMSProperty(self, uuid, tag, value):
        # set property element of PMS by UUID
        try:
            self.g_PMS[uuid][tag] = value
        except:
            log.error('%s has not yet been declared ' % uuid)
            return False

    def getPMSProperty(self, uuid, tag):
        # get name of PMS by UUID
        try:
            answ = self.g_PMS[uuid].get(tag, '')
        except:
            log.error('%s not found in PMS catalogue' % uuid)
            answ = False
        return answ

    def PlexGDM(self):
        """
        PlexGDM

        parameters:
            none
        result:
            PMS_list - dict() of PMSs found
        """
        import struct

        IP_PlexGDM = '239.0.0.250'  # multicast to PMS
        Port_PlexGDM = 32414
        Msg_PlexGDM = 'M-SEARCH * HTTP/1.0'

        # setup socket for discovery -> multicast message
        GDM = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        GDM.settimeout(2.0)

        # Set the time-to-live for messages to 2 for local network
        ttl = struct.pack('b', 2)
        GDM.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        returnData = []
        try:
            # Send data to the multicast group
            GDM.sendto(Msg_PlexGDM, (IP_PlexGDM, Port_PlexGDM))

            # Look for responses from all recipients
            while True:
                try:
                    data, server = GDM.recvfrom(1024)
                    returnData.append({'from': server,
                                       'data': data})
                except socket.timeout:
                    break
        except Exception as e:
            # Probably error: (101, 'Network is unreachable')
            log.error(e)
            import traceback
            log.error("Traceback:\n%s" % traceback.format_exc())
        finally:
            GDM.close()

        pmsList = {}
        for response in returnData:
            update = {'ip': response.get('from')[0]}
            # Check if we had a positive HTTP response
            if "200 OK" not in response.get('data'):
                continue
            for each in response.get('data').split('\n'):
                # decode response data
                update['discovery'] = "auto"
                # update['owned']='1'
                # update['master']= 1
                # update['role']='master'

                if "Content-Type:" in each:
                    update['content-type'] = each.split(':')[1].strip()
                elif "Resource-Identifier:" in each:
                    update['uuid'] = each.split(':')[1].strip()
                elif "Name:" in each:
                    update['serverName'] = tryDecode(
                        each.split(':')[1].strip())
                elif "Port:" in each:
                    update['port'] = each.split(':')[1].strip()
                elif "Updated-At:" in each:
                    update['updated'] = each.split(':')[1].strip()
                elif "Version:" in each:
                    update['version'] = each.split(':')[1].strip()
            pmsList[update['uuid']] = update
        return pmsList

    def discoverPMS(self, IP_self, plexToken=None):
        """
        parameters:
            IP_self         Own IP
        optional:
            plexToken       token for plex.tv
        result:
            self.g_PMS      dict set
        """
        self.g_PMS = {}

        # Look first for local PMS in the LAN
        pmsList = self.PlexGDM()
        log.debug('PMS found in the local LAN via GDM: %s' % pmsList)

        # Get PMS from plex.tv
        if plexToken:
            log.info('Checking with plex.tv for more PMS to connect to')
            self.getPMSListFromMyPlex(plexToken)
        else:
            log.info('No plex token supplied, only checked LAN for PMS')

        for uuid in pmsList:
            PMS = pmsList[uuid]
            if PMS['uuid'] in self.g_PMS:
                log.debug('We already know of PMS %s from plex.tv'
                          % PMS['serverName'])
                # Update with GDM data - potentially more reliable than plex.tv
                self.updatePMSProperty(PMS['uuid'], 'ip', PMS['ip'])
                self.updatePMSProperty(PMS['uuid'], 'port', PMS['port'])
                self.updatePMSProperty(PMS['uuid'], 'local', '1')
                self.updatePMSProperty(PMS['uuid'], 'scheme', 'http')
                self.updatePMSProperty(PMS['uuid'],
                                       'baseURL',
                                       'http://%s:%s' % (PMS['ip'],
                                                         PMS['port']))
            else:
                self.declarePMS(PMS['uuid'], PMS['serverName'], 'http',
                                PMS['ip'], PMS['port'])
            # Ping to check whether we need HTTPs or HTTP
            https = PMSHttpsEnabled('%s:%s' % (PMS['ip'], PMS['port']))
            if https is None:
                # Error contacting url. Skip for now
                continue
            elif https is True:
                self.updatePMSProperty(PMS['uuid'], 'scheme', 'https')
                self.updatePMSProperty(
                    PMS['uuid'],
                    'baseURL',
                    'https://%s:%s' % (PMS['ip'], PMS['port']))
            else:
                # Already declared with http
                pass

        # install plex.tv "virtual" PMS - for myPlex, PlexHome
        # self.declarePMS('plex.tv', 'plex.tv', 'https', 'plex.tv', '443')
        # self.updatePMSProperty('plex.tv', 'local', '-')
        # self.updatePMSProperty('plex.tv', 'owned', '-')
        # self.updatePMSProperty(
        #     'plex.tv', 'accesstoken', plexToken)
        # (remote and local) servers from plex.tv

    def getPMSListFromMyPlex(self, token):
        """
        getPMSListFromMyPlex

        get Plex media Server List from plex.tv/pms/resources
        """
        xml = self.doUtils('https://plex.tv/api/resources',
                           authenticate=False,
                           parameters={'includeHttps': 1},
                           headerOptions={'X-Plex-Token': token})
        try:
            xml.attrib
        except AttributeError:
            log.error('Could not get list of PMS from plex.tv')
            return

        import Queue
        queue = Queue.Queue()
        threadQueue = []

        maxAgeSeconds = 2*60*60*24
        for Dir in xml.findall('Device'):
            if 'server' not in Dir.get('provides'):
                # No PMS - skip
                continue
            if Dir.find('Connection') is None:
                # no valid connection - skip
                continue

            # check MyPlex data age - skip if >2 days
            PMS = {}
            PMS['name'] = Dir.get('name')
            infoAge = time() - int(Dir.get('lastSeenAt'))
            if infoAge > maxAgeSeconds:
                log.debug("Server %s not seen for 2 days - skipping."
                          % PMS['name'])
                continue

            PMS['uuid'] = Dir.get('clientIdentifier')
            PMS['token'] = Dir.get('accessToken', token)
            PMS['owned'] = Dir.get('owned', '1')
            PMS['local'] = Dir.get('publicAddressMatches')
            PMS['ownername'] = Dir.get('sourceTitle', '')
            PMS['path'] = '/'
            PMS['options'] = None

            # Try a local connection first
            # Backup to remote connection, if that failes
            PMS['connections'] = []
            for Con in Dir.findall('Connection'):
                if Con.get('local') == '1':
                    PMS['connections'].append(Con)
            # Append non-local
            for Con in Dir.findall('Connection'):
                if Con.get('local') != '1':
                    PMS['connections'].append(Con)

            t = Thread(target=self.pokePMS,
                       args=(PMS, queue))
            threadQueue.append(t)

        maxThreads = 5
        threads = []
        # poke PMS, own thread for each PMS
        while True:
            # Remove finished threads
            for t in threads:
                if not t.isAlive():
                    threads.remove(t)
            if len(threads) < maxThreads:
                try:
                    t = threadQueue.pop()
                except IndexError:
                    # We have done our work
                    break
                else:
                    t.start()
                    threads.append(t)
            else:
                sleep(50)

        # wait for requests being answered
        for t in threads:
            t.join()

        # declare new PMSs
        while not queue.empty():
            PMS = queue.get()
            self.declarePMS(PMS['uuid'], PMS['name'],
                            PMS['protocol'], PMS['ip'], PMS['port'])
            self.updatePMSProperty(
                PMS['uuid'], 'accesstoken', PMS['token'])
            self.updatePMSProperty(
                PMS['uuid'], 'owned', PMS['owned'])
            self.updatePMSProperty(
                PMS['uuid'], 'local', PMS['local'])
            # set in declarePMS, overwrite for https encryption
            self.updatePMSProperty(
                PMS['uuid'], 'baseURL', PMS['baseURL'])
            self.updatePMSProperty(
                PMS['uuid'], 'ownername', PMS['ownername'])
            log.debug('Found PMS %s: %s'
                      % (PMS['uuid'], self.g_PMS[PMS['uuid']]))
            queue.task_done()

    def pokePMS(self, PMS, queue):
        data = PMS['connections'][0].attrib
        if data['local'] == '1':
            protocol = data['protocol']
            address = data['address']
            port = data['port']
            url = '%s://%s:%s' % (protocol, address, port)
        else:
            url = data['uri']
            if url.count(':') == 1:
                url = '%s:%s' % (url, data['port'])
            protocol, address, port = url.split(':', 2)
            address = address.replace('/', '')

        xml = self.doUtils('%s/identity' % url,
                           authenticate=False,
                           headerOptions={'X-Plex-Token': PMS['token']},
                           verifySSL=False,
                           timeout=3)
        try:
            xml.attrib['machineIdentifier']
        except (AttributeError, KeyError):
            # No connection, delete the one we just tested
            del PMS['connections'][0]
            if len(PMS['connections']) > 0:
                # Still got connections left, try them
                return self.pokePMS(PMS, queue)
            return
        else:
            # Connection successful - correct PMS?
            if xml.get('machineIdentifier') == PMS['uuid']:
                # process later
                PMS['baseURL'] = url
                PMS['protocol'] = protocol
                PMS['ip'] = address
                PMS['port'] = port
                queue.put(PMS)
                return
        log.info('Found a PMS at %s, but the expected machineIdentifier of '
                 '%s did not match the one we found: %s'
                 % (url, PMS['uuid'], xml.get('machineIdentifier')))

    def MyPlexSignIn(self, username, password, options):
        """
        MyPlex Sign In, Sign Out

        parameters:
            username - Plex forum name, MyPlex login, or email address
            password
            options - dict() of PlexConnect-options as received from aTV - necessary: PlexConnectUDID
        result:
            username
            authtoken - token for subsequent communication with MyPlex
        """
        # MyPlex web address
        MyPlexHost = 'plex.tv'
        MyPlexSignInPath = '/users/sign_in.xml'
        MyPlexURL = 'https://' + MyPlexHost + MyPlexSignInPath

        # create POST request
        xargs = client.getXArgsDeviceInfo(options)
        request = urllib2.Request(MyPlexURL, None, xargs)
        request.get_method = lambda: 'POST'

        passmanager = urllib2.HTTPPasswordMgr()
        passmanager.add_password(MyPlexHost, MyPlexURL, username, password)
        authhandler = urllib2.HTTPBasicAuthHandler(passmanager)
        urlopener = urllib2.build_opener(authhandler)

        # sign in, get MyPlex response
        try:
            response = urlopener.open(request).read()
        except urllib2.HTTPError as e:
            if e.code == 401:
                log.info("Authentication failed")
                return ('', '')
            else:
                raise
        # analyse response
        XMLTree = etree.ElementTree(etree.fromstring(response))

        el_username = XMLTree.find('username')
        el_authtoken = XMLTree.find('authentication-token')
        if el_username is None or \
           el_authtoken is None:
            username = ''
            authtoken = ''
        else:
            username = el_username.text
            authtoken = el_authtoken.text
        return (username, authtoken)

    def MyPlexSignOut(self, authtoken):
        """
        TO BE DONE!
        """
        # MyPlex web address
        MyPlexHost = 'plex.tv'
        MyPlexSignOutPath = '/users/sign_out.xml'
        MyPlexURL = 'http://' + MyPlexHost + MyPlexSignOutPath

        # create POST request
        xargs = {'X-Plex-Token': authtoken}
        request = urllib2.Request(MyPlexURL, None, xargs)
        # turn into 'POST' - done automatically with data!=None. But we don't
        # have data.
        request.get_method = lambda: 'POST'

        response = urllib2.urlopen(request).read()

    def GetUserArtworkURL(self, username):
        """
        Returns the URL for the user's Avatar. Or False if something went
        wrong.
        """
        plexToken = settings('plexToken')
        users = self.MyPlexListHomeUsers(plexToken)
        url = ''
        # If an error is encountered, set to False
        if not users:
            log.info("Couldnt get user from plex.tv. No URL for user avatar")
            return False
        for user in users:
            if username in user['title']:
                url = user['thumb']
        log.debug("Avatar url for user %s is: %s" % (username, url))
        return url

    def ChoosePlexHomeUser(self, plexToken):
        """
        Let's user choose from a list of Plex home users. Will switch to that
        user accordingly.

        Returns a dict:
        {
            'username':             Unicode
            'userid': ''            Plex ID of the user
            'token': ''             User's token
            'protected':            True if PIN is needed, else False
        }

        Will return False if something went wrong (wrong PIN, no connection)
        """
        dialog = xbmcgui.Dialog()

        # Get list of Plex home users
        users = self.MyPlexListHomeUsers(plexToken)
        if not users:
            log.error("User download failed.")
            return False

        userlist = []
        userlistCoded = []
        for user in users:
            username = user['title']
            userlist.append(username)
            # To take care of non-ASCII usernames
            userlistCoded.append(tryEncode(username))
        usernumber = len(userlist)

        username = ''
        usertoken = ''
        trials = 0
        while trials < 3:
            if usernumber > 1:
                # Select user
                user_select = dialog.select(
                    lang(29999) + lang(39306),
                    userlistCoded)
                if user_select == -1:
                    log.info("No user selected.")
                    settings('username', value='')
                    executebuiltin('Addon.OpenSettings(%s)'
                                   % v.ADDON_ID)
                    return False
            # Only 1 user received, choose that one
            else:
                user_select = 0
            selected_user = userlist[user_select]
            log.info("Selected user: %s" % selected_user)
            user = users[user_select]
            # Ask for PIN, if protected:
            pin = None
            if user['protected'] == '1':
                log.debug('Asking for users PIN')
                pin = dialog.input(
                    lang(39307) + selected_user,
                    '',
                    xbmcgui.INPUT_NUMERIC,
                    xbmcgui.ALPHANUM_HIDE_INPUT)
                # User chose to cancel
                # Plex bug: don't call url for protected user with empty PIN
                if not pin:
                    trials += 1
                    continue
            # Switch to this Plex Home user, if applicable
            result = self.PlexSwitchHomeUser(
                user['id'],
                pin,
                plexToken,
                settings('plex_machineIdentifier'))
            if result:
                # Successfully retrieved username: break out of while loop
                username = result['username']
                usertoken = result['usertoken']
                break
            # Couldn't get user auth
            else:
                trials += 1
                # Could not login user, please try again
                if not dialog.yesno(lang(29999),
                                    lang(39308) + selected_user,
                                    lang(39309)):
                    # User chose to cancel
                    break
        if not username:
            log.error('Failed signing in a user to plex.tv')
            executebuiltin('Addon.OpenSettings(%s)' % v.ADDON_ID)
            return False
        return {
            'username': username,
            'userid': user['id'],
            'protected': True if user['protected'] == '1' else False,
            'token': usertoken
        }

    def PlexSwitchHomeUser(self, userId, pin, token, machineIdentifier):
        """
        Retrieves Plex home token for a Plex home user.
        Returns False if unsuccessful

        Input:
            userId          id of the Plex home user
            pin             PIN of the Plex home user, if protected
            token           token for plex.tv

        Output:
            {
                'username'
                'usertoken'         Might be empty strings if no token found
                                    for the machineIdentifier that was chosen
            }

        settings('userid') and settings('username') with new plex token
        """
        log.info('Switching to user %s' % userId)
        url = 'https://plex.tv/api/home/users/' + userId + '/switch'
        if pin:
            url += '?pin=' + pin
        answer = self.doUtils(url,
                              authenticate=False,
                              action_type="POST",
                              headerOptions={'X-Plex-Token': token})
        try:
            answer.attrib
        except:
            log.error('Error: plex.tv switch HomeUser change failed')
            return False

        username = answer.attrib.get('title', '')
        token = answer.attrib.get('authenticationToken', '')

        # Write to settings file
        settings('username', username)
        settings('accessToken', token)
        settings('userid', answer.attrib.get('id', ''))
        settings('plex_restricteduser',
                 'true' if answer.attrib.get('restricted', '0') == '1'
                 else 'false')

        # Get final token to the PMS we've chosen
        url = 'https://plex.tv/api/resources?includeHttps=1'
        xml = self.doUtils(url,
                           authenticate=False,
                           headerOptions={'X-Plex-Token': token})
        try:
            xml.attrib
        except:
            log.error('Answer from plex.tv not as excepted')
            # Set to empty iterable list for loop
            xml = []

        found = 0
        log.debug('Our machineIdentifier is %s' % machineIdentifier)
        for device in xml:
            identifier = device.attrib.get('clientIdentifier')
            log.debug('Found a Plex machineIdentifier: %s' % identifier)
            if (identifier in machineIdentifier or
                    machineIdentifier in identifier):
                found += 1
                token = device.attrib.get('accessToken')

        result = {
            'username': username,
        }
        if found == 0:
            log.info('No tokens found for your server! Using empty string')
            result['usertoken'] = ''
        else:
            result['usertoken'] = token
        log.info('Plex.tv switch HomeUser change successfull for user %s'
                 % username)
        return result

    def MyPlexListHomeUsers(self, token):
        """
        Returns a list for myPlex home users for the current plex.tv account.

        Input:
            token for plex.tv
        Output:
            List of users, where one entry is of the form:
                "id": userId,
                "admin": '1'/'0',
                "guest": '1'/'0',
                "restricted": '1'/'0',
                "protected": '1'/'0',
                "email": email,
                "title": title,
                "username": username,
                "thumb": thumb_url
            }
        If any value is missing, None is returned instead (or "" from plex.tv)
        If an error is encountered, False is returned
        """
        xml = self.doUtils('https://plex.tv/api/home/users/',
                           authenticate=False,
                           headerOptions={'X-Plex-Token': token})
        try:
            xml.attrib
        except:
            log.error('Download of Plex home users failed.')
            return False
        users = []
        for user in xml:
            users.append(user.attrib)
        return users

    def getDirectVideoPath(self, key, AuthToken):
        """
        Direct Video Play support

        parameters:
            path
            AuthToken
            Indirect - media indirect specified, grab child XML to gain real path
            options
        result:
            final path to media file
        """
        if key.startswith('http://') or key.startswith('https://'):  # external address - keep
            path = key
        else:
            if AuthToken == '':
                path = key
            else:
                xargs = dict()
                xargs['X-Plex-Token'] = AuthToken
                if key.find('?') == -1:
                    path = key + '?' + urlencode(xargs)
                else:
                    path = key + '&' + urlencode(xargs)

        return path

    def getTranscodeImagePath(self, key, AuthToken, path, width, height):
        """
        Transcode Image support

        parameters:
            key
            AuthToken
            path - source path of current XML: path[srcXML]
            width
            height
        result:
            final path to image file
        """
        if key.startswith('http://') or key.startswith('https://'):  # external address - can we get a transcoding request for external images?
            path = key
        elif key.startswith('/'):  # internal full path.
            path = 'http://127.0.0.1:32400' + key
        else:  # internal path, add-on
            path = 'http://127.0.0.1:32400' + path + '/' + key
        path = tryEncode(path)

        # This is bogus (note the extra path component) but ATV is stupid when it comes to caching images, it doesn't use querystrings.
        # Fortunately PMS is lenient...
        transcodePath = '/photo/:/transcode/' + \
            str(width) + 'x' + str(height) + '/' + quote_plus(path)

        args = dict()
        args['width'] = width
        args['height'] = height
        args['url'] = path

        if not AuthToken == '':
            args['X-Plex-Token'] = AuthToken

        return transcodePath + '?' + urlencode(args)

    def getDirectImagePath(self, path, AuthToken):
        """
        Direct Image support

        parameters:
            path
            AuthToken
        result:
            final path to image file
        """
        if not AuthToken == '':
            xargs = dict()
            xargs['X-Plex-Token'] = AuthToken
            if path.find('?') == -1:
                path = path + '?' + urlencode(xargs)
            else:
                path = path + '&' + urlencode(xargs)

        return path

    def getTranscodeAudioPath(self, path, AuthToken, options, maxAudioBitrate):
        """
        Transcode Audio support

        parameters:
            path
            AuthToken
            options - dict() of PlexConnect-options as received from aTV
            maxAudioBitrate - [kbps]
        result:
            final path to pull in PMS transcoder
        """
        UDID = options['PlexConnectUDID']

        transcodePath = '/music/:/transcode/universal/start.mp3?'

        args = dict()
        args['path'] = path
        args['session'] = UDID
        args['protocol'] = 'http'
        args['maxAudioBitrate'] = maxAudioBitrate

        xargs = client.getXArgsDeviceInfo(options)
        if not AuthToken == '':
            xargs['X-Plex-Token'] = AuthToken

        return transcodePath + urlencode(args) + '&' + urlencode(xargs)

    def getDirectAudioPath(self, path, AuthToken):
        """
        Direct Audio support

        parameters:
            path
            AuthToken
        result:
            final path to audio file
        """
        if not AuthToken == '':
            xargs = dict()
            xargs['X-Plex-Token'] = AuthToken
            if path.find('?') == -1:
                path = path + '?' + urlencode(xargs)
            else:
                path = path + '&' + urlencode(xargs)

        return path

    def returnServerList(self, data):
        """
        Returns a nicer list of all servers found in data, where data is in
        g_PMS format, for the client device with unique ID ATV_udid

        Input:
            data                    e.g. self.g_PMS

        Output: List of all servers, with an entry of the form:
        {
        'name': friendlyName,      the Plex server's name
        'address': ip:port
        'ip': ip,                   without http/https
        'port': port
        'scheme': 'http'/'https',   nice for checking for secure connections
        'local': '1'/'0',           Is the server a local server?
        'owned': '1'/'0',           Is the server owned by the user?
        'machineIdentifier': id,    Plex server machine identifier
        'accesstoken': token        Access token to this server
        'baseURL': baseURL          scheme://ip:port
        'ownername'                 Plex username of PMS owner
        }
        """
        serverlist = []
        for key, value in data.items():
            serverlist.append({
                'name': value.get('name'),
                'address': value.get('address'),
                'ip': value.get('ip'),
                'port': value.get('port'),
                'scheme': value.get('scheme'),
                'local': value.get('local'),
                'owned': value.get('owned'),
                'machineIdentifier': key,
                'accesstoken': value.get('accesstoken'),
                'baseURL': value.get('baseURL'),
                'ownername': value.get('ownername')
            })
        return serverlist


class API():
    """
    API(item)

    Processes a Plex media server's XML response

    item: xml.etree.ElementTree element
    """

    def __init__(self, item):
        self.item = item
        # which media part in the XML response shall we look at?
        self.part = 0
        self.mediastream = None
        self.server = window('pms_server')

    def setPartNumber(self, number=None):
        """
        Sets the part number to work with (used to deal with Movie with several
        parts).
        """
        self.part = number or 0

    def getPartNumber(self):
        """
        Returns the current media part number we're dealing with.
        """
        return self.part

    def getType(self):
        """
        Returns the type of media, e.g. 'movie' or 'clip' for trailers
        """
        return self.item.attrib.get('type')

    def getChecksum(self):
        """
        Returns a string, not int. 

        WATCH OUT - time in Plex, not Kodi ;-)
        """
        # Include a letter to prohibit saving as an int!
        checksum = "K%s%s" % (self.getRatingKey(),
                              self.item.attrib.get('updatedAt', ''))
        return checksum

    def getRatingKey(self):
        """
        Returns the Plex key such as '246922' as a string
        """
        return self.item.attrib.get('ratingKey')

    def getKey(self):
        """
        Returns the Plex key such as '/library/metadata/246922'
        """
        return self.item.attrib.get('key')

    def getFilePath(self, forceFirstMediaStream=False):
        """
        Returns the direct path to this item, e.g. '\\NAS\movies\movie.mkv'
        or None

        forceFirstMediaStream=True:
            will always use 1st media stream, e.g. when several different
            files are present for the same PMS item
        """
        if self.mediastream is None and forceFirstMediaStream is False:
            self.getMediastreamNumber()
        try:
            if forceFirstMediaStream is False:
                ans = self.item[self.mediastream][self.part].attrib['file']
            else:
                ans = self.item[0][self.part].attrib['file']
        except:
            ans = None
        if ans is not None:
            try:
                ans = tryDecode(unquote(ans))
            except UnicodeDecodeError:
                # Sometimes, Plex seems to have encoded in latin1
                ans = unquote(ans).decode('latin1')
        return ans

    def get_picture_path(self):
        """
        Returns the item's picture path (transcode, if necessary) as string.
        Will always use addon paths, never direct paths
        """
        extension = self.item[0][0].attrib['key'][self.item[0][0].attrib['key'].rfind('.'):].lower()
        if (window('plex_force_transcode_pix') == 'true' or
                extension not in v.KODI_SUPPORTED_IMAGES):
            # Let Plex transcode
            # max width/height supported by plex image transcoder is 1920x1080
            path = self.server + PlexAPI().getTranscodeImagePath(
                self.item[0][0].attrib.get('key'),
                window('pms_token'),
                "%s%s" % (self.server, self.item[0][0].attrib.get('key')),
                1920,
                1080)
        else:
            path = self.addPlexCredentialsToUrl(
                '%s%s' % (window('pms_server'),
                          self.item[0][0].attrib['key']))
        # Attach Plex id to url to let it be picked up by our playqueue agent
        # later
        return tryEncode('%s&plex_id=%s' % (path, self.getRatingKey()))

    def getTVShowPath(self):
        """
        Returns the direct path to the TV show, e.g. '\\NAS\tv\series'
        or None
        """
        res = None
        for child in self.item:
            if child.tag == 'Location':
                res = child.attrib.get('path')
        return res

    def getIndex(self):
        """
        Returns the 'index' of an PMS XML reply. Depicts e.g. season number.
        """
        return self.item.attrib.get('index')

    def getDateCreated(self):
        """
        Returns the date when this library item was created.

        If not found, returns 2000-01-01 10:00:00
        """
        res = self.item.attrib.get('addedAt')
        if res is not None:
            res = DateToKodi(res)
        else:
            res = '2000-01-01 10:00:00'
        return res

    def getUserData(self):
        """
        Returns a dict with None if a value is missing
        {
            'Favorite': favorite,                  # False, because n/a in Plex
            'PlayCount': playcount,
            'Played': played,                      # True/False
            'LastPlayedDate': lastPlayedDate,
            'Resume': resume,                      # Resume time in seconds
            'Runtime': runtime,
            'Rating': rating
        }
        """
        item = self.item.attrib
        # Default - attributes not found with Plex
        favorite = False
        try:
            playcount = int(item['viewCount'])
        except (KeyError, ValueError):
            playcount = None
        played = True if playcount else False

        try:
            lastPlayedDate = DateToKodi(int(item['lastViewedAt']))
        except (KeyError, ValueError):
            lastPlayedDate = None

        try:
            userrating = int(float(item['userRating']))
        except (KeyError, ValueError):
            userrating = 0

        try:
            rating = float(item['audienceRating'])
        except (KeyError, ValueError):
            try:
                rating = float(item['rating'])
            except (KeyError, ValueError):
                rating = 0.0

        resume, runtime = self.getRuntime()
        return {
            'Favorite': favorite,
            'PlayCount': playcount,
            'Played': played,
            'LastPlayedDate': lastPlayedDate,
            'Resume': resume,
            'Runtime': runtime,
            'Rating': rating,
            'UserRating': userrating
        }

    def getCollections(self):
        """
        Returns a list of PMS collection tags or an empty list
        """
        collections = []
        for child in self.item:
            if child.tag == 'Collection':
                if child.attrib['tag']:
                    collections.append(child.attrib['tag'])
        return collections

    def getPeople(self):
        """
        Returns a dict of lists of people found.
        {
            'Director': list,
            'Writer': list,
            'Cast': list,
            'Producer': list
        }
        """
        director = []
        writer = []
        cast = []
        producer = []
        for child in self.item:
            if child.tag == 'Director':
                director.append(child.attrib['tag'])
            elif child.tag == 'Writer':
                writer.append(child.attrib['tag'])
            elif child.tag == 'Role':
                cast.append(child.attrib['tag'])
            elif child.tag == 'Producer':
                producer.append(child.attrib['tag'])
        return {
            'Director': director,
            'Writer': writer,
            'Cast': cast,
            'Producer': producer
        }

    def getPeopleList(self):
        """
        Returns a list of people from item, with a list item of the form
        {
            'Name': xxx,
            'Type': xxx,
            'Id': xxx
            'imageurl': url to picture, None otherwise
            ('Role': xxx for cast/actors only, None if not found)
        }
        """
        people = []
        # Key of library: Plex-identifier. Value represents the Kodi/emby side
        people_of_interest = {
            'Director': 'Director',
            'Writer': 'Writer',
            'Role': 'Actor',
            'Producer': 'Producer'
        }
        for child in self.item:
            if child.tag in people_of_interest.keys():
                name = child.attrib['tag']
                name_id = child.attrib['id']
                Type = child.tag
                Type = people_of_interest[Type]

                url = child.attrib.get('thumb')
                Role = child.attrib.get('role')

                people.append({
                    'Name': name,
                    'Type': Type,
                    'Id': name_id,
                    'imageurl': url
                })
                if url:
                    people[-1].update({'imageurl': url})
                if Role:
                    people[-1].update({'Role': Role})
        return people

    def getGenres(self):
        """
        Returns a list of genres found. (Not a string)
        """
        genre = []
        for child in self.item:
            if child.tag == 'Genre':
                genre.append(child.attrib['tag'])
        return genre

    def getGuid(self):
        return self.item.attrib.get('guid')

    def getProvider(self, providername=None):
        """
        providername:  e.g. 'imdb', 'tvdb'

        Return IMDB, e.g. "tt0903624". Returns None if not found
        """
        item = self.item.attrib
        try:
            item = item['guid']
        except KeyError:
            return None

        if providername == 'imdb':
            regex = REGEX_IMDB
        elif providername == 'tvdb':
            # originally e.g. com.plexapp.agents.thetvdb://276564?lang=en
            regex = REGEX_TVDB
        else:
            return None

        provider = regex.findall(item)
        try:
            provider = provider[0]
        except IndexError:
            provider = None
        return provider

    def getTitle(self):
        """
        Returns an item's name/title or "Missing Title Name".
        Output:
            title, sorttitle

        sorttitle = title, if no sorttitle is found
        """
        title = self.item.attrib.get('title', 'Missing Title Name')
        sorttitle = self.item.attrib.get('titleSort', title)
        return title, sorttitle

    def getPlot(self):
        """
        Returns the plot or None.
        """
        return self.item.attrib.get('summary', None)

    def getTagline(self):
        """
        Returns a shorter tagline or None
        """
        return self.item.attrib.get('tagline', None)

    def getAudienceRating(self):
        """
        Returns the audience rating, 'rating' itself or 0.0
        """
        res = self.item.attrib.get('audienceRating')
        if res is None:
            res = self.item.attrib.get('rating')
        try:
            res = float(res)
        except (ValueError, TypeError):
            res = 0.0
        return res

    def getYear(self):
        """
        Returns the production(?) year ("year") or None
        """
        return self.item.attrib.get('year', None)

    def getRuntime(self):
        """
        Resume point of time and runtime/totaltime in rounded to seconds.
        Time from Plex server is measured in milliseconds.
        Kodi: seconds

        Output:
            resume, runtime         as ints. 0 if not found
        """
        item = self.item.attrib

        try:
            runtime = float(item['duration'])
        except (KeyError, ValueError):
            runtime = 0.0
        try:
            resume = float(item['viewOffset'])
        except (KeyError, ValueError):
            resume = 0.0

        runtime = int(runtime * v.PLEX_TO_KODI_TIMEFACTOR)
        resume = int(resume * v.PLEX_TO_KODI_TIMEFACTOR)
        return resume, runtime

    def getMpaa(self):
        """
        Get the content rating or None
        """
        mpaa = self.item.attrib.get('contentRating', None)
        # Convert more complex cases
        if mpaa in ("NR", "UR"):
            # Kodi seems to not like NR, but will accept Rated Not Rated
            mpaa = "Rated Not Rated"
        return mpaa

    def getCountry(self):
        """
        Returns a list of all countries found in item.
        """
        country = []
        for child in self.item:
            if child.tag == 'Country':
                country.append(child.attrib['tag'])
        return country

    def getPremiereDate(self):
        """
        Returns the "originallyAvailableAt" or None
        """
        return self.item.attrib.get('originallyAvailableAt')

    def getMusicStudio(self):
        return self.item.attrib.get('studio', '')

    def getStudios(self):
        """
        Returns a list with a single entry for the studio, or an empty list
        """
        studio = []
        try:
            studio.append(self.getStudio(self.item.attrib['studio']))
        except KeyError:
            pass
        return studio

    def getStudio(self, studioName):
        """
        Convert studio for Kodi to properly detect them
        """
        studios = {
            'abc (us)': "ABC",
            'fox (us)': "FOX",
            'mtv (us)': "MTV",
            'showcase (ca)': "Showcase",
            'wgn america': "WGN"
        }
        return studios.get(studioName.lower(), studioName)

    def joinList(self, listobject):
        """
        Smart-joins the listobject into a single string using a " / "
        separator.
        If the list is empty, smart_join returns an empty string.
        """
        string = " / ".join(listobject)
        return string

    def getParentRatingKey(self):
        return self.item.attrib.get('parentRatingKey', '')

    def getEpisodeDetails(self):
        """
        Call on a single episode.

        Output: for the corresponding the TV show and season:
            [
                TV show key,        Plex: 'grandparentRatingKey'
                TV show title,      Plex: 'grandparentTitle'
                TV show season,     Plex: 'parentIndex'
                Episode number,     Plex: 'index'
            ]
        """
        item = self.item.attrib
        key = item.get('grandparentRatingKey')
        title = item.get('grandparentTitle')
        season = item.get('parentIndex')
        episode = item.get('index')
        return key, title, season, episode

    def addPlexHeadersToUrl(self, url, arguments={}):
        """
        Takes an URL and optional arguments (also to be URL-encoded); returns
        an extended URL with e.g. the Plex token included.

        arguments overrule everything
        """
        xargs = client.getXArgsDeviceInfo()
        xargs.update(arguments)
        if '?' not in url:
            url = "%s?%s" % (url, urlencode(xargs))
        else:
            url = "%s&%s" % (url, urlencode(xargs))
        return url

    def addPlexCredentialsToUrl(self, url):
        """
        Returns an extended URL with the Plex token included as 'X-Plex-Token='

        url may or may not already contain a '?'
        """
        if window('pms_token') == '':
            return url
        if '?' not in url:
            url = "%s?X-Plex-Token=%s" % (url, window('pms_token'))
        else:
            url = "%s&X-Plex-Token=%s" % (url, window('pms_token'))
        return url

    def GetPlayQueueItemID(self):
        """
        Returns current playQueueItemID for the item.

        If not found, empty str is returned
        """
        return self.item.attrib.get('playQueueItemID')

    def getDataFromPartOrMedia(self, key):
        """
        Retrieves XML data 'key' first from the active part. If unsuccessful,
        tries to retrieve the data from the Media response part.

        If all fails, None is returned.
        """
        media = self.item[0].attrib
        part = self.item[0][self.part].attrib

        try:
            try:
                value = part[key]
            except KeyError:
                value = media[key]
        except KeyError:
            value = None
        return value

    def getVideoCodec(self):
        """
        Returns the video codec and resolution for the child and part selected.
        If any data is not found on a part-level, the Media-level data is
        returned.
        If that also fails (e.g. for old trailers, None is returned)

        Output:
            {
                'videocodec': xxx,       e.g. 'h264'
                'resolution': xxx,       e.g. '720' or '1080'
                'height': xxx,           e.g. '816'
                'width': xxx,            e.g. '1920'
                'aspectratio': xxx,      e.g. '1.78'
                'bitrate': xxx,          e.g. '10642'
                'container': xxx         e.g. 'mkv',
                'bitDepth': xxx          e.g. '8', '10'
            }
        """
        answ = {
            'videocodec': self.getDataFromPartOrMedia('videoCodec'),
            'resolution': self.getDataFromPartOrMedia('videoResolution'),
            'height': self.getDataFromPartOrMedia('height'),
            'width': self.getDataFromPartOrMedia('width'),
            'aspectratio': self.getDataFromPartOrMedia('aspectratio'),
            'bitrate': self.getDataFromPartOrMedia('bitrate'),
            'container': self.getDataFromPartOrMedia('container'),
        }
        try:
            answ['bitDepth'] = self.item[0][self.part][self.mediastream].attrib.get('bitDepth')
        except:
            answ['bitDepth'] = None
        return answ

    def getExtras(self):
        """
        Currently ONLY returns the very first trailer found!

        Returns a list of trailer and extras from PMS XML. Returns [] if
        no extras are found.
        Extratypes:
            1:    Trailer
            5:    Behind the scenes

        Output: list of dicts with one entry of the form:
            'key':                     e.g. /library/metadata/xxxx
            'title':
            'thumb':                    artwork
            'duration':
            'extraType':
            'originallyAvailableAt':
            'year':
        """
        elements = []
        extras = self.item.find('Extras')
        if extras is None:
            return elements
        for extra in extras:
            try:
                extraType = int(extra.attrib['extraType'])
            except:
                extraType = None
            if extraType != 1:
                continue
            key = extra.attrib.get('key', None)
            title = extra.attrib.get('title', None)
            thumb = extra.attrib.get('thumb', None)
            duration = float(extra.attrib.get('duration', 0.0))
            year = extra.attrib.get('year', None)
            originallyAvailableAt = extra.attrib.get(
                'originallyAvailableAt', None)
            elements.append(
                {
                    'key': key,
                    'title': title,
                    'thumb': thumb,
                    'duration': int(duration * v.PLEX_TO_KODI_TIMEFACTOR),
                    'extraType': extraType,
                    'originallyAvailableAt': originallyAvailableAt,
                    'year': year
                })
            break
        return elements

    def getMediaStreams(self):
        """
        Returns the media streams for metadata purposes

        Output: each track contains a dictionaries
        {
            'video': videotrack-list,       'codec', 'height', 'width',
                                            'aspect', 'video3DFormat'
            'audio': audiotrack-list,       'codec', 'channels',
                                            'language'
            'subtitle': list of subtitle languages (or "Unknown")
        }
        """
        videotracks = []
        audiotracks = []
        subtitlelanguages = []
        # Sometimes, aspectratio is on the "toplevel"
        aspectratio = self.item[0].attrib.get('aspectRatio', None)
        # TODO: what if several Media tags exist?!?
        # Loop over parts
        for child in self.item[0]:
            container = child.attrib.get('container', None)
            # Loop over Streams
            for grandchild in child:
                mediaStream = grandchild.attrib
                mediaType = int(mediaStream.get('streamType', 999))
                if mediaType == 1:  # Video streams
                    videotrack = {}
                    videotrack['codec'] = mediaStream['codec'].lower()
                    if "msmpeg4" in videotrack['codec']:
                        videotrack['codec'] = "divx"
                    elif "mpeg4" in videotrack['codec']:
                        # if "simple profile" in profile or profile == "":
                        #    videotrack['codec'] = "xvid"
                        pass
                    elif "h264" in videotrack['codec']:
                        if container in ("mp4", "mov", "m4v"):
                            videotrack['codec'] = "avc1"
                    videotrack['height'] = mediaStream.get('height', None)
                    videotrack['width'] = mediaStream.get('width', None)
                    # TODO: 3d Movies?!?
                    # videotrack['Video3DFormat'] = item.get('Video3DFormat')
                    aspectratio = mediaStream.get('aspectRatio', aspectratio)
                    videotrack['aspect'] = aspectratio
                    # TODO: Video 3d format
                    videotrack['video3DFormat'] = None
                    videotracks.append(videotrack)

                elif mediaType == 2:  # Audio streams
                    audiotrack = {}
                    audiotrack['codec'] = mediaStream['codec'].lower()
                    if ("dca" in audiotrack['codec'] and
                            "ma" in mediaStream.get('profile', '').lower()):
                        audiotrack['codec'] = "dtshd_ma"
                    audiotrack['channels'] = mediaStream.get('channels')
                    # 'unknown' if we cannot get language
                    audiotrack['language'] = mediaStream.get(
                        'languageCode', lang(39310)).lower()
                    audiotracks.append(audiotrack)

                elif mediaType == 3:  # Subtitle streams
                    # 'unknown' if we cannot get language
                    subtitlelanguages.append(
                        mediaStream.get('languageCode',
                                        lang(39310)).lower())
        return {
            'video': videotracks,
            'audio': audiotracks,
            'subtitle': subtitlelanguages
        }

    def __getOneArtwork(self, entry):
        try:
            artwork = self.item.attrib[entry]
            if artwork.startswith('http'):
                pass
            else:
                artwork = "%s%s" % (self.server, artwork)
                artwork = self.addPlexCredentialsToUrl(artwork)
        except KeyError:
            artwork = ""
        return artwork

    def getAllArtwork(self, parentInfo=False):
        """
        Gets the URLs to the Plex artwork, or empty string if not found.
        parentInfo=True will check for parent's artwork if None is found

        Output:
        {
            'Primary'
            'Art'
            'Banner'
            'Logo'
            'Thumb'
            'Disc'
            'Backdrop' : LIST with the first entry xml key "art"
        }
        """
        allartworks = {
            'Primary': "",  # corresponds to Plex poster ('thumb')
            'Art': "",
            'Banner': "",   # corresponds to Plex banner ('banner') for series
            'Logo': "",
            'Thumb': "",    # corresponds to Plex (grand)parent posters (thumb)
            'Disc': "",
            'Backdrop': []  # Corresponds to Plex fanart ('art')
        }
        # Process backdrops
        # Get background artwork URL
        allartworks['Backdrop'].append(self.__getOneArtwork('art'))
        # Get primary "thumb" pictures:
        allartworks['Primary'] = self.__getOneArtwork('thumb')
        # Banner (usually only on tv series level)
        allartworks['Banner'] = self.__getOneArtwork('banner')
        # For e.g. TV shows, get series thumb
        allartworks['Thumb'] = self.__getOneArtwork('grandparentThumb')

        # Process parent items if the main item is missing artwork
        if parentInfo:
            # Process parent backdrops
            if not allartworks['Backdrop']:
                allartworks['Backdrop'].append(
                    self.__getOneArtwork('parentArt'))
            if not allartworks['Primary']:
                allartworks['Primary'] = self.__getOneArtwork('parentThumb')
        return allartworks

    def getFanartArtwork(self, allartworks, parentInfo=False):
        """
        Downloads additional fanart from third party sources (well, link to
        fanart only).

        allartworks = {
            'Primary': "",
            'Art': "",
            'Banner': "",
            'Logo': "",
            'Thumb': "",
            'Disc': "",
            'Backdrop': []
        }
        """
        externalId = self.getExternalItemId()
        if externalId is not None:
            allartworks = self.getFanartTVArt(externalId, allartworks)
        return allartworks

    def getExternalItemId(self, collection=False):
        """
        Returns the item's IMDB id for movies or tvdb id for TV shows

        If not found in item's Plex metadata, check themovidedb.org

        collection=True will try to return the collection's ID

        None is returned if unsuccessful
        """
        item = self.item.attrib
        media_type = item.get('type')
        mediaId = None
        # Return the saved Plex id's, if applicable
        # Always seek collection's ids since not provided by PMS
        if collection is False:
            if media_type == v.PLEX_TYPE_MOVIE:
                mediaId = self.getProvider('imdb')
            elif media_type == v.PLEX_TYPE_SHOW:
                mediaId = self.getProvider('tvdb')
            if mediaId is not None:
                return mediaId
            log.info('Plex did not provide ID for IMDB or TVDB. Start '
                     'lookup process')
        else:
            log.info('Start movie set/collection lookup on themoviedb')

        apiKey = settings('themoviedbAPIKey')
        if media_type == v.PLEX_TYPE_SHOW:
            media_type = 'tv'
        title = item.get('title', '')
        # if the title has the year in remove it as tmdb cannot deal with it...
        # replace e.g. 'The Americans (2015)' with 'The Americans'
        title = sub(r'\s*\(\d{4}\)$', '', title, count=1)
        url = 'http://api.themoviedb.org/3/search/%s' % media_type
        parameters = {
            'api_key': apiKey,
            'language': v.KODILANGUAGE,
            'query': tryEncode(title)
        }
        data = DownloadUtils().downloadUrl(
            url,
            authenticate=False,
            parameters=parameters,
            timeout=7)
        try:
            data.get('test')
        except:
            log.error('Could not download data from FanartTV')
            return
        if data.get('results') is None:
            log.info('No match found on themoviedb for type: %s, title: %s'
                     % (media_type, title))
            return

        year = item.get('year')
        matchFound = None
        # find year match
        if year is not None:
            for entry in data["results"]:
                if year in entry.get("first_air_date", ""):
                    matchFound = entry
                    break
                elif year in entry.get("release_date", ""):
                    matchFound = entry
                    break
        # find exact match based on title, if we haven't found a year match
        if matchFound is None:
            log.info('No themoviedb match found using year %s' % year)
            replacements = (
                ' ',
                '-',
                '&',
                ',',
                ':',
                ';'
            )
            for entry in data["results"]:
                name = entry.get("name", entry.get("title", ""))
                original_name = entry.get("original_name", "")
                title_alt = title.lower()
                name_alt = name.lower()
                org_name_alt = original_name.lower()
                for replaceString in replacements:
                    title_alt = title_alt.replace(replaceString, '')
                    name_alt = name_alt.replace(replaceString, '')
                    org_name_alt = org_name_alt.replace(replaceString, '')
                if name == title or original_name == title:
                    # match found for exact title name
                    matchFound = entry
                    break
                elif (name.split(" (")[0] == title or title_alt == name_alt
                        or title_alt == org_name_alt):
                    # match found with substituting some stuff
                    matchFound = entry
                    break

        # if a match was not found, we accept the closest match from TMDB
        if matchFound is None and len(data.get("results")) > 0:
            log.info('Using very first match from themoviedb')
            matchFound = entry = data.get("results")[0]

        if matchFound is None:
            log.info('Still no themoviedb match for type: %s, title: %s, '
                     'year: %s' % (media_type, title, year))
            log.debug('themoviedb answer was %s' % data['results'])
            return

        log.info('Found themoviedb match for %s: %s'
                 % (item.get('title'), matchFound))

        tmdbId = str(entry.get("id", ""))
        if tmdbId == '':
            log.error('No themoviedb ID found, aborting')
            return

        if media_type == "multi" and entry.get("media_type"):
            media_type = entry.get("media_type")
        name = entry.get("name", entry.get("title"))
        # lookup external tmdbId and perform artwork lookup on fanart.tv
        parameters = {
            'api_key': apiKey
        }
        for language in [v.KODILANGUAGE, "en"]:
            parameters['language'] = language
            if media_type == "movie":
                url = 'http://api.themoviedb.org/3/movie/%s' % tmdbId
                parameters['append_to_response'] = 'videos'
            elif media_type == "tv":
                url = 'http://api.themoviedb.org/3/tv/%s' % tmdbId
                parameters['append_to_response'] = 'external_ids,videos'
            data = DownloadUtils().downloadUrl(
                url,
                authenticate=False,
                parameters=parameters,
                timeout=7)
            try:
                data.get('test')
            except:
                log.error('Could not download %s with parameters %s'
                          % (url, parameters))
                continue
            if collection is False:
                if data.get("imdb_id") is not None:
                    mediaId = str(data.get("imdb_id"))
                    break
                if data.get("external_ids") is not None:
                    mediaId = str(data["external_ids"].get("tvdb_id"))
                    break
            else:
                if data.get("belongs_to_collection") is not None:
                    mediaId = str(data.get("belongs_to_collection").get("id"))
                    log.debug('Retrieved collections tmdb id %s' % mediaId)
        return mediaId

    def getFanartTVArt(self, mediaId, allartworks, setInfo=False):
        """
        perform artwork lookup on fanart.tv

        mediaId: IMDB id for movies, tvdb id for TV shows
        """
        item = self.item.attrib
        api_key = settings('FanArtTVAPIKey')
        typus = item.get('type')
        if typus == 'show':
            typus = 'tv'

        if typus == "movie":
            url = 'http://webservice.fanart.tv/v3/movies/%s?api_key=%s' \
                % (mediaId, api_key)
        elif typus == 'tv':
            url = 'http://webservice.fanart.tv/v3/tv/%s?api_key=%s' \
                % (mediaId, api_key)
        else:
            # Not supported artwork
            return allartworks
        data = DownloadUtils().downloadUrl(
            url,
            authenticate=False,
            timeout=15)
        try:
            data.get('test')
        except:
            log.error('Could not download data from FanartTV')
            return allartworks

        # we need to use a little mapping between fanart.tv arttypes and kodi
        # artttypes
        fanartTVTypes = [
            ("logo", "Logo"),
            ("musiclogo", "clearlogo"),
            ("disc", "Disc"),
            ("clearart", "Art"),
            ("banner", "Banner"),
            ("clearlogo", "Logo"),
            ("background", "fanart"),
            ("showbackground", "fanart"),
            ("characterart", "characterart")
        ]
        if typus == "artist":
            fanartTVTypes.append(("thumb", "folder"))
        else:
            fanartTVTypes.append(("thumb", "Thumb"))

        if setInfo:
            fanartTVTypes.append(("poster", "Primary"))

        prefixes = (
            "hd" + typus,
            "hd",
            typus,
            "",
        )
        for fanarttype in fanartTVTypes:
            # Skip the ones we already have
            if allartworks.get(fanarttype[1]):
                continue
            for prefix in prefixes:
                fanarttvimage = prefix + fanarttype[0]
                if fanarttvimage not in data:
                    continue
                # select image in preferred language
                for entry in data[fanarttvimage]:
                    if entry.get("lang") == v.KODILANGUAGE:
                        allartworks[fanarttype[1]] = entry.get("url", "").replace(' ', '%20')
                        break
                # just grab the first english OR undefinded one as fallback
                # (so we're actually grabbing the more popular one)
                if not allartworks.get(fanarttype[1]):
                    for entry in data[fanarttvimage]:
                        if entry.get("lang") in ("en", "00"):
                            allartworks[fanarttype[1]] = entry.get("url", "").replace(' ', '%20')
                            break

        # grab extrafanarts in list
        maxfanarts = 10
        fanartcount = 0
        for prefix in prefixes:
            fanarttvimage = prefix + 'background'
            if fanarttvimage not in data:
                continue
            for entry in data[fanarttvimage]:
                if fanartcount < maxfanarts:
                    if exists(entry.get("url")):
                        allartworks['Backdrop'].append(
                            entry.get("url", "").replace(' ', '%20'))
                        fanartcount += 1
        return allartworks

    def getSetArtwork(self, parentInfo=False):
        """
        Gets the URLs to the Plex artwork, or empty string if not found.
        parentInfo=True will check for parent's artwork if None is found

        Only call on movies

        Output:
        {
            'Primary'
            'Art'
            'Banner'
            'Logo'
            'Thumb'
            'Disc'
            'Backdrop' : LIST with the first entry xml key "art"
        }
        """
        allartworks = {
            'Primary': "",
            'Art': "",
            'Banner': "",
            'Logo': "",
            'Thumb': "",
            'Disc': "",
            'Backdrop': []
        }

        # Plex does not get much artwork - go ahead and get the rest from
        # fanart tv only for movie or tv show
        externalId = self.getExternalItemId(collection=True)
        if externalId is not None:
            allartworks = self.getFanartTVArt(externalId, allartworks, True)
        return allartworks

    def shouldStream(self):
        """
        Returns True if the item's 'optimizedForStreaming' is set, False other-
        wise
        """
        return self.item[0].attrib.get('optimizedForStreaming') == '1'

    def getMediastreamNumber(self):
        """
        Returns the Media stream as an int (mostly 0). Will let the user choose
        if several media streams are present for a PMS item (if settings are
        set accordingly)
        """
        # How many streams do we have?
        count = 0
        for entry in self.item.findall('./Media'):
            count += 1
        if (count > 1 and (
                (self.getType() != 'clip' and
                 settings('bestQuality') == 'false')
                or
                (self.getType() == 'clip' and
                 settings('bestTrailer') == 'false'))):
            # Several streams/files available.
            dialoglist = []
            for entry in self.item.findall('./Media'):
                fileName = ''
                audioLanguage = ''

                # Get additional info (filename / languages)
                mediaPartEntry = self.item.find('./Media/Part')
                if mediaPartEntry is not None:
                    # Filename
                    if 'file' in mediaPartEntry.attrib:
                        fileName = os.path.basename(mediaPartEntry.attrib['file'])

                    # Languages - subtitle does not seem to be directly included in this stream info
                    mediaPartStreamEntry = self.item.find('./Media/Part/Stream')
                    if mediaPartStreamEntry is not None:
                        # Audio language
                        if 'language' in mediaPartStreamEntry.attrib:
                            audioLanguage = mediaPartStreamEntry.attrib['language']

                dialoglist.append(
                    "%sp %s - %s (%s) (%s) %s" %
                    (entry.attrib.get('videoResolution', 'unknown'),
                    entry.attrib.get('videoCodec', 'unknown'),
                    entry.attrib.get('audioProfile', 'unknown'),
                    entry.attrib.get('audioCodec', 'unknown'),
                    audioLanguage,
                    fileName)
                )
            media = xbmcgui.Dialog().select('Select stream', dialoglist)
        else:
            media = 0
        self.mediastream = media
        return media

    def getTranscodeVideoPath(self, action, quality=None):
        """

        To be called on a VIDEO level of PMS xml response!

        Transcode Video support; returns the URL to get a media started

        Input:
            action      'DirectStream' or 'Transcode'

            quality:    {
                            'videoResolution': e.g. '1024x768',
                            'videoQuality': e.g. '60',
                            'maxVideoBitrate': e.g. '2000' (in kbits)
                        }
                        (one or several of these options)
        Output:
            final URL to pull in PMS transcoder

        TODO: mediaIndex
        """
        if self.mediastream is None:
            self.getMediastreamNumber()
        if quality is None:
            quality = {}
        xargs = client.getXArgsDeviceInfo()
        # For DirectPlay, path/key of PART is needed
        # trailers are 'clip' with PMS xmls
        if action == "DirectStream":
            path = self.item[self.mediastream][self.part].attrib['key']
            url = self.server + path
            # e.g. Trailers already feature an '?'!
            if '?' in url:
                url += '&' + urlencode(xargs)
            else:
                url += '?' + urlencode(xargs)
            return url

        # For Transcoding
        # Path/key to VIDEO item of xml PMS response is needed, not part
        path = self.item.attrib['key']
        transcodePath = self.server + \
            '/video/:/transcode/universal/start.m3u8?'
        args = {
            'protocol': 'hls',   # seen in the wild: 'dash', 'http', 'hls'
            'session':  window('plex_client_Id'),
            'fastSeek': 1,
            'path': path,
            'mediaIndex': self.mediastream,
            'partIndex': self.part,
            # 'copyts': 1,
            # 'offset': 0,           # Resume point
        }
        # Seem like PHT to let the PMS use the transcoding profile
        xargs['X-Plex-Device'] = 'Plex Home Theater'
        # Currently not used!
        if action == "DirectStream":
            argsUpdate = {
                'directPlay': '0',
                'directStream': '1',
            }
            args.update(argsUpdate)
        elif action == 'Transcode':
            argsUpdate = {
                'directPlay': '0',
                'directStream': '0'
            }
            log.debug("Setting transcode quality to: %s" % quality)
            args.update(quality)
            args.update(argsUpdate)
        url = transcodePath + urlencode(xargs) + '&' + urlencode(args)
        return url

    def externalSubs(self, playurl):
        externalsubs = []
        mapping = {}
        try:
            mediastreams = self.item[0][self.part]
        except (TypeError, KeyError, IndexError):
            return
        kodiindex = 0
        for stream in mediastreams:
            index = stream.attrib['id']
            # Since plex returns all possible tracks together, have to pull
            # only external subtitles.
            key = stream.attrib.get('key')
            # IsTextSubtitleStream if true, is available to download from plex.
            if stream.attrib.get('streamType') == "3" and key:
                # Direct stream
                url = ("%s%s" % (self.server, key))
                url = self.addPlexCredentialsToUrl(url)
                # map external subtitles for mapping
                mapping[kodiindex] = index
                externalsubs.append(url)
                kodiindex += 1
        mapping = dumps(mapping)
        window('plex_%s.indexMapping' % playurl, value=mapping)
        log.info('Found external subs: %s' % externalsubs)
        return externalsubs

    def GetKodiPremierDate(self):
        """
        Takes Plex' originallyAvailableAt of the form "yyyy-mm-dd" and returns
        Kodi's "dd.mm.yyyy"
        """
        date = self.getPremiereDate()
        if date is None:
            return
        try:
            date = sub(r'(\d+)-(\d+)-(\d+)', r'\3.\2.\1', date)
        except:
            date = None
        return date

    def CreateListItemFromPlexItem(self,
                                   listItem=None,
                                   appendShowTitle=False,
                                   appendSxxExx=False):
        if self.getType() == v.PLEX_TYPE_PHOTO:
            listItem = self.__createPhotoListItem(listItem)
            # Only set the bare minimum of artwork
            listItem.setArt({'icon': 'DefaultPicture.png',
                             'fanart': self.__getOneArtwork('thumb')})
        else:
            listItem = self.__createVideoListItem(listItem,
                                                  appendShowTitle,
                                                  appendSxxExx)
            self.add_video_streams(listItem)
            self.set_listitem_artwork(listItem)
        return listItem

    def __createPhotoListItem(self, listItem=None):
        """
        Use for photo items only
        """
        title, _ = self.getTitle()
        if listItem is None:
            listItem = xbmcgui.ListItem(title)
        else:
            listItem.setLabel(title)
        metadata = {
            'date': self.GetKodiPremierDate(),
            'size': long(self.item[0][0].attrib.get('size', 0)),
            'exif:width': self.item[0].attrib.get('width', ''),
            'exif:height': self.item[0].attrib.get('height', ''),
        }
        listItem.setInfo(type='image', infoLabels=metadata)
        listItem.setProperty('plot', self.getPlot())
        listItem.setProperty('plexid', self.getRatingKey())
        return listItem

    def __createVideoListItem(self,
                              listItem=None,
                              appendShowTitle=False,
                              appendSxxExx=False):
        """
        Use for video items only
        Call on a child level of PMS xml response (e.g. in a for loop)

        listItem        : existing xbmcgui.ListItem to work with
                          otherwise, a new one is created
        appendShowTitle : True to append TV show title to episode title
        appendSxxExx    : True to append SxxExx to episode title

        Returns XBMC listitem for this PMS library item
        """
        title, sorttitle = self.getTitle()
        typus = self.getType()

        if listItem is None:
            listItem = xbmcgui.ListItem(title)
        else:
            listItem.setLabel(title)
        # Necessary; Kodi won't start video otherwise!
        listItem.setProperty('IsPlayable', 'true')
        # Video items, e.g. movies and episodes or clips
        people = self.getPeople()
        userdata = self.getUserData()
        metadata = {
            'genre': self.joinList(self.getGenres()),
            'year': self.getYear(),
            'rating': self.getAudienceRating(),
            'playcount': userdata['PlayCount'],
            'cast': people['Cast'],
            'director': self.joinList(people.get('Director')),
            'plot': self.getPlot(),
            'sorttitle': sorttitle,
            'duration': userdata['Runtime'],
            'studio': self.joinList(self.getStudios()),
            'tagline': self.getTagline(),
            'writer': self.joinList(people.get('Writer')),
            'premiered': self.getPremiereDate(),
            'dateadded': self.getDateCreated(),
            'lastplayed': userdata['LastPlayedDate'],
            'mpaa': self.getMpaa(),
            'aired': self.getPremiereDate()
        }
        listItem.setProperty('resumetime', str(userdata['Resume']))
        listItem.setProperty('totaltime', str(userdata['Runtime']))

        if typus == v.PLEX_TYPE_EPISODE:
            key, show, season, episode = self.getEpisodeDetails()
            season = -1 if season is None else int(season)
            episode = -1 if episode is None else int(episode)
            metadata['episode'] = episode
            metadata['season'] = season
            metadata['tvshowtitle'] = show
            if season and episode:
                listItem.setProperty('episodeno',
                                     "s%.2de%.2d" % (season, episode))
                if appendSxxExx is True:
                    title = "S%.2dE%.2d - %s" % (season, episode, title)
            listItem.setArt({'icon': 'DefaultTVShows.png'})
            if appendShowTitle is True:
                title = "%s - %s " % (show, title)
            if appendShowTitle or appendSxxExx:
                listItem.setLabel(title)
        elif typus == v.PLEX_TYPE_MOVIE:
            listItem.setArt({'icon': 'DefaultMovies.png'})
        else:
            # E.g. clips, trailers, ...
            listItem.setArt({'icon': 'DefaultVideo.png'})

        plexId = self.getRatingKey()
        listItem.setProperty('plexid', plexId)
        with plexdb.Get_Plex_DB() as plex_db:
            try:
                listItem.setProperty('dbid',
                                     str(plex_db.getItem_byId(plexId)[0]))
            except TypeError:
                pass
        # Expensive operation
        metadata['title'] = title
        listItem.setInfo('video', infoLabels=metadata)
        return listItem

    def add_video_streams(self, listItem):
        """
        Add media stream information to xbmcgui.ListItem
        """
        mediastreams = self.getMediaStreams()
        videostreamFound = False
        if mediastreams:
            for key, value in mediastreams.iteritems():
                if key == "video" and value:
                    videostreamFound = True
                if value:
                    listItem.addStreamInfo(key, value)
        if not videostreamFound:
            # just set empty streamdetails to prevent errors in the logs
            listItem.addStreamInfo(
                "video", {'duration': self.getRuntime()[1]})

    def validatePlayurl(self, path, typus, forceCheck=False, folder=False):
        """
        Returns a valid path for Kodi, e.g. with '\' substituted to '\\' in
        Unicode. Returns None if this is not possible

            path       : Unicode
            typus      : Plex type from PMS xml
            forceCheck : Will always try to check validity of path
                         Will also skip confirmation dialog if path not found
            folder     : Set to True if path is a folder
        """
        if path is None:
            return None
        typus = v.REMAP_TYPE_FROM_PLEXTYPE[typus]
        if window('remapSMB') == 'true':
            path = path.replace(window('remapSMB%sOrg' % typus),
                                window('remapSMB%sNew' % typus),
                                1)
            # There might be backslashes left over:
            path = path.replace('\\', '/')
        elif window('replaceSMB') == 'true':
            if path.startswith('\\\\'):
                path = 'smb:' + path.replace('\\', '/')
        if window('plex_pathverified') == 'true' and forceCheck is False:
            return path

        # exist() needs a / or \ at the end to work for directories
        if folder is False:
            # files
            check = exists(tryEncode(path)) == 1
        else:
            # directories
            if "\\" in path:
                # Add the missing backslash
                check = exists(tryEncode(path + "\\")) == 1
            else:
                check = exists(tryEncode(path + "/")) == 1

        if check is False:
            if forceCheck is False:
                # Validate the path is correct with user intervention
                if self.askToValidate(path):
                    window('plex_shouldStop', value="true")
                    path = None
                window('plex_pathverified', value='true')
            else:
                path = None
        elif forceCheck is False:
            if window('plex_pathverified') != 'true':
                window('plex_pathverified', value='true')
        return path

    def askToValidate(self, url):
        """
        Displays a YESNO dialog box:
            Kodi can't locate file: <url>. Please verify the path.
            You may need to verify your network credentials in the
            add-on settings or use different Plex paths. Stop syncing?

        Returns True if sync should stop, else False
        """
        log.warn('Cannot access file: %s' % url)
        resp = xbmcgui.Dialog().yesno(
            heading=lang(29999),
            line1=lang(39031) + url,
            line2=lang(39032))
        return resp

    def set_listitem_artwork(self, listitem):
        """
        Set all artwork to the listitem
        """
        allartwork = self.getAllArtwork(parentInfo=True)
        arttypes = {
            'poster': "Primary",
            'tvshow.poster': "Thumb",
            'clearart': "Art",
            'tvshow.clearart': "Art",
            'clearart': "Primary",
            'tvshow.clearart': "Primary",
            'clearlogo': "Logo",
            'tvshow.clearlogo': "Logo",
            'discart': "Disc",
            'fanart_image': "Backdrop",
            'landscape': "Backdrop",
            "banner": "Banner"
        }
        for arttype in arttypes:
            art = arttypes[arttype]
            if art == "Backdrop":
                try:
                    # Backdrop is a list, grab the first backdrop
                    self._set_listitem_artprop(listitem,
                                               arttype,
                                               allartwork[art][0])
                except:
                    pass
            else:
                self._set_listitem_artprop(listitem, arttype, allartwork[art])

    def _set_listitem_artprop(self, listitem, arttype, path):
        if arttype in (
                'thumb', 'fanart_image', 'small_poster', 'tiny_poster',
                'medium_landscape', 'medium_poster', 'small_fanartimage',
                'medium_fanartimage', 'fanart_noindicators'):
            listitem.setProperty(arttype, path)
        else:
            listitem.setArt({arttype: path})

    def set_playback_win_props(self, playurl, listitem):
        """
        Set all properties necessary for plugin path playback for listitem
        """
        itemtype = self.getType()
        userdata = self.getUserData()

        plexitem = "plex_%s" % playurl
        window('%s.runtime' % plexitem, value=str(userdata['Runtime']))
        window('%s.type' % plexitem, value=itemtype)
        window('%s.itemid' % plexitem, value=self.getRatingKey())
        window('%s.playcount' % plexitem, value=str(userdata['PlayCount']))

        if itemtype == v.PLEX_TYPE_EPISODE:
            window('%s.refreshid' % plexitem, value=self.getParentRatingKey())
        else:
            window('%s.refreshid' % plexitem, value=self.getRatingKey())

        # Append external subtitles to stream
        playmethod = window('%s.playmethod' % plexitem)
        if playmethod in ("DirectStream", "DirectPlay"):
            subtitles = self.externalSubs(playurl)
            listitem.setSubtitles(subtitles)
