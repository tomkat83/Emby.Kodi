import simpleobjects
import re
import sys
import time
import platform
import uuid

import verlib
import compat
import plexapp

BASE_HEADERS = ''


def resetBaseHeaders():
    return {
        'X-Plex-Platform': X_PLEX_PLATFORM,
        'X-Plex-Platform-Version': X_PLEX_PLATFORM_VERSION,
        'X-Plex-Provides': X_PLEX_PROVIDES,
        'X-Plex-Product': X_PLEX_PRODUCT,
        'X-Plex-Version': X_PLEX_VERSION,
        'X-Plex-Device': X_PLEX_DEVICE,
        'X-Plex-Client-Identifier': X_PLEX_IDENTIFIER,
        'Accept-Encoding': 'gzip,deflate',
        'User-Agent': USER_AGENT
    }


# Core Settings
PROJECT = 'PlexNet'                                 # name provided to plex server
VERSION = '0.0.0a1'                                 # version of this api
TIMEOUT = 10                                        # request timeout
X_PLEX_CONTAINER_SIZE = 50                          # max results to return in a single search page

# Plex Header Configuation
X_PLEX_PROVIDES = 'player,controller'          # one or more of [player, controller, server]
X_PLEX_PLATFORM = platform.uname()[0]          # Platform name, eg iOS, MacOSX, Android, LG, etc
X_PLEX_PLATFORM_VERSION = platform.uname()[2]  # Operating system version, eg 4.3.1, 10.6.7, 3.2
X_PLEX_PRODUCT = PROJECT                       # Plex application name, eg Laika, Plex Media Server, Media Link
X_PLEX_VERSION = VERSION                       # Plex application version number
USER_AGENT = '{0}/{1}'.format(PROJECT, VERSION)

try:
    _platform = platform.system()
except:
    try:
        _platform = platform.platform(terse=True)
    except:
        _platform = sys.platform

X_PLEX_DEVICE = _platform                     # Device name and model number, eg iPhone3,2, Motorola XOOM, LG5200TV
X_PLEX_IDENTIFIER = str(hex(uuid.getnode()))  # UUID, serial number, or other number unique per device

BASE_HEADERS = resetBaseHeaders()

QUALITY_LOCAL = 0
QUALITY_REMOTE = 1
QUALITY_ONLINE = 2

Res = simpleobjects.Res
AttributeDict = simpleobjects.AttributeDict


def LOG(msg):
    plexapp.INTERFACE.LOG(msg)


def DEBUG_LOG(msg):
    plexapp.INTERFACE.DEBUG_LOG(msg)


def ERROR_LOG(msg):
    plexapp.INTERFACE.ERROR_LOG(msg)


def WARN_LOG(msg):
    plexapp.INTERFACE.WARN_LOG(msg)


def ERROR(msg=None, err=None):
    plexapp.INTERFACE.ERROR(msg, err)


def FATAL(msg=None):
    plexapp.INTERFACE.FATAL(msg)


def TEST(msg):
    plexapp.INTERFACE.LOG(' ---TEST: {0}'.format(msg))


def userAgent():
    return plexapp.INTERFACE.getGlobal("userAgent")


def dummyTranslate(string):
    return string


def hideToken(token):
    # return 'X' * len(token)
    if not token:
        return token
    return '****' + token[-4:]


def cleanToken(url):
    return re.sub('X-Plex-Token=[^&]+', 'X-Plex-Token=****', url)


def now(local=False):
    if local:
        return time.time()
    else:
        return time.mktime(time.gmtime())


def joinArgs(args):
    if not args:
        return ''

    arglist = []
    for key in sorted(args, key=lambda x: x.lower()):
        value = str(args[key])
        arglist.append('{0}={1}'.format(key, compat.quote(value)))

    return '?{0}'.format('&'.join(arglist))


def addPlexHeaders(transferObj, token=None):
    transferObj.addHeader("X-Plex-Platform", plexapp.INTERFACE.getGlobal("platform"))
    transferObj.addHeader("X-Plex-Version", plexapp.INTERFACE.getGlobal("appVersionStr"))
    transferObj.addHeader("X-Plex-Client-Identifier", plexapp.INTERFACE.getGlobal("clientIdentifier"))
    transferObj.addHeader("X-Plex-Platform-Version", plexapp.INTERFACE.getGlobal("platformVersion", "unknown"))
    transferObj.addHeader("X-Plex-Product", plexapp.INTERFACE.getGlobal("product"))
    transferObj.addHeader("X-Plex-Provides", not plexapp.INTERFACE.getPreference("remotecontrol", False) and 'player' or '')
    transferObj.addHeader("X-Plex-Device", plexapp.INTERFACE.getGlobal("device"))
    transferObj.addHeader("X-Plex-Model", plexapp.INTERFACE.getGlobal("model"))
    transferObj.addHeader("X-Plex-Device-Name", plexapp.INTERFACE.getGlobal("friendlyName"))

    # Adding the X-Plex-Client-Capabilities header causes node.plexapp.com to 500
    if not type(transferObj) == "roUrlTransfer" or 'node.plexapp.com' not in transferObj.getUrl():
        transferObj.addHeader("X-Plex-Client-Capabilities", plexapp.INTERFACE.getCapabilities())

    addAccountHeaders(transferObj, token)


def addAccountHeaders(transferObj, token=None):
    if token:
        transferObj.addHeader("X-Plex-Token", token)

    # TODO(schuyler): Add username?


def validInt(int_str):
    try:
        return int(int_str)
    except:
        return 0


def bitrateToString(bits):
    if not bits:
        return ''

    speed = bits / 1000000.0
    if speed < 1:
        speed = int(round(bits / 1000.0))
        return '{0} Kbps'.format(speed)
    else:
        return '{0:.1f} Mbps'.format(speed)


def normalizedVersion(ver):
    try:
        modv = '.'.join(ver.split('.')[:4]).split('-', 1)[0]  # Clean the version i.e. Turn 1.2.3.4-asdf8-ads7f into 1.2.3.4
        return verlib.NormalizedVersion(verlib.suggest_normalized_version(modv))
    except:
        if ver:
            ERROR()
        return verlib.NormalizedVersion(verlib.suggest_normalized_version('0.0.0'))
