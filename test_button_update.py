"""Deterministic button gesture tests; GPIO hardware is not required."""
import unittest
from unittest.mock import Mock, patch
from button_update import ButtonUpdateChord, request_update


class FakeTimer:
    def __init__(self, delay, callback):
        self.delay, self.callback = delay, callback
        self.cancelled = False
    def start(self):
        pass
    def cancel(self):
        self.cancelled = True


class ChordTests(unittest.TestCase):
    def setUp(self):
        self.callback = Mock()
        self.timers = []
        def factory(delay, callback):
            timer = FakeTimer(delay, callback)
            self.timers.append(timer)
            return timer
        self.chord = ButtonUpdateChord(callback=self.callback, timer_factory=factory)

    def test_a_alone_keeps_normal_selection(self):
        self.chord.press('A')
        self.assertTrue(self.chord.release('A'))
        self.assertEqual(self.timers, [])
        self.callback.assert_not_called()

    def test_d_alone_selects_advisory_view(self):
        self.chord.press('D')
        self.assertTrue(self.chord.release('D'))
        self.assertEqual(self.timers, [])

    def test_ten_second_chord_in_either_order(self):
        for order in [('A', 'D'), ('D', 'A')]:
            with self.subTest(order=order):
                for name in order:
                    self.chord.press(name)
                self.assertEqual(self.timers[-1].delay, 10)
                self.timers[-1].callback()
                self.timers[-1].callback()
                self.assertFalse(self.chord.release('A'))
                self.chord.release('D')
        self.assertEqual(self.callback.call_count, 2)

    def test_short_chord_cancels_update_and_view_change(self):
        self.chord.press('A')
        self.chord.press('D')
        self.chord.release('D')
        self.timers[-1].callback()
        self.callback.assert_not_called()
        self.assertFalse(self.chord.release('A'))
        self.assertTrue(self.timers[-1].cancelled)

    def test_both_buttons_must_be_released_before_rearming(self):
        self.chord.press('A')
        self.chord.press('D')
        self.timers[-1].callback()
        self.chord.release('A')
        self.chord.press('A')
        self.assertEqual(len(self.timers), 1)
        self.timers[-1].callback()
        self.callback.assert_called_once()

    def test_cancelled_timer_cannot_fire_a_new_chord_early(self):
        self.chord.press('A')
        self.chord.press('D')
        old = self.timers[-1]
        self.chord.release('A')
        self.chord.release('D')
        self.chord.press('A')
        self.chord.press('D')
        old.callback()
        self.callback.assert_not_called()
        self.timers[-1].callback()
        self.callback.assert_called_once()

    def test_close_prevents_pending_update(self):
        self.chord.press('A')
        self.chord.press('D')
        self.chord.close()
        self.timers[-1].callback()
        self.callback.assert_not_called()

    @patch('button_update.os.geteuid', return_value=1000)
    @patch('button_update.subprocess.run')
    def test_unprivileged_request_is_noninteractive(self, run, uid):
        request_update()
        run.assert_called_once_with(['sudo', '-n', '/usr/bin/systemctl', 'start',
                                     'campsites-update.service'],
                                    check=True, timeout=660)

    @patch('button_update.os.geteuid', return_value=0)
    @patch('button_update.subprocess.run')
    def test_root_service_does_not_require_sudo(self, run, uid):
        request_update()
        self.assertEqual(run.call_args.args[0][0], '/usr/bin/systemctl')

    @patch('button_update.subprocess.run', side_effect=FileNotFoundError('systemctl'))
    def test_missing_installation_logs_error_without_crashing_display(self, run):
        with self.assertLogs('button_update', level='ERROR'):
            request_update()


if __name__ == '__main__':
    unittest.main()


