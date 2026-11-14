"""Recognize the Inky A+D hold gesture and request an external update job."""
import logging
import os
import subprocess
import threading

log = logging.getLogger(__name__)


def request_update():
    """Queue the job outside the display process so it can restart that process."""
    command = ['/usr/bin/systemctl', 'start', '--no-block', 'campsites-update.service']
    if os.geteuid() != 0:
        command = ['sudo', '-n', *command]
    try:
        subprocess.run(command, check=True, timeout=10)
        log.info('GitHub update requested; see journalctl -u campsites-update.service')
    except (OSError, subprocess.SubprocessError):
        log.exception('Cannot request update; run sudo python3 scripts/install_button_update.py first')


class ButtonUpdateChord:
    """One update per A+D hold, rearmed only after both buttons are released."""
    def __init__(self, hold_seconds=10, callback=request_update, timer_factory=threading.Timer):
        if hold_seconds <= 0:
            raise ValueError('Update hold duration must be positive')
        self.hold_seconds = hold_seconds
        self.callback = callback
        self.timer_factory = timer_factory
        self.pressed = set()
        self.suppress_a = False
        self.fired = False
        self.timer = None
        self.generation = 0
        self.lock = threading.Lock()

    def press(self, name):
        with self.lock:
            self.pressed.add(name)
            if self.pressed == {'A', 'D'} and not self.suppress_a:
                self.suppress_a = True
                self.generation += 1
                generation = self.generation
                timer = self.timer_factory(self.hold_seconds, lambda: self._fire(generation))
                timer.daemon = True
                self.timer = timer
                timer.start()

    def release(self, name):
        """Return True when A was used alone and should select its normal view."""
        with self.lock:
            select_a = name == 'A' and name in self.pressed and not self.suppress_a
            self.pressed.discard(name)
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
                self.generation += 1
            if not self.pressed:
                self.suppress_a = False
                self.fired = False
            return select_a

    def _fire(self, generation):
        with self.lock:
            if generation != self.generation or self.pressed != {'A', 'D'} or self.fired:
                return
            self.fired = True
        self.callback()

    def close(self):
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
                self.generation += 1
            self.pressed.clear()
