"""Blocking Linux GPIO v2 edge events for Inky buttons (kernel 5.10+).

Use the stable <linux/gpio.h> UAPI through Python's standard library. No
GPIOZero/lgpio alert objects, GPIO sampling loop, or third-party binding is
needed. The v2 ABI explicitly aligns its 64-bit fields on both 32/64-bit Linux.
"""
import fcntl
import logging
import os
import selectors
import struct
import threading
import time

log = logging.getLogger(__name__)
# _IOWR(0xB4, ..., struct size) from <linux/gpio.h> on Raspberry Pi Linux.
_GET_LINE = 0xC250B407       # struct gpio_v2_line_request: 592 bytes
_GET_VALUES = 0xC010B40E     # struct gpio_v2_line_values: 16 bytes
_INPUT = 1 << 2
_ACTIVE_LOW = 1 << 1
_RISING = 1 << 4
_FALLING = 1 << 5
_PULL_UP = 1 << 8
_PULL_DOWN = 1 << 9
_EVENT_SIZE = 48            # struct gpio_v2_line_event


def request_line(chip, pin, pull_up):
    """Return a nonblocking event fd and its current logical pressed state."""
    request = bytearray(592)
    struct.pack_into('=I', request, 0, pin)
    consumer = b'campsites-buttons'
    request[256:256 + len(consumer)] = consumer
    flags = _INPUT | _RISING | _FALLING
    flags |= (_PULL_UP | _ACTIVE_LOW) if pull_up else _PULL_DOWN
    struct.pack_into('=Q', request, 288, flags)
    struct.pack_into('=I', request, 560, 1)  # num_lines
    chip_fd = os.open(chip, os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.ioctl(chip_fd, _GET_LINE, request, True)
    finally:
        os.close(chip_fd)
    fd = struct.unpack_from('=i', request, 588)[0]
    try:
        os.set_inheritable(fd, False)
        os.set_blocking(fd, False)
        values = bytearray(struct.pack('=QQ', 0, 1))
        fcntl.ioctl(fd, _GET_VALUES, values, True)
        return fd, bool(struct.unpack_from('=Q', values)[0] & 1)
    except BaseException:
        os.close(fd)
        raise


class EdgeButton:
    def __init__(self, fd, pressed, bounce_time):
        self.fd = fd
        self.is_pressed = pressed
        self.bounce_time = max(0.0, float(bounce_time or 0))
        self.when_pressed = None
        self.when_released = None
        self.pending = None
        self.deadline = None
        self.closed = False

    def edge(self, pressed, now):
        if self.closed:
            return
        self.pending = pressed
        self.deadline = now + self.bounce_time

    def settle(self, now):
        if self.closed or self.deadline is None or now < self.deadline:
            return
        pressed = self.pending
        self.pending = self.deadline = None
        if pressed == self.is_pressed:
            return
        self.is_pressed = pressed
        callback = self.when_pressed if pressed else self.when_released
        if callback is not None:
            try:
                callback()
            except Exception:
                log.exception('Button callback failed')

    def close(self):
        self.closed = True
        self.when_pressed = self.when_released = None
        self.pending = self.deadline = None


class BlockingButtons:
    """One shared selector; idle select has no timeout. close() wakes it by pipe."""
    def __init__(self, chip='/dev/gpiochip0', line_request=request_line):
        self.chip = chip
        self.line_request = line_request
        self.buttons = []
        self.pins = set()
        self.selector = selectors.DefaultSelector()
        self.wake_read, self.wake_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.selector.register(self.wake_read, selectors.EVENT_READ, None)
        self.stop = threading.Event()
        self.thread = None
        self.closed = False

    def button(self, pin, *, bounce_time=0.05, pull_up=False):
        if self.thread is not None or self.closed:
            raise RuntimeError('Bind buttons before starting the event loop')
        if pin in self.pins:
            raise ValueError(f'GPIO {pin} already bound')
        fd, pressed = self.line_request(self.chip, pin, pull_up)
        try:
            button = EdgeButton(fd, pressed, bounce_time)
            self.selector.register(fd, selectors.EVENT_READ, button)
        except BaseException:
            os.close(fd)
            raise
        self.buttons.append(button)
        self.pins.add(pin)
        return button

    def start(self):
        if self.closed:
            raise RuntimeError('Button event loop is closed')
        if self.thread is None and self.buttons:
            self.thread = threading.Thread(target=self._run, name='gpio-edges', daemon=True)
            self.thread.start()
            log.info('Blocking GPIO edge events active on %s', self.chip)

    def _timeout(self, now):
        deadlines = [b.deadline for b in self.buttons if b.deadline is not None and not b.closed]
        return max(0.0, min(deadlines) - now) if deadlines else None

    def _run(self):
        try:
            while not self.stop.is_set():
                # With no debounce pending this blocks until an actual edge or
                # shutdown. No periodic GPIO checks or idle timer wakeups.
                events = self.selector.select(self._timeout(time.monotonic()))
                if self.stop.is_set():
                    break
                for key, _ in events:
                    button = key.data
                    if button is None:
                        continue
                    while True:
                        try:
                            data = os.read(button.fd, _EVENT_SIZE * 16)
                        except BlockingIOError:
                            break
                        if not data or len(data) % _EVENT_SIZE:
                            raise OSError('GPIO event stream closed or returned a partial event')
                        for offset in range(0, len(data), _EVENT_SIZE):
                            event = struct.unpack_from('=I', data, offset + 8)[0]
                            if event not in (1, 2):
                                continue
                            event_time = struct.unpack_from('=Q', data, offset)[0] / 1_000_000_000
                            # Use the kernel's monotonic timestamp so a delayed
                            # read does not collapse a complete tap into bounce.
                            button.settle(event_time)
                            button.edge(event == 1, event_time)
                            if button.bounce_time == 0:
                                button.settle(event_time)
                now = time.monotonic()
                for button in self.buttons:
                    button.settle(now)
        except Exception:
            log.exception('Blocking GPIO event handling failed; restart the display service')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        os.write(self.wake_write, b'x')
        if self.thread is not None:
            self.thread.join()
        for button in self.buttons:
            button.close()
            os.close(button.fd)
        self.selector.close()
        os.close(self.wake_read)
        os.close(self.wake_write)
