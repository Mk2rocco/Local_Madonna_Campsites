"""Verify update feedback and coordination with normal display flashing."""
import subprocess
import unittest
from unittest.mock import Mock, patch
from button_update import request_update, _request_lock
from status_light import StatusLight


class StatusLightTests(unittest.TestCase):
    def test_flash_while_check_runs_and_stop_when_complete(self):
        led = Mock()
        light = StatusLight(led)
        def check(command, **kwargs):
            self.assertTrue(light.updating)
            led.blink.assert_called_once()
            led.off.assert_not_called()
        with patch('button_update.subprocess.run', side_effect=check):
            request_update(on_start=light.begin_update, on_finish=light.end_update)
        self.assertFalse(light.updating)
        led.off.assert_called_once()

    def test_failed_request_stops_flashing(self):
        led = Mock()
        light = StatusLight(led)
        with patch('button_update.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'systemctl')):
            with self.assertLogs('button_update', level='ERROR'):
                request_update(on_start=light.begin_update, on_finish=light.end_update)
        led.off.assert_called_once()
        self.assertFalse(light.updating)
        self.assertFalse(_request_lock.locked())

    def test_pending_display_stop_cannot_cancel_update_flash(self):
        led = Mock()
        light = StatusLight(led)
        stop_display = light.flash_display()
        light.begin_update()
        stop_display()
        led.off.assert_not_called()
        self.assertIsNone(light.flash_display())
        light.end_update()
        led.off.assert_called_once()
        self.assertIsNotNone(light.flash_display())

    def test_repeated_request_does_not_clear_feedback_of_running_request(self):
        start, finish = Mock(), Mock()
        _request_lock.acquire()
        try:
            with patch('button_update.subprocess.run') as run:
                request_update(on_start=start, on_finish=finish)
            start.assert_not_called()
            finish.assert_not_called()
            run.assert_not_called()
        finally:
            _request_lock.release()

    def test_led_failure_does_not_prevent_update(self):
        led = Mock()
        led.blink.side_effect = OSError('GPIO unavailable')
        led.off.side_effect = OSError('GPIO unavailable')
        light = StatusLight(led)
        with patch('button_update.subprocess.run') as run:
            with self.assertLogs('status_light', level='WARNING'):
                request_update(on_start=light.begin_update, on_finish=light.end_update)
        run.assert_called_once()

    def test_no_led_remains_supported(self):
        light = StatusLight(None)
        with patch('button_update.subprocess.run') as run:
            request_update(on_start=light.begin_update, on_finish=light.end_update)
        run.assert_called_once()
        self.assertIsNone(light.flash_display())
        light.close()


if __name__ == '__main__':
    unittest.main()
