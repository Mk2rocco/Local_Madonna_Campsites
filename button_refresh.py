"""A one-shot long press without GPIO polling or blocking the edge thread."""
import threading


class RefreshHold:
    def __init__(self, callback, hold_seconds=5, timer_factory=threading.Timer):
        self.callback = callback
        self.hold_seconds = hold_seconds
        self.timer_factory = timer_factory
        self.lock = threading.Lock()
        self.timer = None
        self.generation = 0
        self.pressed = False
        self.fired = False

    def press(self):
        with self.lock:
            if self.pressed:
                return
            self.pressed = True
            self.fired = False
            self.generation += 1
            generation = self.generation
            self.timer = self.timer_factory(self.hold_seconds, lambda: self._fire(generation))
            self.timer.daemon = True
            self.timer.start()

    def _fire(self, generation):
        with self.lock:
            if generation != self.generation or not self.pressed or self.fired:
                return
            self.fired = True
        self.callback()

    def release(self):
        with self.lock:
            select = self.pressed and not self.fired
            self.pressed = False
            self.generation += 1
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
            return select

    def close(self):
        self.release()
