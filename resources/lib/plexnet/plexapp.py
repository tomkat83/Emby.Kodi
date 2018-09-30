import threading
import platform
import uuid
import sys
import callback

import signalsmixin
import simpleobjects
import nowplayingmanager
import util

Res = simpleobjects.Res

APP = None
INTERFACE = None

MANAGER = None
SERVERMANAGER = None
ACCOUNT = None

PLATFORM = util.X_PLEX_DEVICE

def init():
    global MANAGER, SERVERMANAGER, ACCOUNT
    import myplexaccount
    ACCOUNT = myplexaccount.ACCOUNT
    import plexservermanager
    SERVERMANAGER = plexservermanager.MANAGER
    import myplexmanager
    MANAGER = myplexmanager.MANAGER
    ACCOUNT.init()


class App(signalsmixin.SignalsMixin):
    def __init__(self):
        signalsmixin.SignalsMixin.__init__(self)
        self.pendingRequests = {}
        self.initializers = {}
        self.timers = []
        self.nowplayingmanager = nowplayingmanager.NowPlayingManager()

    def addTimer(self, timer):
        self.timers.append(timer)

    def startRequest(self, request, context, body=None, contentType=None):
        context.request = request

        started = request.startAsync(body=body, contentType=contentType, context=context)

        if started:
            requestID = context.request.getIdentity()
            self.pendingRequests[requestID] = context
        elif context.callback:
            context.callback(None, context)

        return started

    def onRequestTimeout(self, context):
        requestID = context.request.getIdentity()

        if requestID not in self.pendingRequests:
            return

        context.request.cancel()

        util.WARN_LOG("Request to {0} timed out after {1} sec".format(util.cleanToken(context.request.url), context.timeout))

        if context.callback:
            context.callback(None, context)

    def delRequest(self, request):
        requestID = request.getIdentity()
        if requestID not in self.pendingRequests:
            return

        del self.pendingRequests[requestID]

    def addInitializer(self, name):
        self.initializers[name] = True

    def clearInitializer(self, name):
        if name in self.initializers:
            del self.initializers[name]
            if self.isInitialized():
                self.onInitialized()

    def isInitialized(self):
        return not self.initializers

    def onInitialized(self):
        # Wire up a few of our own listeners
        # PlexServerManager()
        # self.on("change:user", callback.Callable(self.onAccountChange))

        self.trigger('init')

    def cancelAllTimers(self):
        for timer in self.timers:
            timer.cancel()

    def preShutdown(self):
        import http
        http.HttpRequest._cancel = True
        if self.pendingRequests:
            util.DEBUG_LOG('Closing down {0} App() requests...'.format(len(self.pendingRequests)))
            for p in self.pendingRequests.values():
                if p:
                    p.request.cancel()

        if self.timers:
            util.DEBUG_LOG('Canceling App() timers...')
            self.cancelAllTimers()

        if SERVERMANAGER.selectedServer:
            util.DEBUG_LOG('Closing server...')
            SERVERMANAGER.selectedServer.close()

    def shutdown(self):
        if self.timers:
            util.DEBUG_LOG('Waiting for {0} App() timers: Started'.format(len(self.timers)))

            self.cancelAllTimers()

            for timer in self.timers:
                timer.join()

            util.DEBUG_LOG('Waiting for App() timers: Finished')


class DeviceInfo(object):
    def getCaptionsOption(self, key):
        return None


class AppInterface(object):
    QUALITY_LOCAL = 0
    QUALITY_REMOTE = 1
    QUALITY_ONLINE = 2

    _globals = {}

    def __init__(self):
        self.setQualities()

    def setQualities(self):
        # Calculate the max quality based on 4k support
        if self._globals.get("supports4k"):
            maxQuality = simpleobjects.AttributeDict({
                'height': 2160,
                'maxHeight': 2160,
                'origHeight': 1080
            })
            maxResolution = self._globals.get("Is4k") and "4k" or "1080p"
        else:
            maxQuality = simpleobjects.AttributeDict({
                'height': 1080,
                'maxHeight': 1088
            })
            maxResolution = "1080p"

        self._globals['qualities'] = [
            simpleobjects.AttributeDict({'title': "Original", 'index': 13, 'maxBitrate': 200000}),
            simpleobjects.AttributeDict({'title': "20 Mbps " + maxResolution, 'index': 12, 'maxBitrate': 20000}),
            simpleobjects.AttributeDict({'title': "12 Mbps " + maxResolution, 'index': 11, 'maxBitrate': 12000}),
            simpleobjects.AttributeDict({'title': "10 Mbps " + maxResolution, 'index': 10, 'maxBitrate': 10000}),
            simpleobjects.AttributeDict({'title': "8 Mbps " + maxResolution, 'index': 9, 'maxBitrate': 8000}),
            simpleobjects.AttributeDict({'title': "4 Mbps 720p", 'index': 8, 'maxBitrate': 4000, 'maxHeight': 720}),
            simpleobjects.AttributeDict({'title': "3 Mbps 720p", 'index': 7, 'maxBitrate': 3000, 'maxHeight': 720}),
            simpleobjects.AttributeDict({'title': "2 Mbps 720p", 'index': 6, 'maxBitrate': 2000, 'maxHeight': 720}),
            simpleobjects.AttributeDict({'title': "1.5 Mbps 480p", 'index': 5, 'maxBitrate': 1500, 'maxHeight': 480}),
            simpleobjects.AttributeDict({'title': "720 Kbps", 'index': 4, 'maxBitrate': 720, 'maxHeight': 360}),
            simpleobjects.AttributeDict({'title': "320 Kbps", 'index': 3, 'maxBitrate': 320, 'maxHeight': 360}),
            maxQuality
        ]

        for quality in self._globals['qualities']:
            if quality.index >= 9:
                quality.update(maxQuality)

    def getPreference(self, pref, default=None):
        raise NotImplementedError

    def setPreference(self, pref, value):
        raise NotImplementedError

    def clearRegistry(self, reg, sec=None):
        raise NotImplementedError

    def getRegistry(self, reg, default=None, sec=None):
        raise NotImplementedError

    def setRegistry(self, reg, value, sec=None):
        raise NotImplementedError

    def getGlobal(self, glbl, default=None):
        raise NotImplementedError

    def getCapabilities(self):
        raise NotImplementedError

    def LOG(self, msg):
        raise NotImplementedError

    def DEBUG_LOG(self, msg):
        self.LOG(msg)

    def WARN_LOG(self, msg):
        self.LOG(msg)

    def ERROR_LOG(self, msg):
        self.LOG(msg)

    def ERROR(self, msg=None, err=None):
        self.LOG(msg)

    def FATAL(self, msg=None):
        self.ERROR_LOG('FATAL: {0}'.format(msg))

    def supportsAudioStream(self, codec, channels):
        return False

    def supportsSurroundSound(self):
        return False

    def getMaxResolution(self, quality_type, allow4k=False):
        return 480

    def getQualityIndex(self, qualityType):
        if qualityType == self.QUALITY_LOCAL:
            return self.getPreference("local_quality", 13)
        elif qualityType == self.QUALITY_ONLINE:
            return self.getPreference("online_quality", 8)
        else:
            return self.getPreference("remote_quality", 13)

    def settingsGetMaxResolution(self, qualityType, allow4k):
        qualityIndex = self.getQualityIndex(qualityType)

        if qualityIndex >= 9:
            return allow4k and 2160 or 1088
        elif qualityIndex >= 6:
            return 720
        elif qualityIndex >= 5:
            return 480
        else:
            return 360

    def getMaxBitrate(self, qualityType):
        qualityIndex = self.getQualityIndex(qualityType)

        qualities = self.getGlobal("qualities", [])
        for quality in qualities:
            if quality.index == qualityIndex:
                return util.validInt(quality.maxBitrate)

        return 0


class PlayerSettingsInterface(object):
    def __init__(self):
        self.prefOverrides = {}

    def __getattr__(self, name):
        return getattr(INTERFACE, name)

    def setPrefOverride(self, key, val):
        self.prefOverrides[key] = val

    def getPrefOverride(self, key, default=None):
        return self.prefOverrides.get(key, default)

    def getQualityIndex(self, qualityType):
        if qualityType == INTERFACE.QUALITY_LOCAL:
            return self.getPreference("local_quality", 13)
        elif qualityType == INTERFACE.QUALITY_ONLINE:
            return self.getPreference("online_quality", 8)
        else:
            return self.getPreference("remote_quality", 13)

    def getPreference(self, key, default=None):
        if key in self.prefOverrides:
            return self.prefOverrides[key]
        else:
            return INTERFACE.getPreference(key, default)

    def getMaxResolution(self, quality_type, allow4k=False):
        qualityIndex = self.getQualityIndex(quality_type)

        if qualityIndex >= 9:
            return allow4k and 2160 or 1088
        elif qualityIndex >= 6:
            return 720
        elif qualityIndex >= 5:
            return 480
        else:
            return 360


class DumbInterface(AppInterface):
    _prefs = {}
    _regs = {
        None: {}
    }
    _globals = {
        'platform': platform.uname()[0],
        'appVersionStr': '0.0.0a1',
        'clientIdentifier': str(hex(uuid.getnode())),
        'platformVersion': platform.uname()[2],
        'product': 'PlexNet.API',
        'provides': 'player',
        'device': platform.uname()[0],
        'model': 'Unknown',
        'friendlyName': 'PlexNet.API',
        'deviceInfo': DeviceInfo()
    }

    def getPreference(self, pref, default=None):
        return self._prefs.get(pref, default)

    def setPreference(self, pref, value):
        self._prefs[pref] = value

    def getRegistry(self, reg, default=None, sec=None):
        section = self._regs.get(sec)
        if section:
            return section.get(reg, default)

        return default

    def setRegistry(self, reg, value, sec=None):
        if sec and sec not in self._regs:
            self._regs[sec] = {}
        self._regs[sec][reg] = value

    def clearRegistry(self, reg, sec=None):
        del self._regs[sec][reg]

    def getGlobal(self, glbl, default=None):
        return self._globals.get(glbl, default)

    def getCapabilities(self):
        return ''

    def LOG(self, msg):
        print 'PlexNet.API: {0}'.format(msg)

    def DEBUG_LOG(self, msg):
        self.LOG('DEBUG: {0}'.format(msg))

    def WARN_LOG(self, msg):
        self.LOG('WARNING: {0}'.format(msg))

    def ERROR_LOG(self, msg):
        self.LOG('ERROR: {0}'.format(msg))

    def ERROR(self, msg=None, err=None):
        if err:
            self.LOG('ERROR: {0} - {1}'.format(msg, err.message))
        else:
            import traceback
            traceback.print_exc()


class CompatEvent(threading._Event):
    def wait(self, timeout):
        threading._Event.wait(self, timeout)
        return self.isSet()


class Timer(object):
    def __init__(self, timeout, function, repeat=False, *args, **kwargs):
        self.function = function
        self.timeout = timeout
        self.repeat = repeat
        self.args = args
        self.kwargs = kwargs
        self._reset = False
        self.event = CompatEvent()
        self.start()

    def start(self):
        self.event.clear()
        self.thread = threading.Thread(target=self.run, name='TIMER:{0}'.format(self.function), *self.args, **self.kwargs)
        self.thread.start()

    def run(self):
        util.DEBUG_LOG('Timer {0}: {1}'.format(repr(self.function), self._reset and 'RESET'or 'STARTED'))
        try:
            while not self.event.isSet() and not self.shouldAbort():
                while not self.event.wait(self.timeout) and not self.shouldAbort():
                    if self._reset:
                        return

                    self.function(*self.args, **self.kwargs)
                    if not self.repeat:
                        return
        finally:
            if not self._reset:
                if self in APP.timers:
                    APP.timers.remove(self)

                util.DEBUG_LOG('Timer {0}: FINISHED'.format(repr(self.function)))

            self._reset = False

    def cancel(self):
        self.event.set()

    def reset(self):
        self._reset = True
        self.cancel()
        if self.thread and self.thread.isAlive():
            self.thread.join()
        self.start()

    def shouldAbort(self):
        return False

    def join(self):
        if self.thread.isAlive():
            self.thread.join()

    def isExpired(self):
        return self.event.isSet()


TIMER = Timer


def createTimer(timeout, function, repeat=False, *args, **kwargs):
    if isinstance(function, basestring):
        def dummy(*args, **kwargs):
            pass
        dummy.__name__ = function
        function = dummy
    timer = TIMER(timeout / 1000.0, function, repeat=repeat, *args, **kwargs)
    return timer


def setTimer(timer):
    global TIMER
    TIMER = timer


def setInterface(interface):
    global INTERFACE
    INTERFACE = interface


def setApp(app):
    global APP
    APP = app


def setUserAgent(agent):
    util.USER_AGENT = agent
    util.BASE_HEADERS = util.resetBaseHeaders()


def setAbortFlagFunction(func):
    import asyncadapter
    asyncadapter.ABORT_FLAG_FUNCTION = func


def refreshResources(force=False):
    import gdm
    gdm.DISCOVERY.discover()
    MANAGER.refreshResources(force)
    SERVERMANAGER.refreshManualConnections()


setApp(App())
setInterface(DumbInterface())
