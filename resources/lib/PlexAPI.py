
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
import time
import urllib2
import socket
from threading import Thread
import xml.etree.ElementTree as etree
import re
import json
from urllib import urlencode, quote_plus, unquote

import xbmcaddon
import xbmcgui
import xbmc
import xbmcvfs

import clientinfo
import utils
import downloadutils
import requests
from PlexFunctions import PlexToKodiTimefactor, PMSHttpsEnabled


@utils.logging
class PlexAPI():
    # CONSTANTS
    # Timeout for POST/GET commands, I guess in seconds
    timeout = 10

    def __init__(self):
        self.__language__ = xbmcaddon.Addon().getLocalizedString
        self.g_PMS = {}
        self.doUtils = downloadutils.DownloadUtils().downloadUrl

    def GetPlexLoginFromSettings(self):
        """
        Returns a dict:
            'plexLogin': utils.settings('plexLogin'),
            'plexToken': utils.settings('plexToken'),
            'plexhome': utils.settings('plexhome'),
            'plexid': utils.settings('plexid'),
            'myplexlogin': utils.settings('myplexlogin'),
            'plexAvatar': utils.settings('plexAvatar'),
            'plexHomeSize': utils.settings('plexHomeSize')

        Returns strings or unicode

        Returns empty strings '' for a setting if not found.

        myplexlogin is 'true' if user opted to log into plex.tv (the default)
        plexhome is 'true' if plex home is used (the default)
        """
        return {
            'plexLogin': utils.settings('plexLogin'),
            'plexToken': utils.settings('plexToken'),
            'plexhome': utils.settings('plexhome'),
            'plexid': utils.settings('plexid'),
            'myplexlogin': utils.settings('myplexlogin'),
            'plexAvatar': utils.settings('plexAvatar'),
            'plexHomeSize': utils.settings('plexHomeSize')
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
        string = self.__language__

        retrievedPlexLogin = ''
        plexLogin = 'dummy'
        authtoken = ''
        dialog = xbmcgui.Dialog()
        while retrievedPlexLogin == '' and plexLogin != '':
            # Enter plex.tv username. Or nothing to cancel.
            plexLogin = dialog.input(self.addonName + string(39300),
                                     type=xbmcgui.INPUT_ALPHANUM)
            if plexLogin != "":
                # Enter password for plex.tv user
                plexPassword = dialog.input(
                    string(39301) + plexLogin,
                    type=xbmcgui.INPUT_ALPHANUM,
                    option=xbmcgui.ALPHANUM_HIDE_INPUT)
                retrievedPlexLogin, authtoken = self.MyPlexSignIn(
                    plexLogin,
                    plexPassword,
                    {'X-Plex-Client-Identifier':
                        clientinfo.ClientInfo().getDeviceId()})
                self.logMsg("plex.tv username and token: %s, %s"
                            % (plexLogin, authtoken), 1)
                if plexLogin == '':
                    # Could not sign in user
                    dialog.ok(self.addonName,
                              string(39302) + plexLogin)
        # Write to Kodi settings file
        utils.settings('plexLogin', value=retrievedPlexLogin)
        utils.settings('plexToken', value=authtoken)
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
        string = self.__language__

        code, identifier = self.GetPlexPin()
        dialog = xbmcgui.Dialog()
        if not code:
            # Problems trying to contact plex.tv. Try again later
            dialog.ok(self.addonName, string(39303))
            return False
        # Go to https://plex.tv/pin and enter the code:
        # Or press No to cancel the sign in.
        answer = dialog.yesno(self.addonName,
                              string(39304) + "\n\n",
                              code + "\n\n",
                              string(39311))
        if not answer:
            return False
        count = 0
        # Wait for approx 30 seconds (since the PIN is not visible anymore :-))
        while count < 30:
            xml = self.CheckPlexTvSignin(identifier)
            if xml is not False:
                break
            # Wait for 1 seconds
            xbmc.sleep(1000)
            count += 1
        if xml is False:
            # Could not sign in to plex.tv Try again later
            dialog.ok(self.addonName, string(39305))
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
        utils.settings('plexLogin', username)
        utils.settings('plexToken', token)
        utils.settings('plexhome', home)
        utils.settings('plexid', userid)
        utils.settings('plexAvatar', avatar)
        utils.settings('plexHomeSize', homeSize)
        # Let Kodi log into plex.tv on startup from now on
        utils.settings('myplexlogin', 'true')
        return result

    def CheckPlexTvSignin(self, identifier):
        """
        Checks with plex.tv whether user entered the correct PIN on plex.tv/pin

        Returns False if not yet done so, or the XML response file as etree
        """
        # Try to get a temporary token
        xml = self.doUtils('https://plex.tv/pins/%s.xml' % identifier,
                           authenticate=False,
                           type="GET")
        try:
            temp_token = xml.find('auth_token').text
        except:
            self.logMsg("Could not find token in plex.tv answer.", -1)
            return False
        self.logMsg("temp token from plex.tv is: %s" % temp_token, 2)
        if not temp_token:
            return False
        # Use temp token to get the final plex credentials
        xml = self.doUtils('https://plex.tv/users/account',
                           authenticate=False,
                           parameters={'X-Plex-Token': temp_token},
                           type="GET")
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
                           type="POST")
        try:
            xml.attrib
        except:
            self.logMsg("Error, no PIN from plex.tv provided", -1)
            return None, None
        code = xml.find('code').text
        identifier = xml.find('id').text
        self.logMsg('Successfully retrieved code and id from plex.tv', 1)
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
            verifySSL = None if utils.settings('sslverify') == 'true' \
                else False
        if 'plex.tv' in url:
            url = 'https://plex.tv/api/home/users'
        else:
            url = url + '/library/onDeck'
        self.logMsg("Checking connection to server %s with verifySSL=%s"
                    % (url, verifySSL), 1)
        # Check up to 3 times before giving up
        count = 0
        while count < 3:
            answer = self.doUtils(url,
                                  authenticate=False,
                                  headerOptions=headerOptions,
                                  verifySSL=verifySSL)
            if answer is False:
                self.logMsg("Could not connect to %s" % url, 0)
                count += 1
                xbmc.sleep(500)
                continue
            try:
                answer.attrib
            except:
                pass
            else:
                # Success - we downloaded an xml!
                answer = 200
            self.logMsg("Checking connection successfull. Answer: %s"
                        % answer, 1)
            return answer
        self.logMsg('Failed to connect to %s too many times. PMS is dead'
                    % url, 0)
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

    def setgPMSToSettings(self, g_PMS):
        """
        PlexDB: takes an g_PMS list of Plex servers and saves them all to
        the Kodi settings file. It does NOT save the ATV_udid as that id
        seems to change with reboot. Settings are set using the Plex server
        machineIdentifier.

        Input:
            g_PMS

        Output:

        Assumptions:
            There is only one ATV_udid in g_PMS

        Existing entries for servers with the same ID get overwritten.
        New entries get added. Serverinfo already set in file are set to ''.

        NOTE: it is currently not possible to delete entries in Kodi settings
        file!
        """
        addon = xbmcaddon.Addon()
        # Get rid of uppermost level ATV_udid in g_PMS
        ATV_udid = list(g_PMS.keys())[0]
        g_PMS = g_PMS[ATV_udid]

        serverlist = []
        keylist = self.getgPMSKeylist()
        for serverid, servervalues in g_PMS.items():
            serverlist.append(serverid)
            # Set values in Kodi settings file
            for item in keylist:
                # Append the server's ID first, then immediatelly the setting
                addon.setSetting(
                    str(serverid) + str(item),      # the key
                    str(g_PMS[serverid][item])      # the value
                )
        # Write a new or updated 'serverlist' string to settings
        oldserverlist = addon.getSetting('serverlist')
        # If no server has been saved yet, return
        if oldserverlist == '':
            serverlist = ','.join(serverlist)
            addon.setSetting('serverlist', serverlist)
            return
        oldserverlist = oldserverlist.split(',')
        for server in oldserverlist:
            # Delete serverinfo that has NOT been passed in serverlist
            if server not in serverlist:
                # Set old value to '', because deleting is not possible
                for item in keylist:
                    addon.setSetting(str(server) + str(item), '')
        serverlist = ','.join(serverlist)
        addon.setSetting('serverlist', serverlist)
        return

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
            self.logMsg('%s has not yet been declared ' % uuid, -1)
            return False

    def getPMSProperty(self, uuid, tag):
        # get name of PMS by UUID
        try:
            answ = self.g_PMS[uuid].get(tag, '')
        except:
            self.logMsg('%s not found in PMS catalogue' % uuid, -1)
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
                    # dprint(__name__, 1, "Received data from {0}", server)
                    # dprint(__name__, 1, "Data received:\n {0}", data)
                    returnData.append({'from': server,
                                       'data': data})
                except socket.timeout:
                    break
        finally:
            GDM.close()

        pmsList = {}

        self.logMsg('returndata is: %s' % returnData)
        for response in returnData:
            update = {'ip': response.get('from')[0]}
            # Check if we had a positive HTTP response
            if "200 OK" in response.get('data'):
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
                        update['serverName'] = each.split(
                            ':')[1].strip().decode('utf-8', 'replace')
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
        xbmcgui.Dialog().notification(
            heading=self.addonName,
            message=self.__language__(39055),
            icon="special://home/addons/plugin.video.plexkodiconnect/icon.png",
            time=3000,
            sound=False)

        # Look first for local PMS in the LAN
        pmsList = self.PlexGDM()
        self.logMsg('pmslist: %s' % pmsList, 1)
        for uuid in pmsList:
            PMS = pmsList[uuid]
            self.declarePMS(PMS['uuid'], PMS['serverName'], 'http',
                            PMS['ip'], PMS['port'])
            self.updatePMSProperty(PMS['uuid'], 'owned', '-')
            # Ping to check whether we need HTTPs or HTTP
            url = '%s:%s' % (PMS['ip'], PMS['port'])
            https = PMSHttpsEnabled(url)
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

        if not plexToken:
            self.logMsg('No plex.tv token supplied, checked LAN for PMS', 0)
            return

        # install plex.tv "virtual" PMS - for myPlex, PlexHome
        # self.declarePMS('plex.tv', 'plex.tv', 'https', 'plex.tv', '443')
        # self.updatePMSProperty('plex.tv', 'local', '-')
        # self.updatePMSProperty('plex.tv', 'owned', '-')
        # self.updatePMSProperty(
        #     'plex.tv', 'accesstoken', plexToken)
        # (remote and local) servers from plex.tv

        # Get PMS from plex.tv. This will overwrite any PMS we already found
        self.getPMSListFromMyPlex(plexToken)

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
        except:
            self.logMsg('Could not get list of PMS from plex.tv', -1)
            return

        import Queue
        queue = Queue.Queue()
        threads = []

        for Dir in xml.findall('Device'):
            if "server" in Dir.get('provides'):
                if Dir.find('Connection') is None:
                    # no valid connection - skip
                    continue

                # check MyPlex data age - skip if >2 days
                PMS = {}
                PMS['name'] = Dir.get('name')
                infoAge = time.time() - int(Dir.get('lastSeenAt'))
                oneDayInSec = 60 * 60 * 24
                if infoAge > 2 * oneDayInSec:
                    self.logMsg("Server %s not seen for 2 days - "
                                "skipping." % PMS['name'], 0)
                    continue

                PMS['uuid'] = Dir.get('clientIdentifier')
                PMS['token'] = Dir.get('accessToken', token)
                PMS['owned'] = Dir.get('owned', '0')
                PMS['local'] = Dir.get('publicAddressMatches')
                PMS['ownername'] = Dir.get('sourceTitle', '')
                PMS['path'] = '/'
                PMS['options'] = None

                # If PMS seems (!!) local, try a local connection first
                # Backup to remote connection, if that failes
                PMS['baseURL'] = ''
                for Con in Dir.findall('Connection'):
                    localConn = Con.get('local')
                    if ((PMS['local'] == '1' and localConn == '1') or
                            (PMS['local'] == '0' and localConn == '0')):
                        # Either both local or both remote
                        PMS['protocol'] = Con.get('protocol')
                        PMS['ip'] = Con.get('address')
                        PMS['port'] = Con.get('port')
                        PMS['baseURL'] = Con.get('uri')
                    elif PMS['local'] == '1' and localConn == '0':
                        # Backup connection if local one did not work
                        PMS['backup'] = {}
                        PMS['backup']['protocol'] = Con.get('protocol')
                        PMS['backup']['ip'] = Con.get('address')
                        PMS['backup']['port'] = Con.get('port')
                        PMS['backup']['baseURL'] = Con.get('uri')

                # poke PMS, own thread for each poke
                t = Thread(target=self.pokePMS,
                           args=(PMS, queue))
                t.start()
                threads.append(t)

            # wait for requests being answered
            for t in threads:
                t.join()

            # declare new PMSs
            while not queue.empty():
                PMS = queue.get()
                self.declarePMS(PMS['uuid'], PMS['name'],
                                PMS['protocol'], PMS['ip'], PMS['port'])
                # dflt: token='', local, owned - updated later
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
                queue.task_done()

    def pokePMS(self, PMS, queue):
        # Ignore SSL certificates for now
        xml = self.doUtils(PMS['baseURL'],
                           authenticate=False,
                           headerOptions={'X-Plex-Token': PMS['token']},
                           verifySSL=False)
        try:
            xml.attrib
        except:
            # Connection failed
            # retry with remote connection if we just tested local one.
            if PMS['local'] == '1' and PMS.get('backup'):
                self.logMsg('Couldnt talk to local PMS locally.'
                            'Trying again remotely.', 0)
                PMS['protocol'] = PMS['backup']['protocol']
                PMS['ip'] = PMS['backup']['ip']
                PMS['port'] = PMS['backup']['port']
                PMS['baseURL'] = PMS['backup']['baseURL']
                PMS['local'] = '0'
                # Try again
                self.pokePMS(PMS, queue)
            else:
                return
        else:
            # Connection successful, process later
            queue.put(PMS)

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
        xargs = clientinfo.ClientInfo().getXArgsDeviceInfo(options)
        self.logMsg("Header is: %s" % xargs, 1)
        request = urllib2.Request(MyPlexURL, None, xargs)
        request.get_method = lambda: 'POST'
        # turn into 'POST'
        # done automatically with data!=None. But we don't have data.

        # no certificate, will fail with "401 - Authentification required"
        """
        try:
            f = urllib2.urlopen(request)
        except urllib2.HTTPError, e:
            print e.headers
            print "has WWW_Authenticate:", e.headers.has_key('WWW-Authenticate')
            print
        """

        # provide credentials
        # optional... when 'realm' is unknown
        ##passmanager = urllib2.HTTPPasswordMgrWithDefaultRealm()
        # passmanager.add_password(None, address, username, password)  # None:
        # default "realm"
        passmanager = urllib2.HTTPPasswordMgr()
        passmanager.add_password(MyPlexHost, MyPlexURL, username, password)
        authhandler = urllib2.HTTPBasicAuthHandler(passmanager)
        urlopener = urllib2.build_opener(authhandler)

        # sign in, get MyPlex response
        try:
            response = urlopener.open(request).read()
        except urllib2.HTTPError as e:
            if e.code == 401:
                self.logMsg("Authentication failed", 0)
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

        dprint(__name__, 1, "====== MyPlex sign out XML ======")
        dprint(__name__, 1, response)
        dprint(__name__, 1, "====== MyPlex sign out XML finished ======")
        dprint(__name__, 0, 'MyPlex Sign Out done')

    def GetUserArtworkURL(self, username):
        """
        Returns the URL for the user's Avatar. Or False if something went
        wrong.
        """
        plexToken = utils.settings('plexToken')
        users = self.MyPlexListHomeUsers(plexToken)
        url = ''
        # If an error is encountered, set to False
        if not users:
            self.logMsg("Could not get userlist from plex.tv.", 1)
            self.logMsg("No URL for user avatar.", 1)
            return False
        for user in users:
            if username in user['title']:
                url = user['thumb']
        self.logMsg("Avatar url for user %s is: %s" % (username, url), 1)
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
        string = self.__language__
        dialog = xbmcgui.Dialog()

        # Get list of Plex home users
        users = self.MyPlexListHomeUsers(plexToken)
        if not users:
            self.logMsg("User download failed.", -1)
            return False

        userlist = []
        userlistCoded = []
        for user in users:
            username = user['title']
            userlist.append(username)
            # To take care of non-ASCII usernames
            userlistCoded.append(username.encode('utf-8'))
        usernumber = len(userlist)

        username = ''
        usertoken = ''
        trials = 0
        while trials < 3:
            if usernumber > 1:
                # Select user
                user_select = dialog.select(
                    self.addonName + string(39306),
                    userlistCoded)
                if user_select == -1:
                    self.logMsg("No user selected.", 0)
                    utils.settings('username', value='')
                    xbmc.executebuiltin('Addon.OpenSettings(%s)'
                                        % clientinfo.ClientInfo().getAddonId())
                    return False
            # Only 1 user received, choose that one
            else:
                user_select = 0
            selected_user = userlist[user_select]
            self.logMsg("Selected user: %s" % selected_user, 0)
            user = users[user_select]
            # Ask for PIN, if protected:
            pin = None
            if user['protected'] == '1':
                self.logMsg('Asking for users PIN', 1)
                pin = dialog.input(
                    string(39307) + selected_user,
                    type=xbmcgui.INPUT_NUMERIC,
                    option=xbmcgui.ALPHANUM_HIDE_INPUT)
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
                utils.settings('plex_machineIdentifier'))
            if result:
                # Successfully retrieved username: break out of while loop
                username = result['username']
                usertoken = result['usertoken']
                break
            # Couldn't get user auth
            else:
                trials += 1
                # Could not login user, please try again
                if not dialog.yesno(self.addonName,
                                    string(39308) + selected_user,
                                    string(39309)):
                    # User chose to cancel
                    break

        if not username:
            self.logMsg('Failed signing in a user to plex.tv', -1)
            xbmc.executebuiltin('Addon.OpenSettings(%s)'
                                % clientinfo.ClientInfo().getAddonId())
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
        url = 'https://plex.tv/api/home/users/' + userId + '/switch'
        if pin:
            url += '?pin=' + pin
        self.logMsg('Switching to user %s' % userId, 0)
        answer = self.doUtils(url,
                              authenticate=False,
                              type="POST",
                              headerOptions={'X-Plex-Token': token})
        try:
            answer.attrib
        except:
            self.logMsg('Error: plex.tv switch HomeUser change failed', -1)
            return False

        username = answer.attrib.get('title', '')
        token = answer.attrib.get('authenticationToken', '')
        userid = answer.attrib.get('id', '')

        # Write to settings file
        utils.settings('username', username)
        utils.settings('userid', userid)
        utils.settings('accessToken', token)

        # Get final token to the PMS we've chosen
        url = 'https://plex.tv/api/resources?includeHttps=1'
        xml = self.doUtils(url,
                           authenticate=False,
                           type="GET",
                           headerOptions={'X-Plex-Token': token})
        try:
            xml.attrib
        except:
            self.logMsg('Answer from plex.tv not as excepted', -1)
            # Set to empty iterable list for loop
            xml = []

        found = 0
        self.logMsg('Our machineIdentifier is %s' % machineIdentifier, 0)
        for device in xml:
            identifier = device.attrib.get('clientIdentifier')
            self.logMsg('Found a Plex machineIdentifier: %s' % identifier, 0)
            if (identifier in machineIdentifier or
                    machineIdentifier in identifier):
                found += 1
                token = device.attrib.get('accessToken')

        result = {
            'username': username,
        }
        if found == 0:
            self.logMsg('No tokens found for your server!', 0)
            self.logMsg('Using empty string as token', 0)
            result['usertoken'] = ''
        else:
            result['usertoken'] = token

        self.logMsg('Plex.tv switch HomeUser change successfull for user %s'
                    % username, 0)
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
            self.logMsg('Download of Plex home users failed.', -1)
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
        path = path.encode('utf8')

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

        xargs = clientinfo.ClientInfo().getXArgsDeviceInfo(options)
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


@utils.logging
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
        self.__language__ = xbmcaddon.Addon().getLocalizedString
        self.server = utils.window('pms_server')

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

    def getFilePath(self):
        """
        Returns the direct path to this item, e.g. '\\NAS\movies\movie.mkv'
        or None
        """
        try:
            res = self.item[0][self.part].attrib.get('file')
        except:
            res = None
        if res is not None:
            res = unquote(res).decode('utf-8')
        return res

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
        Returns the date when this library item was created or None
        """
        res = self.item.attrib.get('addedAt')
        if res is not None:
            res = utils.DateToKodi(res)
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
        except:
            playcount = None

        if playcount:
            played = True
        else:
            played = False

        try:
            lastPlayedDate = utils.DateToKodi(int(item['lastViewedAt']))
        except:
            lastPlayedDate = None

        try:
            userrating = float(item['userRating'])
        except:
            userrating = 0.0

        try:
            rating = float(item['audienceRating'])
        except:
            try:
                rating = float(item['rating'])
            except:
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
            regex = re.compile(r'''/(tt\d+)''')
        elif providername == 'tvdb':
            # originally e.g. com.plexapp.agents.thetvdb://276564?lang=en
            regex = re.compile(r'''tvdb://(\d+)''')
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
            res = self.item.attrib.get('rating', 0.0)
        res = float(res)
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
        except KeyError:
            runtime = 0.0
        try:
            resume = float(item['viewOffset'])
        except KeyError:
            resume = 0.0

        runtime = int(runtime * PlexToKodiTimefactor())
        resume = int(resume * PlexToKodiTimefactor())
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
        return self.item.attrib.get('originallyAvailableAt', None)

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
        xargs = clientinfo.ClientInfo().getXArgsDeviceInfo()
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
        if utils.window('pms_token') == '':
            return url
        if '?' not in url:
            url = "%s?X-Plex-Token=%s" % (url, utils.window('pms_token'))
        else:
            url = "%s&X-Plex-Token=%s" % (url, utils.window('pms_token'))
        return url

    def GetPlayQueueItemID(self):
        """
        Returns current playQueueItemID for the item.

        If not found, empty str is returned
        """
        return self.item.attrib.get('playQueueItemID', '')

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
                'bitrate': xxx,          e.g. 10642 (an int!)
                'container': xxx         e.g. 'mkv'
            }
        """

        videocodec = self.getDataFromPartOrMedia('videoCodec')
        resolution = self.getDataFromPartOrMedia('videoResolution')
        height = self.getDataFromPartOrMedia('height')
        width = self.getDataFromPartOrMedia('width')
        aspectratio = self.getDataFromPartOrMedia('aspectratio')
        bitrate = self.getDataFromPartOrMedia('bitrate')
        container = self.getDataFromPartOrMedia('container')

        videoCodec = {
            'videocodec': videocodec,
            'resolution': resolution,
            'height': height,
            'width': width,
            'aspectratio': aspectratio,
            'bitrate': bitrate,
            'container': container
        }
        return videoCodec

    def getExtras(self):
        """
        Returns a list of trailer and extras from PMS XML. Returns [] if
        no extras are found.
        Extratypes:
            '1':    Trailer
            '5':    Behind the scenes

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
        for extra in self.item.find('Extras'):
            # Trailer:
            key = extra.attrib.get('key', None)
            title = extra.attrib.get('title', None)
            thumb = extra.attrib.get('thumb', None)
            duration = float(extra.attrib.get('duration', 0.0))
            year = extra.attrib.get('year', None)
            extraType = extra.attrib.get('extraType', None)
            originallyAvailableAt = extra.attrib.get(
                'originallyAvailableAt', None)
            elements.append(
                {'key': key,
                 'title': title,
                 'thumb': thumb,
                 'duration': int(duration * PlexToKodiTimefactor()),
                 'extraType': extraType,
                 'originallyAvailableAt': originallyAvailableAt,
                 'year': year})
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
                    profile = mediaStream.get('codecID', '').lower()
                    if "dca" in audiotrack['codec'] and "dts-hd ma" in profile:
                        audiotrack['codec'] = "dtshd_ma"
                    audiotrack['channels'] = mediaStream.get('channels')
                    # 'unknown' if we cannot get language
                    audiotrack['language'] = mediaStream.get(
                        'language', self.__language__(39310))
                    audiotracks.append(audiotrack)

                elif mediaType == 3:  # Subtitle streams
                    # 'unknown' if we cannot get language
                    subtitlelanguages.append(
                        mediaStream.get('language', self.__language__(39310)))
        return {
            'video': videotracks,
            'audio': audiotracks,
            'subtitle': subtitlelanguages
        }

    def getAllArtwork(self, parentInfo=False):
        """
        Gets the URLs to the Plex artwork, or empty string if not found.

        Output:
        {
            'Primary':           Plex key: "thumb". Only 1 pix
            'Art':,
            'Banner':,
            'Logo':,
            'Thumb':,
            'Disc':,
            'Backdrop': []       Plex key: "art". Only 1 pix
        }
        """
        item = self.item.attrib

        # maxHeight = 10000
        # maxWidth = 10000
        # customquery = ""

        # if utils.settings('compressArt') == "true":
        #     customquery = "&Quality=90"

        # if utils.settings('enableCoverArt') == "false":
        #     customquery += "&EnableImageEnhancers=false"

        allartworks = {
            'Primary': "",
            'Art': "",
            'Banner': "",
            'Logo': "",
            'Thumb': "",
            'Disc': "",
            'Backdrop': []
        }
        # Process backdrops
        # Get background artwork URL
        try:
            background = item['art']
            background = "%s%s" % (self.server, background)
            background = self.addPlexCredentialsToUrl(background)
        except KeyError:
            background = ""
        allartworks['Backdrop'].append(background)
        # Get primary "thumb" pictures:
        try:
            primary = item['thumb']
            primary = "%s%s" % (self.server, primary)
            primary = self.addPlexCredentialsToUrl(primary)
        except KeyError:
            primary = ""
        allartworks['Primary'] = primary

        # Process parent items if the main item is missing artwork
        if parentInfo:
            # Process parent backdrops
            if not allartworks['Backdrop']:
                background = item.get('parentArt')
                if background:
                    background = "%s%s" % (self.server, background)
                    background = self.addPlexCredentialsToUrl(background)
                    allartworks['Backdrop'].append(background)

            if not allartworks['Primary']:
                primary = item.get('parentThumb')
                if primary:
                    primary = "%s%s" % (self.server, primary)
                    primary = self.addPlexCredentialsToUrl(primary)
                    allartworks['Primary'] = primary

        # Plex does not get much artwork - go ahead and get the rest from fanart tv only for movie or tv show
        type = item.get('type')
        if type=='movie' or type=='show':
            allartworks = self.getfanartTVimages(allartworks)

        if allartworks == None:
            self.logMsg('No artwork found for title%s' %str(item.get('title')))
            return  {}
        else:
            return allartworks
    def getfanartTVimages(self,allartworks):
        item = self.item.attrib
        tmdb_apiKey = "ae06df54334aa653354e9a010f4b81cb"
        KODILANGUAGE = xbmc.getLanguage(xbmc.ISO_639_1)
        media_id = None
        media_type = None
        type = item.get('type')
        if type == 'show':
            type = 'tv'
        title = item.get('title')
        # if the title has the year in remove it as tmdb cannot deal with it...making an assumption it is something like The Americans (2015)
        if title.endswith(")"): title = title[:-6]
        year = item.get('year')
        if not type: type="multi"
        try:
            url = 'http://api.themoviedb.org/3/search/%s?api_key=%s&language=%s&query=%s' %(type,tmdb_apiKey,KODILANGUAGE,utils.try_encode(title))
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = json.loads(response.content.decode('utf-8','replace'))
                #find year match
                if data and year and data.get("results"):
                    for item in data["results"]:
                        if item.get("first_air_date") and year in item.get("first_air_date"):
                            matchFound = item
                            break
                        elif item.get("release_date") and year in item.get("release_date"):
                            matchFound = item
                            break
                #find exact match based on title
                if not matchFound and data and data.get("results",None):
                    for item in data["results"]:
                        name = item.get("name")
                        if not name: name = item.get("title")
                        original_name = item.get("original_name","")
                        title_alt = title.lower().replace(" ","").replace("-","").replace(":","").replace("&","").replace(",","")
                        name_alt = name.lower().replace(" ","").replace("-","").replace(":","").replace("&","").replace(",","")
                        org_name_alt = original_name.lower().replace(" ","").replace("-","").replace(":","").replace("&","").replace(",","")
                        if name == title or original_name == title:
                            #match found for exact title name
                            matchFound = item
                            break
                        elif name.split(" (")[0] == title or title_alt == name_alt or title_alt == org_name_alt:
                            #match found with substituting some stuff
                            matchFound = item
                            break

                    #if a match was not found, we accept the closest match from TMDB
                    if not matchFound and len(data.get("results")) > 0 and not len(data.get("results")) > 5:
                        matchFound = item = data.get("results")[0]

            if matchFound:
                coverUrl = matchFound.get("poster_path","")
                fanartUrl = matchFound.get("backdrop_path","")
                id = str(matchFound.get("id",""))
                media_type = type
                if media_type == "multi" and matchFound.get("media_type"):
                    media_type = matchFound.get("media_type","")
                name = item.get("name")
                if not name: name = item.get("title")
                #lookup external tmdb_id and perform artwork lookup on fanart.tv
                if id:
                    languages = [KODILANGUAGE,"en"]
                    for language in languages:
                        if media_type == "movie":
                            url = 'http://api.themoviedb.org/3/movie/%s?api_key=%s&language=%s&append_to_response=videos' %(id,tmdb_apiKey,language)
                        elif media_type == "tv":
                            url = 'http://api.themoviedb.org/3/tv/%s?api_key=%s&append_to_response=external_ids,videos&language=%s' %(id,tmdb_apiKey,language)
                        response = requests.get(url)
                        data = json.loads(response.content.decode('utf-8','replace'))
                        if data:
                            if not media_id and data.get("imdb_id"):
                                media_id = str(data.get("imdb_id"))
                            if not media_id and data.get("external_ids"):
                                media_id = str(data["external_ids"].get("tvdb_id"))

            #lookup artwork on fanart.tv
            if media_id and media_type:
                #gets fanart.tv images for given id
                api_key = "639191cb0774661597f28a47e7e2bad5"

                if type == "movie":
                    url = 'http://webservice.fanart.tv/v3/movies/%s?api_key=%s' %(media_id,api_key)
                else:
                    url = 'http://webservice.fanart.tv/v3/tv/%s?api_key=%s' %(media_id,api_key)
                try:
                    response = requests.get(url, timeout=15)
                except Exception as e:
                    return allartworks
                if response and response.content and response.status_code == 200:
                    data = json.loads(response.content.decode('utf-8','replace'))
                else:
                    #not found
                    return allartworks
                if data:
                    #we need to use a little mapping between fanart.tv arttypes and kodi artttypes
                    fanartTVTypes = [ ("logo","Logo"),("musiclogo","clearlogo"),("disc","Disc"),("clearart","Art"),("banner","Banner"),("clearlogo","Logo"),("background","fanart"),("showbackground","fanart"),("characterart","characterart")]
                    if type != "artist": fanartTVTypes.append( ("thumb","Thumb") )
                    if type == "artist": fanartTVTypes.append( ("thumb","folder") )
                    prefixes = ["",type,"hd","hd"+type]
                    for fanarttype in fanartTVTypes:
                        for prefix in prefixes:
                            fanarttvimage = prefix+fanarttype[0]
                            if data.has_key(fanarttvimage):
                                for item in data[fanarttvimage]:
                                    if item.get("lang","") == KODILANGUAGE:
                                        #select image in preferred language
                                        if xbmcvfs.exists(item.get("url")):
                                            allartworks[fanarttype[1]] = item.get("url")
                                            break
                                if not allartworks.get(fanarttype[1]) or (not "http:" in allartworks.get(fanarttype[1])):
                                    #just grab the first english one as fallback
                                    for item in data[fanarttvimage]:
                                        if item.get("lang","") == "en" or not item.get("lang"):
                                            if xbmcvfs.exists(item.get("url")):
                                                allartworks[fanarttype[1]] = item.get("url")
                                                break
                                #grab extrafanarts in list
                                maxfanarts = 10
                                if "background" in fanarttvimage:
                                    fanartcount = 0
                                    for item in data[fanarttvimage]:
                                        if fanartcount < maxfanarts:
                                            if xbmcvfs.exists(item.get("url")):
                                                allartworks['Backdrop'].append(item.get("url"))
                                                fanartcount += 1
                                                #save extrafanarts as string

                return allartworks

        except Exception as e:
            #no artwork
            self.logMsg('No extra artwork found')
            return allartworks

    def getTranscodeVideoPath(self, action, quality={}):
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

        xargs = clientinfo.ClientInfo().getXArgsDeviceInfo()
        # For DirectPlay, path/key of PART is needed
        if action == "DirectStream":
            path = self.item[0][self.part].attrib['key']
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
            'session':  clientinfo.ClientInfo().getDeviceId(),
            'fastSeek': 1,
            'path': path,
            'mediaIndex': 0,       # Probably refering to XML reply sheme
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
            self.logMsg("Setting transcode quality to: %s" % quality, 1)
            args.update(quality)
            args.update(argsUpdate)

        url = transcodePath + urlencode(xargs) + '&' + urlencode(args)
        return url

    def externalSubs(self, playurl):
        externalsubs = []
        mapping = {}

        item = self.item
        try:
            mediastreams = item[0][self.part]
        except (TypeError, KeyError, IndexError):
            return

        kodiindex = 0
        for stream in mediastreams:
            index = stream.attrib['id']
            # Since Emby returns all possible tracks together, have to pull
            # only external subtitles.
            key = stream.attrib.get('key')
            # IsTextSubtitleStream if true, is available to download from emby.
            if stream.attrib.get('streamType') == "3" and key:

                # Direct stream
                url = ("%s%s" % (self.server, key))
                url = self.addPlexCredentialsToUrl(url)
                # map external subtitles for mapping
                mapping[kodiindex] = index
                externalsubs.append(url)
                kodiindex += 1
        mapping = json.dumps(mapping)
        utils.window('emby_%s.indexMapping' % playurl, value=mapping)
        self.logMsg('Found external subs: %s' % externalsubs)
        return externalsubs

    def CreateListItemFromPlexItem(self, listItem=None):
        """
        Call on a child level of PMS xml response (e.g. in a for loop)

        listItem:       existing xbmcgui.ListItem to work with
                        otherwise, a new one is created

        Returns XBMC listitem for this PMS library item
        """
        people = self.getPeople()
        userdata = self.getUserData()
        title, sorttitle = self.getTitle()

        if listItem is None:
            listItem = xbmcgui.ListItem()

        metadata = {
            'genre': self.joinList(self.getGenres()),
            'year': self.getYear(),
            'rating': self.getAudienceRating(),
            'playcount': userdata['PlayCount'],
            'cast': people['Cast'],
            'director': self.joinList(people.get('Director')),
            'plot': self.getPlot(),
            'title': title,
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

        if "episode" in self.getType():
            # Only for tv shows
            key, show, season, episode = self.getEpisodeDetails()
            metadata['episode'] = episode
            metadata['season'] = season
            metadata['tvshowtitle'] = show

        listItem.setProperty('IsPlayable', 'true')
        listItem.setProperty('IsFolder', 'false')
        listItem.setProperty('embyid', self.getRatingKey())
        listItem.setLabel(title)
        listItem.setInfo('video', infoLabels=metadata)
        return listItem

    def AddStreamInfo(self, listItem):
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
        types = {
            'movie': 'movie',
            'show': 'tv',
            'season': 'tv',
            'episode': 'tv',
            'artist': 'music',
            'album': 'music',
            'song': 'music',
            'track': 'music',
        }
        typus = types[typus]
        if utils.window('remapSMB') == 'true':
            path = path.replace(utils.window('remapSMB%sOrg' % typus),
                                utils.window('remapSMB%sNew' % typus))
            # There might be backslashes left over:
            path = path.replace('\\', '/')
        elif utils.window('replaceSMB') == 'true':
            if path.startswith('\\\\'):
                path = 'smb:' + path.replace('\\', '/')
        if utils.window('emby_pathverified') == 'true' and forceCheck is False:
            return path

        # exist() needs a / or \ at the end to work for directories
        if folder is False:
            # files
            check = True if xbmcvfs.exists(path.encode('utf-8')) == 1 \
                else False
        else:
            # directories
            if "\\" in path:
                # Add the missing backslash
                check = True if \
                    xbmcvfs.exists((path + "\\").encode('utf-8')) == 1 \
                    else False
            else:
                check = True if \
                    xbmcvfs.exists((path + "/").encode('utf-8')) == 1 \
                    else False

        if check is False:
            if forceCheck is False:
                # Validate the path is correct with user intervention
                if self.askToValidate(path):
                    utils.window('emby_shouldStop', value="true")
                    path = None
                utils.window('emby_pathverified', value='true')
                utils.settings('emby_pathverified', value='true')
            else:
                path = None
        elif forceCheck is False:
            if utils.window('emby_pathverified') != 'true':
                utils.window('emby_pathverified', value='true')
                utils.settings('emby_pathverified', value='true')
        return path

    def askToValidate(self, url):
        """
        Displays a YESNO dialog box:
            Kodi can't locate file: <url>. Please verify the path.
            You may need to verify your network credentials in the
            add-on settings or use different Plex paths. Stop syncing?

        Returns True if sync should stop, else False
        """
        self.logMsg('Cannot access file: %s' % url, -1)
        import xbmcaddon
        string = xbmcaddon.Addon().getLocalizedString
        resp = xbmcgui.Dialog().yesno(
            heading=self.addonName,
            line1=string(39031) + url,
            line2=string(39032))
        return resp
