# -*- coding: utf-8 -*-

###############################################################################

import cProfile
import inspect
import json
import pstats
import sqlite3
from datetime import datetime, timedelta
import StringIO
import time
import unicodedata
import xml.etree.ElementTree as etree
from functools import wraps
from calendar import timegm
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

###############################################################################

addonName = xbmcaddon.Addon().getAddonInfo('name')


def DateToKodi(stamp):
        """
        converts a Unix time stamp (seconds passed sinceJanuary 1 1970) to a
        propper, human-readable time stamp used by Kodi

        Output: Y-m-d h:m:s = 2009-04-05 23:16:04
        """
        # DATEFORMAT = xbmc.getRegion('dateshort')
        # TIMEFORMAT = xbmc.getRegion('meridiem')
        # date_time = time.localtime(stamp)
        # if DATEFORMAT[1] == 'd':
        #     localdate = time.strftime('%d-%m-%Y', date_time)
        # elif DATEFORMAT[1] == 'm':
        #     localdate = time.strftime('%m-%d-%Y', date_time)
        # else:
        #     localdate = time.strftime('%Y-%m-%d', date_time)
        # if TIMEFORMAT != '/':
        #     localtime = time.strftime('%I:%M%p', date_time)
        # else:
        #     localtime = time.strftime('%H:%M', date_time)
        # return localtime + '  ' + localdate
        try:
            # DATEFORMAT = xbmc.getRegion('dateshort')
            # TIMEFORMAT = xbmc.getRegion('meridiem')
            date_time = time.localtime(float(stamp))
            localdate = time.strftime('%Y-%m-%d %H:%M:%S', date_time)
        except:
            localdate = None
        return localdate


def changePlayState(itemType, kodiId, playCount, lastplayed):
    """
    YET UNUSED

    kodiId: int or str
    playCount: int or str
    lastplayed: str or int unix timestamp
    """
    logMsg("changePlayState", "start", 1)
    lastplayed = DateToKodi(lastplayed)

    kodiId = int(kodiId)
    playCount = int(playCount)
    method = {
        'movie': ' VideoLibrary.SetMovieDetails',
        'episode': 'VideoLibrary.SetEpisodeDetails',
        'musicvideo': ' VideoLibrary.SetMusicVideoDetails',  # TODO
        'show': 'VideoLibrary.SetTVShowDetails',  # TODO
        '': 'AudioLibrary.SetAlbumDetails',  # TODO
        '': 'AudioLibrary.SetArtistDetails',  # TODO
        'track': 'AudioLibrary.SetSongDetails'
    }
    params = {
        'movie': {
            'movieid': kodiId,
            'playcount': playCount,
            'lastplayed': lastplayed
        },
        'episode': {
            'episodeid': kodiId,
            'playcount': playCount,
            'lastplayed': lastplayed
        }
    }
    query = {
        "jsonrpc": "2.0",
        "id": 1,
    }
    query['method'] = method[itemType]
    query['params'] = params[itemType]
    result = xbmc.executeJSONRPC(json.dumps(query))
    result = json.loads(result)
    result = result.get('result')
    logMsg("changePlayState", "JSON result was: %s" % result, 1)


def IfExists(path):
    """
    Kodi's xbmcvfs.exists is broken - it caches the results for directories.

    path: path to a directory (with a slash at the end)

    Returns True if path exists, else false
    """
    dummyfile = os.path.join(path, 'dummyfile.txt').encode('utf-8')
    try:
        etree.ElementTree(etree.Element('test')).write(dummyfile)
    except:
        # folder does not exist yet
        answer = False
    else:
        # Folder exists. Delete file again.
        xbmcvfs.delete(dummyfile)
        answer = True
    return answer


def LogTime(func):
    """
    Decorator for functions and methods to log the time it took to run the code
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        starttotal = datetime.now()
        result = func(*args, **kwargs)
        elapsedtotal = datetime.now() - starttotal
        logMsg('%s %s' % (addonName, func.__name__),
               'It took %s to run the function.' % (elapsedtotal), 1)
        return result
    return wrapper


def ThreadMethodsAdditionalStop(windowAttribute):
    """
    Decorator to replace stopThread method to include the Kodi windowAttribute

    Use with any sync threads. @ThreadMethods still required FIRST
    """
    def wrapper(cls):
        def threadStopped(self):
            return (self._threadStopped or
                    (window('plex_terminateNow') == "true") or
                    window(windowAttribute) == "true")
        cls.threadStopped = threadStopped
        return cls
    return wrapper


def ThreadMethodsAdditionalSuspend(windowAttribute):
    """
    Decorator to replace threadSuspended(): thread now also suspends if a
    Kodi windowAttribute is set to 'true', e.g. 'suspend_LibraryThread'

    Use with any library sync threads. @ThreadMethods still required FIRST
    """
    def wrapper(cls):
        def threadSuspended(self):
            return (self._threadSuspended or
                    window(windowAttribute) == 'true')
        cls.threadSuspended = threadSuspended
        return cls
    return wrapper


def ThreadMethods(cls):
    """
    Decorator to add the following methods to a threading class:

    suspendThread():    pauses the thread
    resumeThread():     resumes the thread
    stopThread():       stopps/kills the thread

    threadSuspended():  returns True if thread is suspend_thread
    threadStopped():    returns True if thread is stopped (or should stop ;-))
                        ALSO stops if Kodi is exited

    Also adds the following class attributes:
        _threadStopped
        _threadSuspended
    """
    # Attach new attributes to class
    cls._threadStopped = False
    cls._threadSuspended = False

    # Define new class methods and attach them to class
    def stopThread(self):
        self._threadStopped = True
    cls.stopThread = stopThread

    def suspendThread(self):
        self._threadSuspended = True
    cls.suspendThread = suspendThread

    def resumeThread(self):
        self._threadSuspended = False
    cls.resumeThread = resumeThread

    def threadSuspended(self):
        return self._threadSuspended
    cls.threadSuspended = threadSuspended

    def threadStopped(self):
        return self._threadStopped or (window('plex_terminateNow') == 'true')
    cls.threadStopped = threadStopped

    # Return class to render this a decorator
    return cls


def logging(cls):
    """
    A decorator adding logging capabilities to classes.
    Also adds self.addonName to the class

    Syntax: self.logMsg(message, loglevel)

    Loglevel: -2 (Error) to 2 (DB debug)
    """
    # Attach new attributes to class
    cls.addonName = addonName

    # Define new class methods and attach them to class
    def newFunction(self, msg, lvl=0):
        title = "%s %s" % (addonName, cls.__name__)
        logMsg(title, msg, lvl)
    cls.logMsg = newFunction

    # Return class to render this a decorator
    return cls


def IntFromStr(string):
    """
    Returns an int from string or the int 0 if something happened
    """
    try:
        result = int(string)
    except:
        result = 0
    return result


def getUnixTimestamp(secondsIntoTheFuture=None):
    """
    Returns a Unix time stamp (seconds passed since January 1 1970) for NOW as
    an integer.

    Optionally, pass secondsIntoTheFuture: positive int's will result in a
    future timestamp, negative the past
    """
    if secondsIntoTheFuture:
        future = datetime.utcnow() + timedelta(seconds=secondsIntoTheFuture)
    else:
        future = datetime.utcnow()
    return timegm(future.timetuple())


def logMsg(title, msg, level=1):
    # Get the logLevel set in UserClient
    try:
        logLevel = int(window('emby_logLevel'))
    except ValueError:
        logLevel = 0
    kodiLevel = {
        -1: xbmc.LOGERROR,
        0: xbmc.LOGNOTICE,
        1: xbmc.LOGNOTICE,
        2: xbmc.LOGNOTICE
    }
    if logLevel >= level:
        if logLevel == 2:  # inspect is expensive
            func = inspect.currentframe().f_back.f_back.f_code
            try:
                xbmc.log("%s -> %s : %s" % (
                    title, func.co_name, msg), level=kodiLevel[level])
            except UnicodeEncodeError:
                try:
                    xbmc.log("%s -> %s : %s" % (
                        title, func.co_name, msg.encode('utf-8')),
                        level=kodiLevel[level])
                except:
                    xbmc.log("%s -> %s : %s" % (
                        title, func.co_name, 'COULDNT LOG'),
                        level=kodiLevel[level])
        else:
            try:
                xbmc.log("%s -> %s" % (title, msg), level=kodiLevel[level])
            except UnicodeEncodeError:
                try:
                    xbmc.log("%s -> %s" % (title, msg.encode('utf-8')),
                             level=kodiLevel[level])
                except:
                    xbmc.log("%s -> %s " % (title, 'COULDNT LOG'),
                             level=kodiLevel[level])


def window(property, value=None, clear=False, windowid=10000):
    """
    Get or set window property - thread safe!

    Returns unicode.

    Property needs to be string; value may be string or unicode
    """
    WINDOW = xbmcgui.Window(windowid)
    
    #setproperty accepts both string and unicode but utf-8 strings are adviced by kodi devs because some unicode can give issues
    '''if isinstance(property, unicode):
        property = property.encode("utf-8")
    if isinstance(value, unicode):
        value = value.encode("utf-8")'''
    if clear:
        WINDOW.clearProperty(property)
    elif value is not None:
        WINDOW.setProperty(property, value.encode('utf-8'))
    else:
        return WINDOW.getProperty(property).decode('utf-8')

def settings(setting, value=None):
    """
    Get or add addon setting. Returns unicode

    Settings needs to be string
    Value can either be unicode or string
    """
    addon = xbmcaddon.Addon(id='plugin.video.plexkodiconnect')

    if value is not None:
        # Takes string or unicode by default!
        addon.setSetting(setting, value.encode('utf-8'))
    else:
        # Should return unicode by default, but just in case
        return addon.getSetting(setting).decode('utf-8')

def language(stringid):
    # Central string retrieval
    addon = xbmcaddon.Addon(id='plugin.video.plexkodiconnect')
    string = addon.getLocalizedString(stringid) #returns unicode object
    return string

def kodiSQL(type="video"):
    
    if type == "emby":
        dbPath = xbmc.translatePath("special://database/emby.db").decode('utf-8')
    elif type == "music":
        dbPath = getKodiMusicDBPath()
    elif type == "texture":
        dbPath = xbmc.translatePath("special://database/Textures13.db").decode('utf-8')
    else:
        dbPath = getKodiVideoDBPath()
    
    connection = sqlite3.connect(dbPath)
    return connection

def getKodiVideoDBPath():

    kodibuild = xbmc.getInfoLabel('System.BuildVersion')[:2]
    dbVersion = {

        "13": 78,   # Gotham
        "14": 90,   # Helix
        "15": 93,   # Isengard
        "16": 99,   # Jarvis
	"17":104    # Krypton
    }

    dbPath = xbmc.translatePath(
                    "special://database/MyVideos%s.db"
                    % dbVersion.get(kodibuild, "")).decode('utf-8')
    return dbPath

def getKodiMusicDBPath():

    kodibuild = xbmc.getInfoLabel('System.BuildVersion')[:2]
    dbVersion = {

        "13": 46,   # Gotham
        "14": 48,   # Helix
        "15": 52,   # Isengard
        "16": 56,   # Jarvis
        "17": 60    # Krypton
    }

    dbPath = xbmc.translatePath(
                    "special://database/MyMusic%s.db"
                    % dbVersion.get(kodibuild, "")).decode('utf-8')
    return dbPath

def getScreensaver():
    # Get the current screensaver value
    query = {

        'jsonrpc': "2.0",
        'id': 0,
        'method': "Settings.getSettingValue",
        'params': {

            'setting': "screensaver.mode"
        }
    }
    result = xbmc.executeJSONRPC(json.dumps(query))
    result = json.loads(result)
    screensaver = result['result']['value']

    return screensaver

def setScreensaver(value):
    # Toggle the screensaver
    query = {

        'jsonrpc': "2.0",
        'id': 0,
        'method': "Settings.setSettingValue",
        'params': {

            'setting': "screensaver.mode",
            'value': value
        }
    }
    result = xbmc.executeJSONRPC(json.dumps(query))
    logMsg("PLEX", "Toggling screensaver: %s %s" % (value, result), 1)    

def reset():

    dialog = xbmcgui.Dialog()

    resp = dialog.yesno("Warning", "Are you sure you want to reset your local Kodi database?")
    if resp == 0:
        return

    # first stop any db sync
    window('emby_shouldStop', value="true")
    count = 10
    while window('emby_dbScan') == "true":
        logMsg("PLEX", "Sync is running, will retry: %s..." % count)
        count -= 1
        if count == 0:
            dialog.ok("Warning", "Could not stop the database from running. Try again.")
            return
        xbmc.sleep(1000)

    # Clean up the playlists
    deletePlaylists()

    # Clean up the video nodes
    deleteNodes()

    # Wipe the kodi databases
    logMsg("EMBY", "Resetting the Kodi video database.", 0)
    connection = kodiSQL('video')
    cursor = connection.cursor()
    cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
    rows = cursor.fetchall()
    for row in rows:
        tablename = row[0]
        if tablename != "version":
            cursor.execute("DELETE FROM " + tablename)
    connection.commit()
    cursor.close()

    if settings('enableMusic') == "true":
        logMsg("EMBY", "Resetting the Kodi music database.")
        connection = kodiSQL('music')
        cursor = connection.cursor()
        cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
        rows = cursor.fetchall()
        for row in rows:
            tablename = row[0]
            if tablename != "version":
                cursor.execute("DELETE FROM " + tablename)
        connection.commit()
        cursor.close()

    # Wipe the emby database
    logMsg("EMBY", "Resetting the Emby database.", 0)
    connection = kodiSQL('emby')
    cursor = connection.cursor()
    cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
    rows = cursor.fetchall()
    for row in rows:
        tablename = row[0]
        if tablename != "version":
            cursor.execute("DELETE FROM " + tablename)
    cursor.execute('DROP table IF EXISTS emby')
    cursor.execute('DROP table IF EXISTS view')
    connection.commit()
    cursor.close()

    # Offer to wipe cached thumbnails
    resp = dialog.yesno("Warning", "Removed all cached artwork?")
    if resp:
        logMsg("EMBY", "Resetting all cached artwork.", 0)
        # Remove all existing textures first
        path = xbmc.translatePath("special://thumbnails/").decode('utf-8')
        if xbmcvfs.exists(path):
            allDirs, allFiles = xbmcvfs.listdir(path)
            for dir in allDirs:
                allDirs, allFiles = xbmcvfs.listdir(path+dir)
                for file in allFiles:
                    if os.path.supports_unicode_filenames:
                        xbmcvfs.delete(os.path.join(path+dir.decode('utf-8'),file.decode('utf-8')))
                    else:
                        xbmcvfs.delete(os.path.join(path.encode('utf-8')+dir,file))
        
        # remove all existing data from texture DB
        connection = kodiSQL('texture')
        cursor = connection.cursor()
        cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
        rows = cursor.fetchall()
        for row in rows:
            tableName = row[0]
            if(tableName != "version"):
                cursor.execute("DELETE FROM " + tableName)
        connection.commit()
        cursor.close()
    
    # reset the install run flag  
    settings('SyncInstallRunDone', value="false")

    # Remove emby info
    resp = dialog.yesno("Warning", "Reset all Emby Addon settings?")
    if resp:
        # Delete the settings
        addon = xbmcaddon.Addon()
        addondir = xbmc.translatePath(addon.getAddonInfo('profile')).decode('utf-8')
        dataPath = "%ssettings.xml" % addondir
        xbmcvfs.delete(dataPath.encode('utf-8'))
        logMsg("PLEX", "Deleting: settings.xml", 1)

    dialog.ok(
        heading=addonName,
        line1="Database reset has completed, Kodi will now restart to apply the changes.")
    xbmc.executebuiltin('RestartApp')

def profiling(sortby="cumulative"):
    # Will print results to Kodi log
    def decorator(func):
        def wrapper(*args, **kwargs):
            
            pr = cProfile.Profile()

            pr.enable()
            result = func(*args, **kwargs)
            pr.disable()

            s = StringIO.StringIO()
            ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
            ps.print_stats()
            logMsg("EMBY Profiling", s.getvalue(), 1)

            return result

        return wrapper
    return decorator

def convertdate(date):
    try:
        date = datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")
    except TypeError:
        # TypeError: attribute of type 'NoneType' is not callable
        # Known Kodi/python error
        date = datetime(*(time.strptime(date, "%Y-%m-%dT%H:%M:%SZ")[0:6]))

    return date

def normalize_nodes(text):
    # For video nodes
    text = text.replace(":", "")
    text = text.replace("/", "-")
    text = text.replace("\\", "-")
    text = text.replace("<", "")
    text = text.replace(">", "")
    text = text.replace("*", "")
    text = text.replace("?", "")
    text = text.replace('|', "")
    text = text.replace('(', "")
    text = text.replace(')', "")
    text = text.strip()
    # Remove dots from the last character as windows can not have directories
    # with dots at the end
    text = text.rstrip('.')
    text = unicodedata.normalize('NFKD', unicode(text, 'utf-8')).encode('ascii', 'ignore')
    
    return text

def normalize_string(text):
    # For theme media, do not modify unless
    # modified in TV Tunes
    text = text.replace(":", "")
    text = text.replace("/", "-")
    text = text.replace("\\", "-")
    text = text.replace("<", "")
    text = text.replace(">", "")
    text = text.replace("*", "")
    text = text.replace("?", "")
    text = text.replace('|', "")
    text = text.strip()
    # Remove dots from the last character as windows can not have directories
    # with dots at the end
    text = text.rstrip('.')
    text = unicodedata.normalize('NFKD', unicode(text, 'utf-8')).encode('ascii', 'ignore')

    return text

def indent(elem, level=0):
    # Prettify xml trees
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
          elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
          elem.tail = i
        for elem in elem:
          indent(elem, level+1)
        if not elem.tail or not elem.tail.strip():
          elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
          elem.tail = i


def musiclibXML():
    """
    Deactivates Kodi trying to scan music library on startup

    Changes guisettings.xml in Kodi userdata folder:
        updateonstartup:        set to "false"
    """
    path = xbmc.translatePath("special://profile/").decode('utf-8')
    xmlpath = "%sguisettings.xml" % path

    try:
        xmlparse = etree.parse(xmlpath)
    except:
        # Document is blank or missing
        root = etree.Element('settings')
    else:
        root = xmlparse.getroot()

    music = root.find('musiclibrary')
    if music is None:
        music = etree.SubElement(root, 'musiclibrary')

    startup = music.find('updateonstartup')
    if startup is None:
        # Setting does not exist yet; create it
        startup = etree.SubElement(music,
                                   'updateonstartup',
                                   attrib={'default': "true"}).text = "false"
    else:
        startup.text = "false"

    # Prettify and write to file
    try:
        indent(root)
    except:
        pass
    etree.ElementTree(root).write(xmlpath)


def advancedSettingsXML():
    """
    Deactivates Kodi popup for scanning of music library

    Changes advancedsettings.xml, musiclibrary:
        backgroundupdate        set to "true"
    """
    path = xbmc.translatePath("special://profile/").decode('utf-8')
    xmlpath = "%sadvancedsettings.xml" % path

    try:
        xmlparse = etree.parse(xmlpath)
    except:
        # Document is blank or missing
        root = etree.Element('advancedsettings')
    else:
        root = xmlparse.getroot()

    music = root.find('musiclibrary')
    if music is None:
        music = etree.SubElement(root, 'musiclibrary')

    backgroundupdate = music.find('backgroundupdate')
    if backgroundupdate is None:
        # Setting does not exist yet; create it
        backgroundupdate = etree.SubElement(
            music,
            'backgroundupdate').text = "true"
    else:
        backgroundupdate.text = "true"

    # Prettify and write to file
    try:
        indent(root)
    except:
        pass
    etree.ElementTree(root).write(xmlpath)


def sourcesXML():
    # To make Master lock compatible
    path = xbmc.translatePath("special://profile/").decode('utf-8')
    xmlpath = "%ssources.xml" % path

    try:
        xmlparse = etree.parse(xmlpath)
    except: # Document is blank or missing
        root = etree.Element('sources')
    else:
        root = xmlparse.getroot()
        

    video = root.find('video')
    if video is None:
        video = etree.SubElement(root, 'video')
        etree.SubElement(video, 'default', attrib={'pathversion': "1"})

    # Add elements
    count = 2
    for source in root.findall('.//path'):
        if source.text == "smb://":
            count -= 1
        
        if count == 0:
            # sources already set
            break
    else:
        # Missing smb:// occurences, re-add.
        for i in range(0, count):
            source = etree.SubElement(video, 'source')
            etree.SubElement(source, 'name').text = "Emby"
            etree.SubElement(source, 'path', attrib={'pathversion': "1"}).text = "smb://"
            etree.SubElement(source, 'allowsharing').text = "true"
    # Prettify and write to file
    try:
        indent(root)
    except: pass
    etree.ElementTree(root).write(xmlpath)


def passwordsXML():
    # To add network credentials
    path = xbmc.translatePath("special://userdata/").decode('utf-8')
    xmlpath = "%spasswords.xml" % path
    logMsg('passwordsXML', 'Path to passwords.xml: %s' % xmlpath, 1)

    try:
        xmlparse = etree.parse(xmlpath)
    except: # Document is blank or missing
        root = etree.Element('passwords')
        skipFind = True
    else:
        root = xmlparse.getroot()
        skipFind = False

    dialog = xbmcgui.Dialog()
    credentials = settings('networkCreds')
    if credentials:
        # Present user with options
        option = dialog.select(
            "Modify/Remove network credentials", ["Modify", "Remove"])

        if option < 0:
            # User cancelled dialog
            return

        elif option == 1:
            # User selected remove
            iterator = root.getiterator('passwords')

            for paths in iterator:
                for path in paths:
                    if path.find('.//from').text == "smb://%s/" % credentials:
                        paths.remove(path)
                        logMsg("passwordsXML",
                               "Successfully removed credentials for: %s"
                               % credentials, 1)
                        etree.ElementTree(root).write(xmlpath)
                        break
            else:
                logMsg("EMBY", "Failed to find saved server: %s in passwords.xml" % credentials, 1)
            
            settings('networkCreds', value="")
            xbmcgui.Dialog().notification(
                heading='PlexKodiConnect',
                message="%s removed from passwords.xml" % credentials,
                icon="special://home/addons/plugin.video.plexkodiconnect/icon.png",
                time=1000,
                sound=False)
            return

        elif option == 0:
            # User selected to modify
            server = dialog.input("Modify the computer name or ip address", credentials)
            if not server:
                return
    else:
        # No credentials added
        dialog.ok(
            heading="Network credentials",
            line1= (
                "Input the server name or IP address as indicated in your plex library paths. "
                'For example, the server name: \\\\SERVER-PC\\path\\ or smb://SERVER-PC/path is "SERVER-PC".'))
        server = dialog.input("Enter the server name or IP address")
        if not server:
            return

    # Network username
    user = dialog.input("Enter the network username")
    if not user:
        return
    # Network password
    password = dialog.input("Enter the network password",
                            '',  # Default input
                            xbmcgui.INPUT_ALPHANUM,
                            xbmcgui.ALPHANUM_HIDE_INPUT)

    # Add elements. Annoying etree bug where findall hangs forever
    if skipFind is False:
        skipFind = True
        for path in root.findall('.//path'):
            if path.find('.//from').text.lower() == "smb://%s/" % server.lower():
                # Found the server, rewrite credentials
                path.find('.//to').text = "smb://%s:%s@%s/" % (user, password, server)
                skipFind = False
                break
    if skipFind:
        # Server not found, add it.
        path = etree.SubElement(root, 'path')
        etree.SubElement(path, 'from', attrib={'pathversion': "1"}).text = "smb://%s/" % server
        topath = "smb://%s:%s@%s/" % (user, password, server)
        etree.SubElement(path, 'to', attrib={'pathversion': "1"}).text = topath
        # Force Kodi to see the credentials without restarting
        xbmcvfs.exists(topath)

    # Add credentials    
    settings('networkCreds', value="%s" % server)
    logMsg("PLEX", "Added server: %s to passwords.xml" % server, 1)
    # Prettify and write to file
    try:
        indent(root)
    except: pass
    etree.ElementTree(root).write(xmlpath)
    
    # dialog.notification(
    #     heading="PlexKodiConnect",
    #     message="Added to passwords.xml",
    #     icon="special://home/addons/plugin.video.plexkodiconnect/icon.png",
    #     time=5000,
    #     sound=False)

def playlistXSP(mediatype, tagname, viewid, viewtype="", delete=False):
    """
    Feed with tagname as unicode
    """
    path = xbmc.translatePath("special://profile/playlists/video/").decode('utf-8')
    if viewtype == "mixed":
        plname = "%s - %s" % (tagname, mediatype)
        xsppath = "%sPlex %s - %s.xsp" % (path, viewid, mediatype)
    else:
        plname = tagname
        xsppath = "%sPlex %s.xsp" % (path, viewid)

    # Create the playlist directory
    if not xbmcvfs.exists(path.encode('utf-8')):
        logMsg("PLEX", "Creating directory: %s" % path, 1)
        xbmcvfs.mkdirs(path.encode('utf-8'))

    # Only add the playlist if it doesn't already exists
    if xbmcvfs.exists(xsppath.encode('utf-8')):
        logMsg('Path %s does exist' % xsppath, 1)
        if delete:
            xbmcvfs.delete(xsppath.encode('utf-8'))
            logMsg("PLEX", "Successfully removed playlist: %s." % tagname, 1)
        
        return

    # Using write process since there's no guarantee the xml declaration works with etree
    itemtypes = {
        'homevideos': "movie"
    }
    logMsg("Plex", "Writing playlist file to: %s" % xsppath, 1)
    try:
        f = xbmcvfs.File(xsppath.encode('utf-8'), 'wb')
    except:
        logMsg("Plex", "Failed to create playlist: %s" % xsppath, -1)
        return
    else:
        f.write((
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            '<smartplaylist type="%s">\n\t'
                '<name>Plex %s</name>\n\t'
                '<match>all</match>\n\t'
                '<rule field="tag" operator="is">\n\t\t'
                    '<value>%s</value>\n\t'
                '</rule>\n'
            '</smartplaylist>'
            % (itemtypes.get(mediatype, mediatype), plname, tagname))
            .encode('utf-8'))
        f.close()
    logMsg("Plex", "Successfully added playlist: %s" % tagname)

def deletePlaylists():

    # Clean up the playlists
    path = xbmc.translatePath("special://profile/playlists/video/").decode('utf-8')
    dirs, files = xbmcvfs.listdir(path.encode('utf-8'))
    for file in files:
        if file.decode('utf-8').startswith('Plex'):
            xbmcvfs.delete(("%s%s" % (path, file.decode('utf-8'))).encode('utf-8'))

def deleteNodes():

    # Clean up video nodes
    import shutil
    path = xbmc.translatePath("special://profile/library/video/").decode('utf-8')
    dirs, files = xbmcvfs.listdir(path.encode('utf-8'))
    for dir in dirs:
        if dir.decode('utf-8').startswith('Plex'):
            try:
                shutil.rmtree("%s%s" % (path, dir.decode('utf-8')))
            except:
                logMsg("PLEX", "Failed to delete directory: %s" % dir.decode('utf-8'))
    for file in files:
        if file.decode('utf-8').startswith('plex'):
            try:
                xbmcvfs.delete(("%s%s" % (path, file.decode('utf-8'))).encode('utf-8'))
            except:
                logMsg("PLEX", "Failed to file: %s" % file.decode('utf-8'))