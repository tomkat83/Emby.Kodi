import sys
import eventlet
import contexter
import six


class Task(object):
    @classmethod
    def get_or_create(cls, signal, kwargs=None, logger=None):
        if not hasattr(cls, '_registry'):
            cls._registry = []

        task = cls(signal, kwargs, logger=logger)

        if task not in cls._registry:
            cls._registry.append(task)

        return cls._registry[cls._registry.index(task)]

    def __init__(self, signal, kwargs=None, logger=None):
        self.signal = signal
        self.kwargs = kwargs or {}
        self.logger = logger
        self.failures = 0
        self.task_semaphore = eventlet.semaphore.BoundedSemaphore(1)

    def __call__(self, semaphores=None):
        semaphores = semaphores or []

        with contexter.Contexter(self.task_semaphore, *semaphores):
            result = self._do()

        if result:
            self.failures = 0
        else:
            self.failures += 1

        return result

    def _do(self):
        try:
            self._emit()
        except Exception:
            self._exception(*sys.exc_info())
            return False
        else:
            self._completed()
            return True
        finally:
            self._clean()

    def _clean(self):
        pass

    def _completed(self):
        if self.logger:
            self.logger.info('[%s] Completed' % self)

    def _exception(self, e_type, e_value, e_traceback):
        if self.logger:
            self.logger.exception('[%s] Raised exception: %s' % (
                self, e_value))
        else:
            six.reraise(e_type, e_value, e_traceback)

    def _emit(self):
        if self.logger:
            self.logger.info('[%s] Running' % self)
        self.signal.emit(**self.kwargs)

    def __eq__(self, other):
        return (self.signal == other.signal and self.kwargs == other.kwargs)

    def __str__(self):
        return '%s: %s' % (self.signal.__class__.__name__, self.kwargs)
