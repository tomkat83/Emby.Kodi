import signalslot


class SignalsMixin(object):
    def __init__(self):
        self._signals = {}

    def on(self, signalName, callback):
        if signalName not in self._signals:
            self._signals[signalName] = signalslot.Signal(threadsafe=True)

        signal = self._signals[signalName]

        signal.connect(callback)

    def off(self, signalName, callback):
        if not self._signals:
            return

        if not signalName:
            if not callback:
                self._signals = {}
            else:
                for name in self._signals:
                    self.off(name, callback)
        else:
            if not callback:
                if signalName in self._signals:
                    del self._signals[signalName]
            else:
                self._signals[signalName].disconnect(callback)

    def trigger(self, signalName, **kwargs):
        if not self._signals:
            return

        if signalName not in self._signals:
            return

        self._signals[signalName].emit(**kwargs)
