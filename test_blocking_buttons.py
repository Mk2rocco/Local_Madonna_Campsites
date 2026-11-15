"""Exercise real blocking selector waits with pipe-backed simulated GPIO events."""
import os
import selectors
import struct
import threading
import time
import unittest
from unittest.mock import Mock, patch

from blocking_buttons import BlockingButtons, EdgeButton, request_line, _GET_LINE, _GET_VALUES
from button_update import ButtonUpdateChord


class RecordingSelector:
    def __init__(self):
        self.real = selectors.DefaultSelector()
        self.calls = []
        self.waiting = threading.Event()
    def register(self, *args):
        return self.real.register(*args)
    def select(self, timeout=None):
        self.calls.append(timeout)
        self.waiting.set()
        return self.real.select(timeout)
    def close(self):
        self.real.close()


class BlockingButtonTests(unittest.TestCase):
    def setUp(self):
        self.writers = {}
        def line_request(chip, pin, pull_up):
            read, write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            self.writers[pin] = write
            return read, False
        self.selector = RecordingSelector()
        with patch('blocking_buttons.selectors.DefaultSelector', return_value=self.selector):
            self.bank = BlockingButtons(line_request=line_request)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.bank.close()
        for write in self.writers.values():
            os.close(write)

    def edge(self, pin, pressed):
        data = struct.pack('=QIIII6I', time.monotonic_ns(), 1 if pressed else 2,
                           pin, 1, 1, *([0] * 6))
        os.write(self.writers[pin], data)

    def test_idle_blocks_without_periodic_wakeups_and_close_wakes_it(self):
        self.bank.button(5)
        self.bank.start()
        self.assertTrue(self.selector.waiting.wait(1))
        self.assertEqual(self.selector.calls, [None])
        # Give a periodic-poll implementation time to expose extra wakeups.
        self.assertFalse(self.bank.stop.wait(0.05))
        self.assertEqual(self.selector.calls, [None])
        self.bank.close()
        self.assertFalse(self.bank.thread.is_alive())
        self.bank.close()  # idempotent

    def test_real_events_deliver_press_and_release(self):
        button = self.bank.button(5, bounce_time=0)
        pressed, released = threading.Event(), threading.Event()
        button.when_pressed = pressed.set
        button.when_released = released.set
        self.bank.start()
        self.edge(5, True)
        self.assertTrue(pressed.wait(1))
        self.assertTrue(button.is_pressed)
        self.edge(5, False)
        self.assertTrue(released.wait(1))
        self.assertFalse(button.is_pressed)
        self.assertTrue(all(t is None for t in self.selector.calls))

    def test_switch_bounce_is_coalesced_and_only_has_finite_wait_while_pending(self):
        button = EdgeButton(0, False, 0.05)
        button.when_pressed, button.when_released = Mock(), Mock()
        button.edge(True, 1)
        button.edge(False, 1.01)
        button.edge(True, 1.02)
        button.settle(1.06)
        button.when_pressed.assert_not_called()
        button.settle(1.071)
        button.when_pressed.assert_called_once()
        button.edge(False, 2)
        button.settle(2.051)
        button.when_released.assert_called_once()
        self.assertIsNone(button.deadline)

    def test_real_debounce_wait_returns_to_indefinite_wait(self):
        button = self.bank.button(5, bounce_time=0.01)
        pressed = threading.Event()
        button.when_pressed = pressed.set
        self.bank.start()
        self.edge(5, True)
        self.assertTrue(pressed.wait(1))
        # Wait for the worker to issue its next idle select without sleeping.
        self.bank.close()
        self.assertTrue(any(t is not None and 0 <= t <= 0.01 for t in self.selector.calls))
        self.assertIsNone(button.deadline)

    def test_callback_failure_does_not_kill_event_thread(self):
        button = self.bank.button(5, bounce_time=0)
        received = threading.Event()
        button.when_pressed = Mock(side_effect=ValueError('callback failed'))
        button.when_released = received.set
        with self.assertLogs('blocking_buttons', level='ERROR'):
            self.bank.start()
            self.edge(5, True)
            self.edge(5, False)
            self.assertTrue(received.wait(1))
        self.assertTrue(self.bank.thread.is_alive())

    def test_a_d_hold_still_uses_one_ten_second_timer(self):
        started = threading.Event()
        timers = []
        def timer_factory(delay, callback):
            timer = Mock()
            timer.delay, timer.callback = delay, callback
            timer.start.side_effect = started.set
            timers.append(timer)
            return timer
        update = Mock()
        chord = ButtonUpdateChord(callback=update, timer_factory=timer_factory)
        a, d = self.bank.button(5, bounce_time=0), self.bank.button(24, bounce_time=0)
        a.when_pressed = lambda: chord.press('A')
        d.when_pressed = lambda: chord.press('D')
        a.when_released = lambda: chord.release('A')
        d.when_released = lambda: chord.release('D')
        self.bank.start()
        self.edge(5, True)
        self.edge(24, True)
        self.assertTrue(started.wait(1))
        self.assertEqual(timers[0].delay, 10)
        update.assert_not_called()
        timers[0].callback()
        timers[0].callback()
        update.assert_called_once()
        self.bank.close()
        chord.close()

    def test_release_before_hold_deadline_cancels_update(self):
        started, released = threading.Event(), threading.Event()
        timers = []
        def factory(delay, callback):
            timer = Mock()
            timer.start.side_effect = started.set
            timer.callback = callback
            timers.append(timer)
            return timer
        update = Mock()
        chord = ButtonUpdateChord(callback=update, timer_factory=factory)
        a, d = self.bank.button(5, bounce_time=0), self.bank.button(24, bounce_time=0)
        a.when_pressed, d.when_pressed = lambda: chord.press('A'), lambda: chord.press('D')
        def release_a():
            chord.release('A')
            released.set()
        a.when_released = release_a
        self.bank.start()
        self.edge(5, True)
        self.edge(24, True)
        self.assertTrue(started.wait(1))
        self.edge(5, False)
        self.assertTrue(released.wait(1))
        timers[0].callback()
        update.assert_not_called()
        timers[0].cancel.assert_called_once()
        self.bank.close()
        chord.close()

    def test_buffered_tap_keeps_its_kernel_timing(self):
        button = self.bank.button(5, bounce_time=0.01)
        pressed, released = threading.Event(), threading.Event()
        button.when_pressed, button.when_released = pressed.set, released.set
        now = time.monotonic_ns()
        def event(timestamp, identifier):
            return struct.pack('=QIIII6I', timestamp, identifier, 5, 1, 1, *([0] * 6))
        # Both edges are already buffered before the thread runs; their original
        # spacing, rather than read time, determines whether this was a tap.
        os.write(self.writers[5], event(now - 100_000_000, 1) + event(now - 50_000_000, 2))
        self.bank.start()
        self.assertTrue(pressed.wait(1))
        self.assertTrue(released.wait(1))

    def test_starting_with_pressed_button_does_not_emit_phantom_press(self):
        button = EdgeButton(0, True, 0)
        button.when_pressed, button.when_released = Mock(), Mock()
        button.edge(True, 0)
        button.settle(0)
        button.when_pressed.assert_not_called()
        button.edge(False, 1)
        button.settle(1)
        button.when_released.assert_called_once()

    def test_duplicate_pin_and_late_binding_are_rejected(self):
        self.bank.button(5)
        with self.assertRaises(ValueError):
            self.bank.button(5)
        self.bank.start()
        with self.assertRaises(RuntimeError):
            self.bank.button(6)

    def test_line_request_failure_does_not_prevent_other_buttons(self):
        self.bank.line_request = Mock(side_effect=PermissionError('GPIO access'))
        with self.assertRaises(PermissionError):
            self.bank.button(5)
        self.assertEqual(self.bank.buttons, [])


class KernelRequestTests(unittest.TestCase):
    def test_v2_request_preserves_pull_up_polarity_and_initial_state(self):
        calls = []
        def ioctl(fd, request, buffer, mutate):
            calls.append((fd, request, bytes(buffer)))
            if request == _GET_LINE:
                struct.pack_into('=i', buffer, 588, 100)
            else:
                self.assertEqual(request, _GET_VALUES)
                struct.pack_into('=Q', buffer, 0, 1)
        with patch('blocking_buttons.os.open', return_value=99), \
             patch('blocking_buttons.os.close') as close, \
             patch('blocking_buttons.os.set_inheritable'), \
             patch('blocking_buttons.os.set_blocking'), \
             patch('blocking_buttons.fcntl.ioctl', side_effect=ioctl):
            fd, pressed = request_line('/dev/gpiochip0', 5, True)
        self.assertEqual((fd, pressed), (100, True))
        close.assert_called_once_with(99)
        flags = struct.unpack_from('=Q', calls[0][2], 288)[0]
        self.assertTrue(flags & (1 << 1))  # active low with pull-up
        self.assertTrue(flags & (1 << 8))
        self.assertEqual(struct.unpack_from('=I', calls[0][2], 0)[0], 5)

    def test_pull_down_does_not_invert_press_edges(self):
        def ioctl(fd, request, buffer, mutate):
            if request == _GET_LINE:
                flags = struct.unpack_from('=Q', buffer, 288)[0]
                self.assertFalse(flags & (1 << 1))
                self.assertTrue(flags & (1 << 9))
                struct.pack_into('=i', buffer, 588, 100)
        with patch('blocking_buttons.os.open', return_value=99), \
             patch('blocking_buttons.os.close'), \
             patch('blocking_buttons.os.set_inheritable'), \
             patch('blocking_buttons.os.set_blocking'), \
             patch('blocking_buttons.fcntl.ioctl', side_effect=ioctl):
            self.assertEqual(request_line('/dev/gpiochip0', 5, False), (100, False))

    def test_failed_initial_read_closes_both_kernel_descriptors(self):
        def ioctl(fd, request, buffer, mutate):
            if request == _GET_LINE:
                struct.pack_into('=i', buffer, 588, 100)
            else:
                raise OSError('read failed')
        with patch('blocking_buttons.os.open', return_value=99), \
             patch('blocking_buttons.os.close') as close, \
             patch('blocking_buttons.os.set_inheritable'), \
             patch('blocking_buttons.os.set_blocking'), \
             patch('blocking_buttons.fcntl.ioctl', side_effect=ioctl):
            with self.assertRaises(OSError):
                request_line('/dev/gpiochip0', 5, True)
        self.assertEqual([c.args[0] for c in close.call_args_list], [99, 100])


if __name__ == '__main__':
    unittest.main()
