import threading


class Callable(object):
    _currID = 0

    def __init__(self, func, forcedArgs=None, ID=None):
        self.func = func
        self.forcedArgs = forcedArgs

        self.ID = ID or id(func)

        if not self.ID:
            self.ID = Callable.nextID()

    def __repr__(self):
        return '<Callable:({0})>'.format(repr(self.func).strip('<>'))

    def __eq__(self, other):
        if not other:
            return False

        if self.__class__ != other.__class__:
            return False

        return self.ID and self.ID == other.ID

    def __ne__(self, other):
        return not self.__eq__(other)

    def __call__(self, *args, **kwargs):
        args = args or []
        if self.forcedArgs:
            args = self.forcedArgs

        self.func(*args, **kwargs)

    @property
    def context(self):
        return self.func.im_self

    @classmethod
    def nextID(cls):
        cls._currID += 1
        return cls._currID

    def deferCall(self, timeout=0.1):
        timer = threading.Timer(timeout, self.onDeferCallTimer)
        timer.name = 'ONDEFERCALLBACK-TIMER:{0}'.format(self.func)
        timer.start()

    def onDeferCallTimer(self):
        self()
