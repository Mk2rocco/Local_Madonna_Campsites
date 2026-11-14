"""Recognize the Inky A+D hold gesture and request an external update job."""
import logging
import os
import subprocess
import threading

log = logging.getLogger(__name__)


_request_lock = threading.Lock()


def request_update(on_start=None, on_finish=None):
    """Wait in the button's worker thread while the independent update job runs."""
    if not _request_lock.acquire(blocking=False):
        log.info('An update request is already running')
        return
    command = ['/usr/bin/systemctl', 'start', 'campsites-update.service']
    if os.geteuid() != 0:
        command = ['sudo', '-n', *command]
    try:
        if on_start is not None:
            on_start()
        # The service owns the update; stopping the display may kill this client,
        # but does not kill the separate updater service. No main-loop blocking.
        subprocess.run(command, check=True, timeout=660)
        log.info('GitHub update check finished; see journalctl -u campsites-update.service')
    except (OSError, subprocess.SubprocessError):
        log.exception('Update request failed; check updater logs and rerun the button installer if needed')
    finally:
        try:
            if on_finish is not None:
                on_finish()
        finally:
            _request_lock.release()


class ButtonUpdateChord:
    """One update per A+D hold, rearmed only after both buttons are released."""
    def __init__(self, hold_seconds=10, callback=request_update, timer_factory=threading.Timer):
        if hold_seconds <= 0:
            raise ValueError('Update hold duration must be positive')
        self.hold_seconds = hold_seconds
        self.callback = callback
        self.timer_factory = timer_factory
        self.pressed = set()
        self.suppress_selection = False
        self.fired = False
        self.timer = None
        self.generation = 0
        self.lock = threading.Lock()

    def press(self, name):
        with self.lock:
            self.pressed.add(name)
            if self.pressed == {'A', 'D'} and not self.suppress_selection:
                self.suppress_selection = True
                self.generation += 1
                generation = self.generation
                timer = self.timer_factory(self.hold_seconds, lambda: self._fire(generation))
                timer.daemon = True
                self.timer = timer
                timer.start()

    def release(self, name):
        """Return True for a single A or D press that should select its view."""
        with self.lock:
            select_view = name in {'A', 'D'} and name in self.pressed and not self.suppress_selection
            self.pressed.discard(name)
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
                self.generation += 1
            if not self.pressed:
                self.suppress_selection = False
                self.fired = False
            return select_view

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


