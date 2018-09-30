import pytest
import mock
import logging
import eventlet
import time
from signalslot import Signal
from signalslot.contrib.task import Task

eventlet.monkey_patch(time=True)


class TestTask(object):
    def setup_method(self, method):
        self.signal = mock.Mock()

    def get_task_mock(self, *methods, **kwargs):
        if kwargs.get('logger'):
            log = logging.getLogger('TestTask')
        else:
            log = None
        task_mock = Task(self.signal, logger=log)

        for method in methods:
            setattr(task_mock, method, mock.Mock())

        return task_mock

    def test_eq(self):
        x = Task(self.signal, dict(some_kwarg='foo'),
                 logger=logging.getLogger('TaskX'))
        y = Task(self.signal, dict(some_kwarg='foo'),
                 logger=logging.getLogger('TaskY'))

        assert x == y

    def test_not_eq(self):
        x = Task(self.signal, dict(some_kwarg='foo',
                 logger=logging.getLogger('TaskX')))
        y = Task(self.signal, dict(some_kwarg='bar',
                 logger=logging.getLogger('TaskY')))

        assert x != y

    def test_unicode(self):
        t = Task(self.signal, dict(some_kwarg='foo'),
                 logger=logging.getLogger('TaskT'))

        assert str(t) == "Mock: {'some_kwarg': 'foo'}"

    def test_get_or_create_gets(self):
        x = Task.get_or_create(self.signal, dict(some_kwarg='foo'),
                               logger=logging.getLogger('TaskX'))
        y = Task.get_or_create(self.signal, dict(some_kwarg='foo'),
                               logger=logging.getLogger('TaskY'))

        assert x is y

    def test_get_or_create_creates(self):
        x = Task.get_or_create(self.signal, dict(some_kwarg='foo'),
                               logger=logging.getLogger('TaskX'))
        y = Task.get_or_create(self.signal, dict(some_kwarg='bar'),
                               logger=logging.getLogger('TaskY'))

        assert x is not y

    def test_get_or_create_without_kwargs(self):
        t = Task.get_or_create(self.signal)

        assert t.kwargs == {}

    def test_get_or_create_uses_cls(self):
        class Foo(Task):
            pass

        assert isinstance(Foo.get_or_create(self.signal), Foo)

    def test_do_emit(self):
        task_mock = self.get_task_mock('_clean', '_exception', '_completed')

        task_mock._do()

        self.signal.emit.assert_called_once_with()

    def test_do_emit_nolog(self):
        task_mock = self.get_task_mock(
                '_clean', '_exception', '_completed', logging=True)

        task_mock._do()

        self.signal.emit.assert_called_once_with()

    def test_do_emit_no_log(self):
        task_mock = self.get_task_mock('_clean', '_exception', '_completed')

        task_mock._do()

        self.signal.emit.assert_called_once_with()

    def test_do_complete(self):
        task_mock = self.get_task_mock('_clean', '_exception', '_completed')

        task_mock._do()

        task_mock._exception.assert_not_called()
        task_mock._completed.assert_called_once_with()
        task_mock._clean.assert_called_once_with()

    def test_do_success(self):
        task_mock = self.get_task_mock()
        assert task_mock._do() is True

    def test_do_failure_nolog(self):
        # Our dummy exception
        class DummyError(Exception):
            pass

        task_mock = self.get_task_mock('_emit')
        task_mock._emit.side_effect = DummyError()

        # This will throw an exception at us, be ready to catch it.
        try:
            task_mock._do()
            assert False
        except DummyError:
            pass

    def test_do_failure_withlog(self):
        task_mock = self.get_task_mock('_emit', logger=True)
        task_mock._emit.side_effect = Exception()
        assert task_mock._do() is False

    def test_do_exception(self):
        task_mock = self.get_task_mock(
                '_clean', '_exception', '_completed', '_emit')

        task_mock._emit.side_effect = Exception()

        task_mock._do()

        task_mock._exception.assert_called_once_with(
            Exception, task_mock._emit.side_effect, mock.ANY)

        task_mock._completed.assert_not_called()
        task_mock._clean.assert_called_once_with()

    @mock.patch('signalslot.signal.inspect')
    def test_semaphore(self, inspect):
        slot = mock.Mock()
        slot.side_effect = lambda **k: time.sleep(.3)

        signal = Signal('tost')
        signal.connect(slot)

        x = Task.get_or_create(signal, dict(some_kwarg='foo'),
                               logger=logging.getLogger('TaskX'))
        y = Task.get_or_create(signal, dict(some_kwarg='foo'),
                               logger=logging.getLogger('TaskY'))

        eventlet.spawn(x)
        time.sleep(.1)
        eventlet.spawn(y)
        time.sleep(.1)

        assert slot.call_count == 1
        time.sleep(.4)
        assert slot.call_count == 2

    def test_call_context(self):
        task_mock = self.get_task_mock('_clean', '_exception', '_completed',
                                       '_emit')

        task_mock._emit.side_effect = Exception()

        assert task_mock.failures == 0
        task_mock()
        assert task_mock.failures == 1

    def test_call_success(self):
        task_mock = self.get_task_mock('_clean', '_exception', '_completed',
                                       '_emit')

        assert task_mock.failures == 0
        task_mock()
        assert task_mock.failures == 0
