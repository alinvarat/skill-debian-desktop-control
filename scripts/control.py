"""Interactive GNOME desktop control through a user-approved portal session.

Mouse moves, clicks and drags follow smooth human-like curves by default (see the
`speed` command). Keyboard supports chords, hold/release, evdev keycodes and
Unicode typing. Run with --remember to keep GNOME consent between sessions.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import math
import os
from pathlib import Path
import random
import secrets
import shlex
import shutil
import struct
import subprocess
import tempfile
import sys
import time
import zlib

import gi
gi.require_version('Gdk', '4.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gdk, Gio, GLib, Gst

from request_access import bus, desktop, destination, interface, request

SCREENCAST = 'org.freedesktop.portal.ScreenCast'
STATE = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'debian-desktop-control'
TOKEN = STATE / 'restore-token'
BUTTONS = {'left': 272, 'right': 273, 'middle': 274, 'back': 275, 'forward': 276}
# Frame format -> byte offsets of R, G and B inside one 4-byte pixel.
CHANNEL_OFFSETS = {
    'BGRx': (2, 1, 0), 'BGRA': (2, 1, 0), 'RGBx': (0, 1, 2), 'RGBA': (0, 1, 2),
    'xRGB': (1, 2, 3), 'ARGB': (1, 2, 3), 'xBGR': (3, 2, 1), 'ABGR': (3, 2, 1),
}
PNG_THREADS = 8
png_pool = ThreadPoolExecutor(PNG_THREADS)
# speed name -> (duration multiplier, typing delay range in seconds, click pause range)
SPEEDS = {
    'human': (1.0, (0.030, 0.085), (0.030, 0.080)),
    'fast': (0.35, (0.004, 0.012), (0.008, 0.020)),
    'slow': (1.8, (0.060, 0.150), (0.060, 0.140)),
    'instant': (0.0, (0.0, 0.0), (0.0, 0.0)),
}
KEY_ALIASES = {
    'ctrl': 'Control_L', 'control': 'Control_L', 'alt': 'Alt_L', 'shift': 'Shift_L',
    'super': 'Super_L', 'win': 'Super_L', 'meta': 'Super_L', 'cmd': 'Super_L',
    'enter': 'Return', 'return': 'Return', 'esc': 'Escape', 'escape': 'Escape',
    'space': 'space', 'tab': 'Tab', 'backspace': 'BackSpace', 'bksp': 'BackSpace',
    'del': 'Delete', 'delete': 'Delete', 'ins': 'Insert', 'insert': 'Insert',
    'pgup': 'Page_Up', 'pageup': 'Page_Up', 'pgdn': 'Page_Down', 'pagedown': 'Page_Down',
    'home': 'Home', 'end': 'End', 'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right',
    'caps': 'Caps_Lock', 'capslock': 'Caps_Lock', 'menu': 'Menu', 'print': 'Print',
    'plus': 'plus', 'minus': 'minus',
}

# Physical (evdev) key codes of a US keyboard. Used for chords and shortcuts so they
# work no matter which input layout (for example Thai) is active.
KEYCODES = {
    **{c: n for c, n in zip('qwertyuiop', range(16, 26))},
    **{c: n for c, n in zip('asdfghjkl', range(30, 39))},
    **{c: n for c, n in zip('zxcvbnm', range(44, 51))},
    **{c: n for c, n in zip('1234567890', range(2, 12))},
    '-': 12, '=': 13, '[': 26, ']': 27, ';': 39, "'": 40, '`': 41, '\\': 43, ',': 51, '.': 52, '/': 53,
    'escape': 1, 'backspace': 14, 'tab': 15, 'return': 28, 'space': 57, 'caps_lock': 58,
    'control_l': 29, 'control_r': 97, 'shift_l': 42, 'shift_r': 54, 'alt_l': 56, 'alt_r': 100,
    'super_l': 125, 'super_r': 126, 'menu': 127, 'print': 99, 'insert': 110, 'delete': 111,
    'home': 102, 'end': 107, 'page_up': 104, 'page_down': 109,
    'up': 103, 'down': 108, 'left': 105, 'right': 106,
    **{f'f{n}': 58 + n for n in range(1, 11)}, 'f11': 87, 'f12': 88,
    'minus': 12, 'equal': 13, 'plus': 13, 'comma': 51, 'period': 52, 'slash': 53,
    'semicolon': 39, 'apostrophe': 40, 'grave': 41, 'backslash': 43,
    'bracketleft': 26, 'bracketright': 27,
}
HELP = {
    'streams': 'streams',
    'shot': 'shot STREAM /absolute/output.png',
    'where': 'where  (tracked pointer position per stream, in PNG pixels)',
    'speed': 'speed human|fast|slow|instant',
    'move': 'move STREAM X Y   (smooth curve; "jump STREAM X Y" teleports)',
    'jump': 'jump STREAM X Y',
    'click': 'click STREAM X Y [left|right|middle|back|forward] [COUNT]',
    'down': 'down [left|right|middle|back|forward]',
    'up': 'up [left|right|middle|back|forward]',
    'drag': 'drag STREAM X1 Y1 X2 Y2 [button]',
    'drag-between': 'drag-between SOURCE X1 Y1 DESTINATION X2 Y2',
    'scroll': 'scroll vertical|horizontal STEPS  (positive = down/right, notches)',
    'smoothscroll': 'smoothscroll vertical|horizontal PIXELS  (eased, continuous)',
    'key': 'key KEY[+KEY...] [COUNT]  (physical keys, layout independent: ctrl+shift+t, Tab 3, F5)',
    'keydown': 'keydown KEY',
    'keyup': 'keyup KEY',
    'hold': 'hold KEY[+KEY...] SECONDS',
    'keycode': 'keycode EVDEV_CODE[+CODE...]  (example: 30 = A)',
    'type': 'type "text"  (any language, via clipboard; restores text clipboard)',
    'typekeys': 'typekeys "text"  (one character at a time with human delays, any layout)',
    'paste': 'paste "Unicode text" (replaces system clipboard)',
    'wait': 'wait SECONDS',
    'quit': 'quit',
}


def portal_call(path, api, method, signature, *args):
    return bus.call_sync(destination, path, api, method, GLib.Variant(signature, args),
                         None, Gio.DBusCallFlags.NONE, 5000, None)


def checked_request(method, signature, args, options, api=interface):
    code, result = request(method, signature, args, options, api)
    if code != 0:
        raise RuntimeError(f'{method} returned {code}')
    return result


def min_jerk(t):
    return t * t * t * (10 + t * (-15 + 6 * t))


def sleep_until(deadline):
    remaining = deadline - time.perf_counter()
    if remaining > 0:
        time.sleep(remaining)


class Desktop:
    def __init__(self, session, streams):
        self.session = session
        self.streams = dict(streams)
        self.pipelines = {}
        self.frame_sizes = {}
        self.last_frames = {}
        self.pos = {}              # stream -> tracked pointer position, PNG pixels
        self.speed = 'fast'        # smooth but quick; the user does not want teleporting
        self.last_input = 0.0
        self.rng = random.Random()

    # ---------------------------------------------------------------- portal
    def send(self, action, signature, *args, options=None):
        self.last_input = time.monotonic()
        portal_call(desktop, interface, 'Notify' + action, '(oa{sv}' + signature + ')',
                    self.session, options or {}, *args)

    def pause(self, bounds):
        low, high = bounds
        if high > 0:
            time.sleep(self.rng.uniform(low, high))

    # ---------------------------------------------------------------- frames
    def open_pipeline(self, stream):
        if stream in self.pipelines:
            return
        response, fds = bus.call_with_unix_fd_list_sync(
            destination, desktop, SCREENCAST, 'OpenPipeWireRemote',
            GLib.Variant('(oa{sv})', (self.session, {})), None,
            Gio.DBusCallFlags.NONE, 5000, None, None)
        fd = fds.get(response.unpack()[0])
        try:
            pipeline = Gst.parse_launch(
                f'pipewiresrc fd={fd} path={stream} ! video/x-raw ! '
                'appsink name=frames max-buffers=1 drop=true sync=false')
            self.pipelines[stream] = (pipeline, fd)
            pipeline.set_state(Gst.State.PLAYING)
        except Exception:
            self.pipelines.pop(stream, None)
            os.close(fd)
            raise

    def grab(self, stream):
        """Return the freshest available frame sample for the stream."""
        if stream not in self.streams:
            raise ValueError(f'Unknown stream {stream}; use the streams command')
        self.open_pipeline(stream)
        # Let the compositor deliver a frame that reflects the last input.
        settle = 0.07 - (time.monotonic() - self.last_input)
        if settle > 0:
            time.sleep(settle)
        pipeline, _ = self.pipelines[stream]
        error = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if error:
            raise RuntimeError(str(error.parse_error()))
        frames = pipeline.get_by_name('frames')
        # The sink always holds the newest frame, so a still screen needs no waiting.
        sample = frames.get_property('last-sample')
        if sample is None:
            sample = frames.emit('try-pull-sample', 120 * Gst.MSECOND)
        if sample is None:
            # Mutter can wait for screen damage before delivering the first frame.
            self.send('PointerMotion', 'dd', 1.0, 0.0)
            try:
                sample = frames.emit('try-pull-sample', 600 * Gst.MSECOND)
            finally:
                self.send('PointerMotion', 'dd', -1.0, 0.0)
        if sample is None:
            raise RuntimeError('No PipeWire frame received')
        pts = sample.get_buffer().pts
        reused = self.last_frames.get(stream) == pts
        self.last_frames[stream] = pts
        caps = sample.get_caps().get_structure(0)
        self.frame_sizes[stream] = (caps.get_value('width'), caps.get_value('height'))
        return sample, reused

    @staticmethod
    def encode_png(sample):
        """Encode a raw frame on request, deflating slices in parallel."""
        caps = sample.get_caps().get_structure(0)
        name = caps.get_value('format')
        if name not in CHANNEL_OFFSETS:
            raise ValueError(f'Unsupported frame format {name}')
        width, height = caps.get_value('width'), caps.get_value('height')
        buffer = sample.get_buffer()
        data = buffer.extract_dup(0, buffer.get_size())
        stride = len(data) // height
        if stride != width * 4:
            data = b''.join(data[y * stride:y * stride + width * 4] for y in range(height))
        row = width * 3
        rgb = bytearray(row * height)
        for channel, offset in enumerate(CHANNEL_OFFSETS[name]):
            rgb[channel::3] = data[offset::4]
        raw = bytearray((row + 1) * height)  # each row starts with filter byte 0
        for y in range(height):
            raw[y * (row + 1) + 1:(y + 1) * (row + 1)] = rgb[y * row:(y + 1) * row]
        raw = bytes(raw)

        def deflate(index):
            start, end = index * len(raw) // PNG_THREADS, (index + 1) * len(raw) // PNG_THREADS
            part = zlib.compressobj(1, zlib.DEFLATED, -15)
            last = index == PNG_THREADS - 1
            return part.compress(raw[start:end]) + part.flush(zlib.Z_FINISH if last else zlib.Z_SYNC_FLUSH)

        body = b'\x78\x01' + b''.join(png_pool.map(deflate, range(PNG_THREADS)))
        body += struct.pack('>I', zlib.adler32(raw))

        def chunk(kind, payload):
            return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))

        header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
        return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', body) + chunk(b'IEND', b'')

    def shot(self, stream, path):
        output = Path(path)
        if not output.is_absolute() or output.suffix.lower() != '.png':
            raise ValueError('Provide an absolute .png output path')
        sample, reused = self.grab(stream)
        png = self.encode_png(sample)
        with output.open('xb') as image:
            image.write(png)
        return {'file': str(output), 'size': self.frame_sizes[stream], 'cached': reused}

    def frame_size(self, stream):
        if stream not in self.frame_sizes:
            self.grab(stream)
        return self.frame_sizes[stream]

    # ------------------------------------------------------------- geometry
    def logical_size(self, stream):
        width, height = self.frame_size(stream)
        return self.streams[stream].get('logical_size', self.streams[stream].get('size', (width, height)))

    def point(self, stream, x, y):
        """PNG pixel -> coordinates the portal expects for absolute motion."""
        width, height = self.frame_size(stream)
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f'Coordinates fall outside the captured frame {width}x{height}')
        # GNOME maps absolute input in buffer pixels but validates it against the
        # logical size, so only the top-left logical-size region is reachable that way.
        logical_width, logical_height = self.streams[stream].get('logical_size', (width, height))
        return x * logical_width / width, y * logical_height / height

    def absolute_ok(self, stream, x, y):
        logical_width, logical_height = self.logical_size(stream)
        sx, sy = self.point(stream, x, y)
        return sx < logical_width - 0.5 and sy < logical_height - 0.5

    def rel_scale(self, stream):
        """Logical pixels per PNG pixel (relative motion is in logical pixels)."""
        width, height = self.frame_size(stream)
        logical_width, _ = self.logical_size(stream)
        return logical_width / width

    def goto(self, stream, x, y):
        """Place the pointer at a PNG pixel using absolute motion, else relative."""
        width, height = self.frame_size(stream)
        x = min(max(x, 0.0), width - 1.0)
        y = min(max(y, 0.0), height - 1.0)
        if self.absolute_ok(stream, x, y):
            self.send('PointerMotionAbsolute', 'udd', stream, *self.point(stream, x, y))
            self.pos[stream] = (x, y)
            return
        if stream not in self.pos:
            # Unknown start: anchor inside the reachable region, finish with relative motion.
            logical_width, logical_height = self.logical_size(stream)
            ax, ay = min(x, logical_width - 2.0), min(y, logical_height - 2.0)
            self.send('PointerMotionAbsolute', 'udd', stream, *self.point(stream, ax, ay))
            self.pos[stream] = (ax, ay)
        px, py = self.pos[stream]
        scale = self.rel_scale(stream)
        self.send('PointerMotion', 'dd', (x - px) * scale, (y - py) * scale)
        self.pos[stream] = (x, y)

    def travel_time(self, distance):
        multiplier = SPEEDS[self.speed][0]
        if multiplier == 0:
            return 0.0
        return min(1.3, (0.10 + 0.14 * math.log2(1 + distance / 30.0))) * multiplier

    def move_path(self, stream, x, y, slow_factor=1.0):
        width, height = self.frame_size(stream)
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f'Coordinates fall outside the captured frame {width}x{height}')
        if stream not in self.pos or SPEEDS[self.speed][0] == 0:
            self.goto(stream, x, y)
            return
        x0, y0 = self.pos[stream]
        dx, dy = x - x0, y - y0
        distance = math.hypot(dx, dy)
        duration = self.travel_time(distance) * slow_factor
        if distance < 1.0 or duration <= 0:
            self.goto(stream, x, y)
            return
        # Gently curved path: control points pushed sideways, eased with min-jerk timing.
        nx, ny = -dy / distance, dx / distance
        bend = min(40.0, distance * 0.06)
        o1 = self.rng.uniform(-bend, bend)
        o2 = self.rng.uniform(-bend, bend)
        c1 = (x0 + dx / 3 + nx * o1, y0 + dy / 3 + ny * o1)
        c2 = (x0 + 2 * dx / 3 + nx * o2, y0 + 2 * dy / 3 + ny * o2)
        steps = max(3, int(duration * 120))
        start = time.perf_counter()
        for i in range(1, steps + 1):
            t = i / steps
            s = min_jerk(t)
            u = 1 - s
            px = u**3 * x0 + 3 * u * u * s * c1[0] + 3 * u * s * s * c2[0] + s**3 * x
            py = u**3 * y0 + 3 * u * u * s * c1[1] + 3 * u * s * s * c2[1] + s**3 * y
            if i < steps:
                jitter = min(0.35, distance / 200.0)
                px += self.rng.uniform(-jitter, jitter)
                py += self.rng.uniform(-jitter, jitter)
            else:
                px, py = x, y
            self.goto(stream, px, py)
            sleep_until(start + duration * t)

    # --------------------------------------------------------------- mouse
    def button(self, name, state):
        self.send('PointerButton', 'iu', BUTTONS[name], state)

    def click(self, stream, x, y, button, count):
        if button not in BUTTONS:
            raise ValueError('Button must be ' + '|'.join(BUTTONS))
        if not 1 <= count <= 3:
            raise ValueError('Click count must be 1–3')
        self.move_path(stream, x, y)
        self.pause(SPEEDS[self.speed][2])
        for index in range(count):
            self.button(button, 1)
            self.pause((0.025, 0.060) if SPEEDS[self.speed][0] else (0, 0))
            self.button(button, 0)
            if index + 1 < count:
                self.pause((0.04, 0.09) if SPEEDS[self.speed][0] else (0, 0))

    def drag(self, stream, x1, y1, x2, y2, destination=None, button='left'):
        if button not in BUTTONS:
            raise ValueError('Button must be ' + '|'.join(BUTTONS))
        destination = stream if destination is None else destination
        humanize = SPEEDS[self.speed][0] > 0
        self.move_path(stream, x1, y1)
        if stream != destination:
            # Start the grab on the source, nudge toward the edge, then cross monitors.
            width = self.frame_size(stream)[0]
            offset = 20 if x1 + 20 < width else -20
            self.pause((0.05, 0.10) if humanize else (0, 0))
            self.button(button, 1)
            try:
                self.pause((0.08, 0.15) if humanize else (0, 0))
                self.move_path(stream, x1 + offset, y1)
                self.goto(destination, x2, y2)
                self.pause((0.05, 0.10) if humanize else (0, 0))
            finally:
                self.button(button, 0)
            return
        self.pause((0.05, 0.10) if humanize else (0, 0))
        self.button(button, 1)
        try:
            self.pause((0.08, 0.16) if humanize else (0, 0))
            self.move_path(stream, x2, y2, slow_factor=1.25)
            self.pause((0.06, 0.12) if humanize else (0, 0))
        finally:
            self.button(button, 0)

    def scroll_steps(self, axis, steps):
        code = {'vertical': 0, 'horizontal': 1}[axis]
        humanize = SPEEDS[self.speed][0] > 0
        sign = 1 if steps >= 0 else -1
        remaining = abs(steps)
        if not humanize or remaining <= 1:
            self.send('PointerAxisDiscrete', 'ui', code, steps)
            return
        while remaining:
            self.send('PointerAxisDiscrete', 'ui', code, sign)
            remaining -= 1
            time.sleep(self.rng.uniform(0.018, 0.045))

    def smooth_scroll(self, axis, pixels):
        duration = 0 if SPEEDS[self.speed][0] == 0 else min(1.2, 0.15 + abs(pixels) / 1600.0)
        steps = max(1, int(duration * 90))
        previous = 0.0
        start = time.perf_counter()
        for i in range(1, steps + 1):
            t = i / steps
            current = pixels * min_jerk(t)
            delta = current - previous
            previous = current
            self.send('PointerAxis', 'dd', *((0.0, delta) if axis == 'vertical' else (delta, 0.0)))
            sleep_until(start + duration * t)
        self.send('PointerAxis', 'dd', 0.0, 0.0, options={'finish': GLib.Variant('b', True)})

    # ------------------------------------------------------------ keyboard
    @staticmethod
    def keysym(name):
        key = Gdk.keyval_from_name(KEY_ALIASES.get(name.lower(), name))
        if key in (0, Gdk.KEY_VoidSymbol):
            key = Gdk.keyval_from_name(name.lower()) or Gdk.keyval_from_name(name.capitalize())
        if key in (0, Gdk.KEY_VoidSymbol):
            if len(name) == 1:
                key = Gdk.unicode_to_keyval(ord(name))
            else:
                raise ValueError(f'Unknown key name: {name}')
        return key

    def chord(self, text):
        return [self.keysym(name) for name in text.split('+') if name]

    def chord_codes(self, text):
        """Resolve KEY[+KEY...] to physical key codes; unknown names raise ValueError."""
        codes = []
        for name in (part for part in text.split('+') if part):
            alias = KEY_ALIASES.get(name.lower(), name).lower()
            if alias not in KEYCODES:
                raise KeyError(name)
            codes.append(KEYCODES[alias])
        return codes

    def press(self, keysyms, hold=0.0):
        pressed = []
        try:
            for key in keysyms:
                self.send('KeyboardKeysym', 'iu', key, 1)
                pressed.append(key)
                if SPEEDS[self.speed][0] and len(keysyms) > 1:
                    time.sleep(0.008)
            if hold:
                time.sleep(hold)
            elif SPEEDS[self.speed][0]:
                time.sleep(0.012)
        finally:
            for key in reversed(pressed):
                self.send('KeyboardKeysym', 'iu', key, 0)

    def tap(self, chord, hold=0.0):
        try:
            self.press_codes(self.chord_codes(chord), hold)
        except KeyError:
            self.press(self.chord(chord), hold)

    def key_state(self, chord, state):
        try:
            codes, action, signature = self.chord_codes(chord), 'KeyboardKeycode', 'iu'
        except KeyError:
            codes, action, signature = self.chord(chord), 'KeyboardKeysym', 'iu'
        for code in (codes if state else reversed(codes)):
            self.send(action, signature, code, state)

    def press_codes(self, codes, hold=0.0):
        pressed = []
        try:
            for code in codes:
                self.send('KeyboardKeycode', 'iu', code, 1)
                pressed.append(code)
                if SPEEDS[self.speed][0] and len(codes) > 1:
                    time.sleep(0.008)
            time.sleep(hold or (0.012 if SPEEDS[self.speed][0] else 0.0))
        finally:
            for code in reversed(pressed):
                self.send('KeyboardKeycode', 'iu', code, 0)

    def clipboard_set(self, value):
        subprocess.run(['wl-copy', '--type', 'text/plain;charset=utf-8'],
                       input=value.encode('utf-8'), check=True, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def clipboard_get(self):
        if not shutil.which('wl-paste'):
            return None
        done = subprocess.run(['wl-paste', '--no-newline'], capture_output=True, timeout=3)
        return done.stdout if done.returncode == 0 else None

    def paste(self, value, restore=False):
        saved = self.clipboard_get() if restore else None
        self.clipboard_set(value)
        time.sleep(0.04)
        self.press_codes([KEYCODES['control_l'], KEYCODES['v']])
        if saved is not None:
            time.sleep(0.15)  # let the target app read the clipboard first
            subprocess.run(['wl-copy'], input=saved, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def type_keys(self, value):
        """Type one character at a time with human delays, whatever layout is active."""
        delays = SPEEDS[self.speed][1]
        special = {'\n': KEYCODES['return'], '\t': KEYCODES['tab']}
        saved = self.clipboard_get()
        try:
            for char in value:
                if char in special:
                    self.press_codes([special[char]])
                else:
                    self.clipboard_set(char)
                    time.sleep(0.012)
                    self.press_codes([KEYCODES['control_l'], KEYCODES['v']])
                self.pause(delays)
        finally:
            if saved is not None:
                time.sleep(0.15)
                subprocess.run(['wl-copy'], input=saved, timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ------------------------------------------------------------- dispatch
    def execute(self, command, args):
        match command, args:
            case 'streams', []:
                return self.streams
            case 'shot', [stream, path]:
                return self.shot(int(stream), path)
            case 'where', []:
                return {str(stream): [round(x, 1), round(y, 1)] for stream, (x, y) in self.pos.items()}
            case 'speed', [name]:
                if name not in SPEEDS:
                    raise ValueError('speed ' + '|'.join(SPEEDS))
                self.speed = name
            case 'move', [stream, x, y]:
                self.move_path(int(stream), float(x), float(y))
            case 'jump', [stream, x, y]:
                self.goto(int(stream), float(x), float(y))
            case 'click', [stream, x, y, *options] if len(options) <= 2:
                button = options[0] if options else 'left'
                count = int(options[1]) if len(options) == 2 else 1
                self.click(int(stream), float(x), float(y), button, count)
            case 'down', [*options] if len(options) <= 1:
                self.button(options[0] if options else 'left', 1)
            case 'up', [*options] if len(options) <= 1:
                self.button(options[0] if options else 'left', 0)
            case 'drag', [stream, x1, y1, x2, y2, *options] if len(options) <= 1:
                self.drag(int(stream), float(x1), float(y1), float(x2), float(y2),
                          button=options[0] if options else 'left')
            case 'drag-between', [stream, x1, y1, destination, x2, y2]:
                self.drag(int(stream), float(x1), float(y1), float(x2), float(y2), int(destination))
            case 'scroll', [axis, steps] if axis in ('vertical', 'horizontal'):
                self.scroll_steps(axis, int(steps))
            case 'smoothscroll', [axis, pixels] if axis in ('vertical', 'horizontal'):
                self.smooth_scroll(axis, float(pixels))
            case 'key', [chord, *options] if len(options) <= 1:
                for index in range(int(options[0]) if options else 1):
                    if index:
                        self.pause(SPEEDS[self.speed][1])
                    self.tap(chord)
            case 'keydown', [chord]:
                self.key_state(chord, 1)
            case 'keyup', [chord]:
                self.key_state(chord, 0)
            case 'hold', [chord, seconds]:
                self.tap(chord, hold=float(seconds))
            case 'keycode', [codes]:
                self.press_codes([int(code) for code in codes.split('+')])
            case 'type', [value]:
                self.paste(value, restore=True)
            case 'typekeys', [value]:
                self.type_keys(value)
            case 'paste', [value]:
                self.paste(value)
            case 'wait', [seconds]:
                time.sleep(min(float(seconds), 60.0))
            case _:
                raise ValueError(HELP.get(command, 'Unknown command. Commands: ' + ', '.join(HELP)))

    def close(self):
        for pipeline, fd in self.pipelines.values():
            pipeline.set_state(Gst.State.NULL)
            os.close(fd)


def save_token(token):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=STATE)
    try:
        with os.fdopen(fd, 'w') as file:
            file.write(token)
        os.replace(name, TOKEN)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=' | '.join(HELP.values()))
    parser.add_argument('--remember', action='store_true', help='Ask GNOME to remember consent across sessions')
    args = parser.parse_args()
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'A desktop controller is already running. Reuse or close it first.\n')
        run_session(args.remember)


def run_session(remember):
    Gst.init(None)
    result = checked_request('CreateSession', '(a{sv})', (), {
        'session_handle_token': GLib.Variant('s', 'control' + secrets.token_hex(8)),
    })
    session = result['session_handle']
    controller = None
    indicator = None
    try:
        devices = {'types': GLib.Variant('u', 3)}
        if remember:
            devices['persist_mode'] = GLib.Variant('u', 2)
            try:
                devices['restore_token'] = GLib.Variant('s', TOKEN.read_text())
            except FileNotFoundError:
                pass
        checked_request('SelectDevices', '(oa{sv})', (session,), devices)
        checked_request('SelectSources', '(oa{sv})', (session,), {
            'types': GLib.Variant('u', 1),
            'multiple': GLib.Variant('b', True),
            'cursor_mode': GLib.Variant('u', 2),
        }, SCREENCAST)
        result = checked_request('Start', '(osa{sv})', (session, ''), {})
        if result.get('devices', 0) & 3 != 3 or not result.get('streams'):
            raise RuntimeError('Screen sharing and both keyboard and pointer access are required')
        restore_token = result.get('restore_token')
        if remember and restore_token:
            save_token(restore_token)
        controller = Desktop(session, result['streams'])
        indicator_script = Path(__file__).resolve().with_name('indicator.py')
        if indicator_script.is_file():
            indicator = subprocess.Popen(
                [sys.executable, '-I', str(indicator_script)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        print(json.dumps({'ready': controller.streams, 'remembered': bool(restore_token)}), flush=True)
        for line in sys.stdin:
            try:
                words = shlex.split(line)
                if not words:
                    continue
                if words == ['quit']:
                    break
                started = time.monotonic()
                result = controller.execute(words[0], words[1:])
                elapsed_ms = round((time.monotonic() - started) * 1000)
                print(json.dumps({'ok': result, 'elapsed_ms': elapsed_ms}), flush=True)
            except (ValueError, KeyError, OSError, GLib.Error, RuntimeError, subprocess.SubprocessError) as error:
                message = f'Unknown stream or key: {error}' if isinstance(error, KeyError) else str(error)
                print(json.dumps({'error': message}), flush=True)
    finally:
        if indicator and indicator.poll() is None:
            indicator.terminate()
            try:
                indicator.wait(timeout=2)
            except subprocess.TimeoutExpired:
                indicator.kill()
        if controller:
            controller.close()
        try:
            portal_call(session, 'org.freedesktop.portal.Session', 'Close', '()')
        except GLib.Error as error:
            print(f'Portal session close: {error.message}', file=sys.stderr)


if __name__ == '__main__':
    main()
