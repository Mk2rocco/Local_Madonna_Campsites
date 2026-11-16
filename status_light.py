"""Coordinate display flashes and update flashes on the shared status LED."""
import logging
import threading

log = logging.getLogger(__name__)


class StatusLight:
    def __init__(self, led, flash_time=0.15):
        self.led = led
        self.flash_time = max(0.05, flash_time)
        self.updating = False
        self.refreshing = False
        self.lock = threading.Lock()

    def _blink(self):
        if self.led is not None:
            try:
                self.led.blink(on_time=self.flash_time, off_time=self.flash_time, background=True)
            except Exception:
                log.warning('Status LED could not blink', exc_info=True)

    def _off(self):
        if self.led is not None:
            try:
                self.led.off()
            except Exception:
                log.warning('Status LED could not turn off', exc_info=True)

    def begin_update(self):
        with self.lock:
            self.updating = True
            self._blink()

    def end_update(self):
        with self.lock:
            self.updating = False
            if not self.refreshing:
                self._off()

    def begin_refresh(self):
        with self.lock:
            self.refreshing = True
            self._blink()

    def end_refresh(self):
        with self.lock:
            self.refreshing = False
            if not self.updating:
                self._off()

    def flash_display(self):
        with self.lock:
            if self.updating or self.refreshing or self.led is None:
                return None
            self._blink()

        def stop():
            with self.lock:
                # A pending display timer must not cancel update feedback.
                if not self.updating and not self.refreshing:
                    self._off()
        return stop

    def close(self):
        self.end_refresh()
        self.end_update()
        if self.led is not None:
            try:
                self.led.close()
            except Exception:
                log.debug('Status LED close failed', exc_info=True)

