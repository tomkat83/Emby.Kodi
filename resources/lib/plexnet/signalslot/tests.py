import pytest
import mock

from signalslot import Signal, SlotMustAcceptKeywords, Slot


@mock.patch('signalslot.signal.inspect')
class TestSignal(object):
    def setup_method(self, method):
        self.signal_a = Signal(threadsafe=True)
        self.signal_b = Signal(args=['foo'])

        self.slot_a = mock.Mock(spec=lambda **kwargs: None)
        self.slot_a.return_value = None
        self.slot_b = mock.Mock(spec=lambda **kwargs: None)
        self.slot_b.return_value = None

    def test_is_connected(self, inspect):
        self.signal_a.connect(self.slot_a)

        assert self.signal_a.is_connected(self.slot_a)
        assert not self.signal_a.is_connected(self.slot_b)
        assert not self.signal_b.is_connected(self.slot_a)
        assert not self.signal_b.is_connected(self.slot_b)

    def test_emit_one_slot(self, inspect):
        self.signal_a.connect(self.slot_a)

        self.signal_a.emit()

        self.slot_a.assert_called_once_with()
        assert self.slot_b.call_count == 0

    def test_emit_two_slots(self, inspect):
        self.signal_a.connect(self.slot_a)
        self.signal_a.connect(self.slot_b)

        self.signal_a.emit()

        self.slot_a.assert_called_once_with()
        self.slot_b.assert_called_once_with()

    def test_emit_one_slot_with_arguments(self, inspect):
        self.signal_b.connect(self.slot_a)

        self.signal_b.emit(foo='bar')

        self.slot_a.assert_called_once_with(foo='bar')
        assert self.slot_b.call_count == 0

    def test_emit_two_slots_with_arguments(self, inspect):
        self.signal_b.connect(self.slot_a)
        self.signal_b.connect(self.slot_b)

        self.signal_b.emit(foo='bar')

        self.slot_a.assert_called_once_with(foo='bar')
        self.slot_b.assert_called_once_with(foo='bar')

    def test_reconnect_does_not_duplicate(self, inspect):
        self.signal_a.connect(self.slot_a)
        self.signal_a.connect(self.slot_a)
        self.signal_a.emit()

        self.slot_a.assert_called_once_with()

    def test_disconnect_does_not_fail_on_not_connected_slot(self, inspect):
        self.signal_a.disconnect(self.slot_b)


def test_anonymous_signal_has_nice_repr():
    signal = Signal()
    assert repr(signal) == '<signalslot.Signal: NO_NAME>'


def test_named_signal_has_a_nice_repr():
    signal = Signal(name='update_stuff')
    assert repr(signal) == '<signalslot.Signal: update_stuff>'


class TestSignalConnect(object):
    def setup_method(self, method):
        self.signal = Signal()

    def test_connect_with_kwargs(self):
        def cb(**kwargs):
            pass

        self.signal.connect(cb)

    def test_connect_without_kwargs(self):
        def cb():
            pass

        with pytest.raises(SlotMustAcceptKeywords):
            self.signal.connect(cb)


class MyTestError(Exception):
    pass


class TestException(object):
    def setup_method(self, method):
        self.signal = Signal(threadsafe=False)
        self.seen_exception = False

        def failing_slot(**args):
            raise MyTestError('die!')

        self.signal.connect(failing_slot)

    def test_emit_exception(self):
        try:
            self.signal.emit()
        except MyTestError:
            self.seen_exception = True

        assert self.seen_exception


class TestStrongSlot(object):
    def setup_method(self, method):
        self.called = False

        def slot(**kwargs):
            self.called = True

        self.slot = Slot(slot)

    def test_alive(self):
        assert self.slot.is_alive

    def test_call(self):
        self.slot(testing=1234)
        assert self.called


class TestWeakFuncSlot(object):
    def setup_method(self, method):
        self.called = False

        def slot(**kwargs):
            self.called = True

        self.slot = Slot(slot, weak=True)
        self.slot_ref = slot

    def test_alive(self):
        assert self.slot.is_alive
        assert repr(self.slot) == '<signalslot.Slot: %s>' % repr(self.slot_ref)

    def test_call(self):
        self.slot(testing=1234)
        assert self.called

    def test_gc(self):
        self.slot_ref = None
        assert not self.slot.is_alive
        assert repr(self.slot) == '<signalslot.Slot: dead>'
        self.slot(testing=1234)


class TestWeakMethodSlot(object):
    def setup_method(self, method):

        class MyObject(object):

            def __init__(self):
                self.called = False

            def slot(self, **kwargs):
                self.called = True

        self.obj_ref = MyObject()
        self.slot = Slot(self.obj_ref.slot, weak=True)
        self.signal = Signal()
        self.signal.connect(self.slot)

    def test_alive(self):
        assert self.slot.is_alive

    def test_call(self):
        self.signal.emit(testing=1234)
        assert self.obj_ref.called

    def test_gc(self):
        self.obj_ref = None
        assert not self.slot.is_alive
        self.signal.emit(testing=1234)


class TestSlotEq(object):
    def setup_method(self, method):
        self.slot_a = Slot(self.slot, weak=False)
        self.slot_b = Slot(self.slot, weak=True)

    def slot(self, **kwargs):
        pass

    def test_eq_other(self):
        assert self.slot_a == self.slot_b

    def test_eq_func(self):
        assert self.slot_a == self.slot
