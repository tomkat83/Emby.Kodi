#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Various functions and decorators for PKC
"""
from __future__ import absolute_import, division, unicode_literals
from logging import getLogger
from cProfile import Profile
from pstats import Stats
from sqlite3 import connect, OperationalError
from datetime import datetime, timedelta
from StringIO import StringIO
from time import localtime, strftime
from unicodedata import normalize
import xml.etree.ElementTree as etree
from functools import wraps, partial
from urllib import quote_plus
import hashlib
import re
import xbmc
import xbmcaddon
import xbmcgui

from . import path_ops
from . import variables as v
from . import state

###############################################################################

LOG = getLogger('PLEX.utils')

WINDOW = xbmcgui.Window(10000)
ADDON = xbmcaddon.Addon(id='plugin.video.plexkodiconnect')
EPOCH = datetime.utcfromtimestamp(0)

# Grab Plex id from '...plex_id=XXXX....'
REGEX_PLEX_ID = re.compile(r'''plex_id=(\d+)''')
# Return the numbers at the end of an url like '.../.../XXXX'
REGEX_END_DIGITS = re.compile(r'''/(.+)/(\d+)$''')
REGEX_PLEX_DIRECT = re.compile(r'''\.plex\.direct:\d+$''')
REGEX_FILE_NUMBERING = re.compile(r'''_(\d+)\.\w+$''')
# Plex API
REGEX_IMDB = re.compile(r'''/(tt\d+)''')
REGEX_TVDB = re.compile(r'''thetvdb:\/\/(.+?)\?''')
# Plex music
REGEX_MUSICPATH = re.compile(r'''^\^(.+)\$$''')
# Grab Plex id from an URL-encoded string
REGEX_PLEX_ID_FROM_URL = re.compile(r'''metadata%2F(\d+)''')

###############################################################################
# Main methods


def reboot_kodi(message=None):
    """
    Displays an OK prompt with 'Kodi will now restart to apply the changes'
    Kodi will then reboot.

    Set optional custom message
    """
    message = message or lang(33033)
    dialog('ok', heading='{plex}', line1=message)
    xbmc.executebuiltin('RestartApp')


def window(prop, value=None, clear=False, windowid=10000):
    """
    Get or set window property - thread safe!

    Returns unicode.

    Property and value may be string or unicode
    """
    if windowid != 10000:
        win = xbmcgui.Window(windowid)
    else:
        win = WINDOW

    if clear:
        win.clearProperty(prop)
    elif value is not None:
        win.setProperty(try_encode(prop), try_encode(value))
    else:
        return try_decode(win.getProperty(prop))


def plex_command(key, value):
    """
    Used to funnel states between different Python instances. NOT really thread
    safe - let's hope the Kodi user can't click fast enough

        key:   state.py variable
        value: either 'True' or 'False'
    """
    while window('plex_command'):
        xbmc.sleep(20)
    window('plex_command', value='%s-%s' % (key, value))


def settings(setting, value=None):
    """
    Get or add addon setting. Returns unicode

    setting and value can either be unicode or string
    """
    # We need to instantiate every single time to read changed variables!
    addon = xbmcaddon.Addon(id='plugin.video.plexkodiconnect')
    if value is not None:
        # Takes string or unicode by default!
        addon.setSetting(try_encode(setting), try_encode(value))
    else:
        # Should return unicode by default, but just in case
        return try_decode(addon.getSetting(setting))


def lang(stringid):
    """
    Central string retrieval from strings.po. If not found within PKC,
    standard XBMC/Kodi strings are retrieved.
    Will return unicode
    """
    return (ADDON.getLocalizedString(stringid) or
            xbmc.getLocalizedString(stringid))


def dialog(typus, *args, **kwargs):
    """
    Displays xbmcgui Dialog. Pass a string as typus:
        'yesno', 'ok', 'notification', 'input', 'select', 'numeric'
    kwargs:
        heading='{plex}'        title bar (here PlexKodiConnect)
        message=lang(30128),    Dialog content. Don't use with 'OK', 'yesno'
        line1=str(),            For 'OK' and 'yesno' dialogs use line1...line3!
        time=5000,
        sound=True,
        nolabel=str(),          For 'yesno' dialogs
        yeslabel=str(),         For 'yesno' dialogs
    Icons:
        icon='{plex}'       Display Plex standard icon
        icon='{info}'       xbmcgui.NOTIFICATION_INFO
        icon='{warning}'    xbmcgui.NOTIFICATION_WARNING
        icon='{error}'      xbmcgui.NOTIFICATION_ERROR
    Input Types:
        type='{alphanum}'   xbmcgui.INPUT_ALPHANUM (standard keyboard)
        type='{numeric}'    xbmcgui.INPUT_NUMERIC (format: #)
        type='{date}'       xbmcgui.INPUT_DATE (format: DD/MM/YYYY)
        type='{time}'       xbmcgui.INPUT_TIME (format: HH:MM)
        type='{ipaddress}'  xbmcgui.INPUT_IPADDRESS (format: #.#.#.#)
        type='{password}'   xbmcgui.INPUT_PASSWORD
                            (return md5 hash of input, input is masked)
    Options:
        option='{password}' xbmcgui.PASSWORD_VERIFY (verifies an existing
                            (default) md5 hashed password)
        option='{hide}'     xbmcgui.ALPHANUM_HIDE_INPUT (masks input)
    """
    if 'icon' in kwargs:
        types = {
            '{plex}': 'special://home/addons/plugin.video.plexkodiconnect/icon.png',
            '{info}': xbmcgui.NOTIFICATION_INFO,
            '{warning}': xbmcgui.NOTIFICATION_WARNING,
            '{error}': xbmcgui.NOTIFICATION_ERROR
        }
        for key, value in types.iteritems():
            kwargs['icon'] = kwargs['icon'].replace(key, value)
    if 'type' in kwargs:
        types = {
            '{alphanum}': xbmcgui.INPUT_ALPHANUM,
            '{numeric}': xbmcgui.INPUT_NUMERIC,
            '{date}': xbmcgui.INPUT_DATE,
            '{time}': xbmcgui.INPUT_TIME,
            '{ipaddress}': xbmcgui.INPUT_IPADDRESS,
            '{password}': xbmcgui.INPUT_PASSWORD
        }
        kwargs['type'] = types[kwargs['type']]
    if 'option' in kwargs:
        types = {
            '{password}': xbmcgui.PASSWORD_VERIFY,
            '{hide}': xbmcgui.ALPHANUM_HIDE_INPUT
        }
        kwargs['option'] = types[kwargs['option']]
    if 'heading' in kwargs:
        kwargs['heading'] = kwargs['heading'].replace("{plex}",
                                                      lang(29999))
    dia = xbmcgui.Dialog()
    types = {
        'yesno': dia.yesno,
        'ok': dia.ok,
        'notification': dia.notification,
        'input': dia.input,
        'select': dia.select,
        'numeric': dia.numeric
    }
    return types[typus](*args, **kwargs)


def millis_to_kodi_time(milliseconds):
    """
    Converts time in milliseconds to the time dict used by the Kodi JSON RPC:
    {
        'hours': [int],
        'minutes': [int],
        'seconds'[int],
        'milliseconds': [int]
    }
    Pass in the time in milliseconds as an int
    """
    seconds = milliseconds / 1000
    minutes = seconds / 60
    hours = minutes / 60
    seconds = seconds % 60
    minutes = minutes % 60
    milliseconds = milliseconds % 1000
    return {'hours': hours,
            'minutes': minutes,
            'seconds': seconds,
            'milliseconds': milliseconds}


def kodi_time_to_millis(time):
    """
    Converts the Kodi time dict
    {
        'hours': [int],
        'minutes': [int],
        'seconds'[int],
        'milliseconds': [int]
    }
    to milliseconds [int]. Will not return negative results but 0!
    """
    ret = (time['hours'] * 3600 +
           time['minutes'] * 60 +
           time['seconds']) * 1000 + time['milliseconds']
    ret = 0 if ret < 0 else ret
    return ret


def try_encode(input_str, encoding='utf-8'):
    """
    Will try to encode input_str (in unicode) to encoding. This possibly
    fails with e.g. Android TV's Python, which does not accept arguments for
    string.encode()
    """
    if isinstance(input_str, str):
        # already encoded
        return input_str
    try:
        input_str = input_str.encode(encoding, "ignore")
    except TypeError:
        input_str = input_str.encode()
    return input_str


def try_decode(string, encoding='utf-8'):
    """
    Will try to decode string (encoded) using encoding. This possibly
    fails with e.g. Android TV's Python, which does not accept arguments for
    string.encode()
    """
    if isinstance(string, unicode):
        # already decoded
        return string
    try:
        string = string.decode(encoding, "ignore")
    except TypeError:
        string = string.decode()
    return string


def slugify(text):
    """
    Normalizes text (in unicode or string) to e.g. enable safe filenames.
    Returns unicode
    """
    if not isinstance(text, unicode):
        text = unicode(text)
    return unicode(normalize('NFKD', text).encode('ascii', 'ignore'))


def valid_filename(text):
    """
    Return a valid filename after passing it in [unicode].
    """
    # Get rid of all whitespace except a normal space
    text = re.sub(r'(?! )\s', '', text)
    # ASCII characters 0 to 31 (non-printable, just in case)
    text = re.sub(u'[\x00-\x1f]', '', text)
    if v.PLATFORM == 'Windows':
        # Whitespace at the end of the filename is illegal
        text = text.strip()
        # Dot at the end of a filename is illegal
        text = re.sub(r'\.+$', '', text)
        # Illegal Windows characters
        text = re.sub(r'[/\\:*?"<>|\^]', '', text)
    elif v.PLATFORM == 'MacOSX':
        # Colon is illegal
        text = re.sub(r':', '', text)
        # Files cannot begin with a dot
        text = re.sub(r'^\.+', '', text)
    else:
        # Linux
        text = re.sub(r'/', '', text)
    # Ensure that filename length is at most 255 chars (including 3 chars for
    # filename extension and 1 dot to separate the extension)
    text = text[:min(len(text), 251)]
    return text


def escape_html(string):
    """
    Escapes the following:
        < to &lt;
        > to &gt;
        & to &amp;
    """
    escapes = {
        '<': '&lt;',
        '>': '&gt;',
        '&': '&amp;'
    }
    for key, value in escapes.iteritems():
        string = string.replace(key, value)
    return string


def unix_date_to_kodi(stamp):
    """
    converts a Unix time stamp (seconds passed sinceJanuary 1 1970) to a
    propper, human-readable time stamp used by Kodi

    Output: Y-m-d h:m:s = 2009-04-05 23:16:04

    None if an error was encountered
    """
    try:
        stamp = float(stamp) + state.KODI_PLEX_TIME_OFFSET
        date_time = localtime(stamp)
        localdate = strftime('%Y-%m-%d %H:%M:%S', date_time)
    except:
        localdate = None
    return localdate


def unix_timestamp(seconds_into_the_future=None):
    """
    Returns a Unix time stamp (seconds passed since January 1 1970) for NOW as
    an integer.

    Optionally, pass seconds_into_the_future: positive int's will result in a
    future timestamp, negative the past
    """
    if seconds_into_the_future:
        future = datetime.utcnow() + timedelta(seconds=seconds_into_the_future)
    else:
        future = datetime.utcnow()
    return int((future - EPOCH).total_seconds())


def kodi_sql(media_type=None):
    """
    Open a connection to the Kodi database.
        media_type: 'video' (standard if not passed), 'plex', 'music', 'texture'
    """
    if media_type == "plex":
        db_path = v.DB_PLEX_PATH
    elif media_type == "music":
        db_path = v.DB_MUSIC_PATH
    elif media_type == "texture":
        db_path = v.DB_TEXTURE_PATH
    else:
        db_path = v.DB_VIDEO_PATH
    return connect(db_path, timeout=60.0)


def create_actor_db_index():
    """
    Index the "actors" because we got a TON - speed up SELECT and WHEN
    """
    conn = kodi_sql('video')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX index_name
            ON actor (name);
        """)
    except OperationalError:
        # Index already exists
        pass
    conn.commit()
    conn.close()


def wipe_database():
    """
    Deletes all Plex playlists as well as video nodes, then clears Kodi as well
    as Plex databases completely.
    Will also delete all cached artwork.
    """
    # Clean up the playlists
    delete_playlists()
    # Clean up the video nodes
    delete_nodes()

    # Wipe the kodi databases
    LOG.info("Resetting the Kodi video database.")
    connection = kodi_sql('video')
    cursor = connection.cursor()
    cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
    rows = cursor.fetchall()
    for row in rows:
        tablename = row[0]
        if tablename != "version":
            cursor.execute("DELETE FROM %s" % tablename)
    connection.commit()
    cursor.close()

    if settings('enableMusic') == "true":
        LOG.info("Resetting the Kodi music database.")
        connection = kodi_sql('music')
        cursor = connection.cursor()
        cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
        rows = cursor.fetchall()
        for row in rows:
            tablename = row[0]
            if tablename != "version":
                cursor.execute("DELETE FROM %s" % tablename)
        connection.commit()
        cursor.close()

    # Wipe the Plex database
    LOG.info("Resetting the Plex database.")
    connection = kodi_sql('plex')
    cursor = connection.cursor()
    # First get the paths to all synced playlists
    playlist_paths = []
    cursor.execute('SELECT kodi_path FROM playlists')
    for entry in cursor.fetchall():
        playlist_paths.append(entry[0])
    cursor.execute('SELECT tbl_name FROM sqlite_master WHERE type="table"')
    rows = cursor.fetchall()
    for row in rows:
        tablename = row[0]
        if tablename != "version":
            cursor.execute("DELETE FROM %s" % tablename)
    connection.commit()
    cursor.close()

    # Delete all synced playlists
    for path in playlist_paths:
        try:
            path_ops.remove(path)
        except (OSError, IOError):
            pass

    LOG.info("Resetting all cached artwork.")
    # Remove all existing textures first
    path = path_ops.translate_path("special://thumbnails/")
    if path_ops.exists(path):
        path_ops.rmtree(path, ignore_errors=True)
    # remove all existing data from texture DB
    connection = kodi_sql('texture')
    cursor = connection.cursor()
    query = 'SELECT tbl_name FROM sqlite_master WHERE type=?'
    cursor.execute(query, ("table", ))
    rows = cursor.fetchall()
    for row in rows:
        table_name = row[0]
        if table_name != "version":
            cursor.execute("DELETE FROM %s" % table_name)
    connection.commit()
    cursor.close()
    # reset the install run flag
    settings('SyncInstallRunDone', value="false")


def reset(ask_user=True):
    """
    User navigated to the PKC settings, Advanced, and wants to reset the Kodi
    database and possibly PKC entirely
    """
    # Are you sure you want to reset your local Kodi database?
    if ask_user and not dialog('yesno',
                               heading='{plex} %s ' % lang(30132),
                               line1=lang(39600)):
        return

    # first stop any db sync
    plex_command('STOP_SYNC', 'True')
    count = 10
    while window('plex_dbScan') == "true":
        LOG.debug("Sync is running, will retry: %s...", count)
        count -= 1
        if count == 0:
            # Could not stop the database from running. Please try again later.
            dialog('ok',
                   heading='{plex} %s' % lang(30132),
                   line1=lang(39601))
            return
        xbmc.sleep(1000)

    # Wipe everything
    wipe_database()

    # Reset all PlexKodiConnect Addon settings? (this is usually NOT
    # recommended and unnecessary!)
    if ask_user and dialog('yesno',
                           heading='{plex} %s ' % lang(30132),
                           line1=lang(39603)):
        # Delete the settings
        LOG.info("Deleting: settings.xml")
        path_ops.remove("%ssettings.xml" % v.ADDON_PROFILE)
    reboot_kodi()


def profiling(sortby="cumulative"):
    """
    Will print results to Kodi log. Must be enabled in the Python source code
    """
    def decorator(func):
        """
        decorator construct
        """
        def wrapper(*args, **kwargs):
            """
            wrapper construct
            """
            profile = Profile()
            profile.enable()
            result = func(*args, **kwargs)
            profile.disable()
            string_io = StringIO()
            stats = Stats(profile, stream=string_io).sort_stats(sortby)
            stats.print_stats()
            LOG.info(string_io.getvalue())
            return result
        return wrapper
    return decorator


def compare_version(current, minimum):
    """
    Returns True if current is >= then minimum. False otherwise. Returns True
    if there was no valid input for current!

    Input strings: e.g. "1.2.3"; always with Major, Minor and Patch!
    """
    LOG.info("current DB: %s minimum DB: %s", current, minimum)
    try:
        curr_major, curr_minor, curr_patch = current.split(".")
    except ValueError:
        # there WAS no current DB, e.g. deleted.
        return True
    min_major, min_minor, min_patch = minimum.split(".")
    curr_major = int(curr_major)
    curr_minor = int(curr_minor)
    curr_patch = int(curr_patch)
    min_major = int(min_major)
    min_minor = int(min_minor)
    min_patch = int(min_patch)

    if curr_major > min_major:
        return True
    elif curr_major < min_major:
        return False

    if curr_minor > min_minor:
        return True
    elif curr_minor < min_minor:
        return False
    return curr_patch >= min_patch


def normalize_string(text):
    """
    For theme media, do not modify unless modified in TV Tunes
    """
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
    text = try_encode(normalize('NFKD', unicode(text, 'utf-8')))

    return text


def normalize_nodes(text):
    """
    For video nodes. Returns unicode
    """
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
    text = normalize('NFKD', unicode(text, 'utf-8'))
    return text


def indent(elem, level=0):
    """
    Prettifies xml trees. Pass the etree root in
    """
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


class XmlKodiSetting(object):
    """
    Used to load a Kodi XML settings file from special://profile as an etree
    object to read settings or set them. Usage:
        with XmlKodiSetting(filename,
                            path=None,
                            force_create=False,
                            top_element=None) as xml:
            xml.get_setting('test')

    filename [str]:      filename of the Kodi settings file under
    path [str]:          if set, replace special://profile path with custom
                         path
    force_create:        will create the XML file if it does not exist
    top_element [str]:   Name of the top xml element; used if xml does not
                         yet exist

    Raises IOError if the file does not exist or is empty and force_create
    has been set to False.
    Raises etree.ParseError if the file could not be parsed by etree

    xml.write_xml        Set to True if we need to write the XML to disk
    """
    def __init__(self, filename, path=None, force_create=False,
                 top_element=None):
        self.filename = filename
        if path is None:
            self.path = path_ops.path.join(v.KODI_PROFILE, filename)
        else:
            self.path = path_ops.path.join(path, filename)
        self.force_create = force_create
        self.top_element = top_element
        self.tree = None
        self.root = None
        self.write_xml = False

    def __enter__(self):
        try:
            self.tree = etree.parse(self.path)
        except IOError:
            # Document is blank or missing
            if self.force_create is False:
                LOG.debug('%s does not seem to exist; not creating', self.path)
                # This will abort __enter__
                self.__exit__(IOError, None, None)
            # Create topmost xml entry
            self.tree = etree.ElementTree(
                element=etree.Element(self.top_element))
            self.write_xml = True
        except etree.ParseError:
            LOG.error('Error parsing %s', self.path)
            # "Kodi cannot parse {0}. PKC will not function correctly. Please
            # visit {1} and correct your file!"
            dialog('ok', lang(29999), lang(39716).format(
                self.filename,
                'http://kodi.wiki'))
            self.__exit__(etree.ParseError, None, None)
        self.root = self.tree.getroot()
        return self

    def __exit__(self, e_typ, e_val, trcbak):
        if e_typ:
            raise
        # Only safe to file if we did not botch anything
        if self.write_xml is True:
            self._remove_empty_elements()
            # Indent and make readable
            indent(self.root)
            # Safe the changed xml
            self.tree.write(self.path, encoding="UTF-8")

    def _is_empty(self, element, empty_elements):
        empty = True
        for child in element:
            empty_child = True
            if list(child):
                empty_child = self._is_empty(child, empty_elements)
            if empty_child and (child.attrib or
                                (child.text and child.text.strip())):
                empty_child = False
            if empty_child:
                empty_elements.append((element, child))
            else:
                # At least one non-empty entry - hence we cannot delete the
                # original element itself
                empty = False
        return empty

    def _remove_empty_elements(self):
        """
        Deletes all empty XML elements, otherwise Kodi/PKC gets confused
        This is recursive, so an empty element with empty children will also
        get deleted
        """
        empty_elements = []
        self._is_empty(self.root, empty_elements)
        for element, child in empty_elements:
            element.remove(child)

    @staticmethod
    def _set_sub_element(element, subelement):
        """
        Returns an etree element's subelement. Creates one if not exist
        """
        answ = element.find(subelement)
        if answ is None:
            answ = etree.SubElement(element, subelement)
        return answ

    def get_setting(self, node_list):
        """
        node_list is a list of node names starting from the outside, ignoring
        the outter advancedsettings.
        Example nodelist=['video', 'busydialogdelayms'] for the following xml
        would return the etree Element:

            <busydialogdelayms>750</busydialogdelayms>

        for the following example xml:

        <advancedsettings>
            <video>
                <busydialogdelayms>750</busydialogdelayms>
            </video>
        </advancedsettings>

        Returns the etree element or None if not found
        """
        element = self.root
        for node in node_list:
            element = element.find(node)
            if element is None:
                break
        return element

    def set_setting(self, node_list, value=None, attrib=None, append=False):
        """
        node_list is a list of node names starting from the outside, ignoring
        the outter advancedsettings.
        Example nodelist=['video', 'busydialogdelayms'] for the following xml
        would return the etree Element:

            <busydialogdelayms>750</busydialogdelayms>

        for the following example xml:

        <advancedsettings>
            <video>
                <busydialogdelayms>750</busydialogdelayms>
            </video>
        </advancedsettings>

        value, e.g. '750' will be set accordingly, returning the new
        etree Element. Advancedsettings might be generated if it did not exist
        already

        If the dict attrib is set, the Element's attributs will be appended
        accordingly

        If append is True, the last element of node_list with value and attrib
        will always be added. WARNING: this will set self.write_xml to True!

        Returns the (last) etree element
        """
        attrib = attrib or {}
        value = value or ''
        if not append:
            old = self.get_setting(node_list)
            if (old is not None and
                    old.text.strip() == value and
                    old.attrib == attrib):
                # Already set exactly these values
                return old
        LOG.debug('Adding etree to: %s, value: %s, attrib: %s, append: %s',
                  node_list, value, attrib, append)
        self.write_xml = True
        element = self.root
        nodes = node_list[:-1] if append else node_list
        for node in nodes:
            element = self._set_sub_element(element, node)
        if append:
            element = etree.SubElement(element, node_list[-1])
        # Write new values
        element.text = value
        if attrib:
            for key, attribute in attrib.iteritems():
                element.set(key, attribute)
        return element


def passwords_xml():
    """
    To add network credentials to Kodi's password xml
    """
    path = path_ops.translate_path('special://userdata/')
    xmlpath = "%spasswords.xml" % path
    try:
        xmlparse = etree.parse(xmlpath)
    except IOError:
        # Document is blank or missing
        root = etree.Element('passwords')
        skip_find = True
    except etree.ParseError:
        LOG.error('Error parsing %s', xmlpath)
        # "Kodi cannot parse {0}. PKC will not function correctly. Please visit
        # {1} and correct your file!"
        dialog('ok', lang(29999), lang(39716).format(
            'passwords.xml', 'http://forum.kodi.tv/'))
        return
    else:
        root = xmlparse.getroot()
        skip_find = False

    credentials = settings('networkCreds')
    if credentials:
        # Present user with options
        option = dialog('select',
                        "Modify/Remove network credentials",
                        ["Modify", "Remove"])

        if option < 0:
            # User cancelled dialog
            return

        elif option == 1:
            # User selected remove
            success = False
            for paths in root.getiterator('passwords'):
                for path in paths:
                    if path.find('.//from').text == "smb://%s/" % credentials:
                        paths.remove(path)
                        LOG.info("Successfully removed credentials for: %s",
                                 credentials)
                        etree.ElementTree(root).write(xmlpath,
                                                      encoding="UTF-8")
                        success = True
            if not success:
                LOG.error("Failed to find saved server: %s in passwords.xml",
                          credentials)
                dialog('notification',
                       heading='{plex}',
                       message="%s not found" % credentials,
                       icon='{warning}',
                       sound=False)
                return
            settings('networkCreds', value="")
            dialog('notification',
                   heading='{plex}',
                   message="%s removed from passwords.xml" % credentials,
                   icon='{plex}',
                   sound=False)
            return

        elif option == 0:
            # User selected to modify
            server = dialog('input',
                            "Modify the computer name or ip address",
                            credentials)
            if not server:
                return
    else:
        # No credentials added
        dialog('ok',
               "Network credentials",
               'Input the server name or IP address as indicated in your plex '
               'library paths. For example, the server name: '
               '\\\\SERVER-PC\\path\\ or smb://SERVER-PC/path is SERVER-PC')
        server = dialog('input', "Enter the server name or IP address")
        if not server:
            return
        server = quote_plus(server)

    # Network username
    user = dialog('input', "Enter the network username")
    if not user:
        return
    user = quote_plus(user)
    # Network password
    password = dialog('input',
                      "Enter the network password",
                      '',  # Default input
                      type='{alphanum}',
                      option='{hide}')
    # Need to url-encode the password
    password = quote_plus(password)
    # Add elements. Annoying etree bug where findall hangs forever
    if skip_find is False:
        skip_find = True
        for path in root.findall('.//path'):
            if path.find('.//from').text.lower() == "smb://%s/" % server.lower():
                # Found the server, rewrite credentials
                path.find('.//to').text = ("smb://%s:%s@%s/"
                                           % (user, password, server))
                skip_find = False
                break
    if skip_find:
        # Server not found, add it.
        path = etree.SubElement(root, 'path')
        etree.SubElement(path, 'from', attrib={'pathversion': "1"}).text = \
            "smb://%s/" % server
        topath = "smb://%s:%s@%s/" % (user, password, server)
        etree.SubElement(path, 'to', attrib={'pathversion': "1"}).text = topath

    # Add credentials
    settings('networkCreds', value="%s" % server)
    LOG.info("Added server: %s to passwords.xml", server)
    # Prettify and write to file
    indent(root)
    etree.ElementTree(root).write(xmlpath, encoding="UTF-8")


def playlist_xsp(mediatype, tagname, viewid, viewtype="", delete=False):
    """
    Feed with tagname as unicode
    """
    path = path_ops.translate_path("special://profile/playlists/video/")
    if viewtype == "mixed":
        plname = "%s - %s" % (tagname, mediatype)
        xsppath = "%sPlex %s - %s.xsp" % (path, viewid, mediatype)
    else:
        plname = tagname
        xsppath = "%sPlex %s.xsp" % (path, viewid)

    # Create the playlist directory
    if not path_ops.exists(path):
        LOG.info("Creating directory: %s", path)
        path_ops.makedirs(path)

    # Only add the playlist if it doesn't already exists
    if path_ops.exists(xsppath):
        LOG.info('Path %s does exist', xsppath)
        if delete:
            path_ops.remove(xsppath)
            LOG.info("Successfully removed playlist: %s.", tagname)
        return

    # Using write process since there's no guarantee the xml declaration works
    # with etree
    itemtypes = {
        'homevideos': 'movies',
        'movie': 'movies',
        'show': 'tvshows'
    }
    LOG.info("Writing playlist file to: %s", xsppath)
    with open(path_ops.encode_path(xsppath), 'wb') as filer:
        filer.write(try_encode(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
            '<smartplaylist type="%s">\n\t'
                '<name>Plex %s</name>\n\t'
                '<match>all</match>\n\t'
                '<rule field="tag" operator="is">\n\t\t'
                    '<value>%s</value>\n\t'
                '</rule>\n'
            '</smartplaylist>\n'
            % (itemtypes.get(mediatype, mediatype), plname, tagname)))
    LOG.info("Successfully added playlist: %s", tagname)


def delete_playlists():
    """
    Clean up the playlists
    """
    path = path_ops.translate_path('special://profile/playlists/video/')
    for root, _, files in path_ops.walk(path):
        for file in files:
            if file.startswith('Plex'):
                path_ops.remove(path_ops.path.join(root, file))


def delete_nodes():
    """
    Clean up video nodes
    """
    path = path_ops.translate_path("special://profile/library/video/")
    for root, dirs, _ in path_ops.walk(path):
        for directory in dirs:
            if directory.startswith('Plex-'):
                path_ops.rmtree(path_ops.path.join(root, directory))
        break


def generate_file_md5(path):
    """
    Generates the md5 hash value for the file located at path [unicode].
    The hash does not include the path and filename and is thus identical for
    a file that was moved/changed name.
    Returns a unique unicode containing only hexadecimal digits
    """
    m = hashlib.md5()
    with open(path_ops.encode_path(path), 'rb') as f:
        while True:
            piece = f.read(32768)
            if not piece:
                break
            m.update(piece)
    return m.hexdigest().decode('utf-8')


###############################################################################
# WRAPPERS

def catch_exceptions(warnuser=False):
    """
    Decorator for methods to catch exceptions and log them. Useful for e.g.
    librarysync threads using itemtypes.py, because otherwise we would not
    get informed of crashes

    warnuser=True:      sets the window flag 'plex_scancrashed' to true
                        which will trigger a Kodi infobox to inform user
    """
    def decorate(func):
        """
        Decorator construct
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            """
            Wrapper construct
            """
            try:
                return func(*args, **kwargs)
            except Exception as err:
                LOG.error('%s has crashed. Error: %s', func.__name__, err)
                import traceback
                LOG.error("Traceback:\n%s", traceback.format_exc())
                if warnuser:
                    window('plex_scancrashed', value='true')
                return
        return wrapper
    return decorate


def log_time(func):
    """
    Decorator for functions and methods to log the time it took to run the code
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        starttotal = datetime.now()
        result = func(*args, **kwargs)
        elapsedtotal = datetime.now() - starttotal
        LOG.info('It took %s to run the function %s',
                 elapsedtotal, func.__name__)
        return result
    return wrapper


def thread_methods(cls=None, add_stops=None, add_suspends=None):
    """
    Decorator to add the following methods to a threading class:

    suspend():          pauses the thread
    resume():           resumes the thread
    stop():             stopps/kills the thread

    suspended():        returns True if thread is suspended
    stopped():          returns True if thread is stopped (or should stop ;-))
                        ALSO returns True if PKC should exit

    Also adds the following class attributes:
        thread_stopped
        thread_suspended
        stops
        suspends

    invoke with either
        @thread_methods
        class MyClass():
    or
        @thread_methods(add_stops=['SUSPEND_LIBRARY_TRHEAD'],
                        add_suspends=['DB_SCAN', 'WHATEVER'])
        class MyClass():
    """
    # So we don't need to invoke with ()
    if cls is None:
        return partial(thread_methods,
                       add_stops=add_stops,
                       add_suspends=add_suspends)
    # Because we need a reference, not a copy of the immutable objects in
    # state, we need to look up state every time explicitly
    cls.stops = ['STOP_PKC']
    if add_stops is not None:
        cls.stops.extend(add_stops)
    cls.suspends = add_suspends or []

    # Attach new attributes to class
    cls.thread_stopped = False
    cls.thread_suspended = False

    # Define new class methods and attach them to class
    def stop(self):
        """
        Call to stop this thread
        """
        self.thread_stopped = True
    cls.stop = stop

    def suspend(self):
        """
        Call to suspend this thread
        """
        self.thread_suspended = True
    cls.suspend = suspend

    def resume(self):
        """
        Call to revive a suspended thread back to life
        """
        self.thread_suspended = False
    cls.resume = resume

    def suspended(self):
        """
        Returns True if the thread is suspended
        """
        if self.thread_suspended is True:
            return True
        for suspend in self.suspends:
            if getattr(state, suspend):
                return True
        return False
    cls.suspended = suspended

    def stopped(self):
        """
        Returns True if the thread is stopped
        """
        if self.thread_stopped is True:
            return True
        for stop in self.stops:
            if getattr(state, stop):
                return True
        return False
    cls.stopped = stopped

    # Return class to render this a decorator
    return cls
