#!/usr/bin/env python3
"""Floating red-dot indicator at top-center while desktop control is active."""
import ctypes
import math
import os
import signal
import sys

os.environ['GDK_BACKEND'] = 'x11'

import cairo
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk

SIZE = 20
TOP_MARGIN = 6


def die_with_parent():
    try:
        libc = ctypes.CDLL('libc.so.6')
        libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


class RedDotIndicator(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_default_size(SIZE, SIZE)
        self.set_size_request(SIZE, SIZE)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

        self.connect('draw', self.on_draw)
        self.connect('realize', self.on_realize)
        self.connect('destroy', Gtk.main_quit)

        self._position_top_center()

    def _position_top_center(self):
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geom = monitor.get_geometry()
        x = geom.x + (geom.width - SIZE) // 2
        y = geom.y + TOP_MARGIN
        self.move(x, y)

    def on_realize(self, _widget):
        # Click-through: empty input region
        self.input_shape_combine_region(cairo.Region())

    def on_draw(self, _widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.0)
        cr.paint()

        cr.set_operator(cairo.OPERATOR_OVER)
        cx = cy = SIZE / 2.0
        r = SIZE / 2.0 - 2.0

        # Subtle dark halo for contrast on light backgrounds
        cr.arc(cx, cy, r + 1.2, 0, 2 * math.pi)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.45)
        cr.fill()

        # Bright red dot
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.set_source_rgba(1.0, 0.16, 0.16, 0.95)
        cr.fill()

        # Thin bright inner ring
        cr.arc(cx, cy, r - 0.5, 0, 2 * math.pi)
        cr.set_source_rgba(1.0, 0.55, 0.55, 0.6)
        cr.set_line_width(1.0)
        cr.stroke()
        return False


def main():
    die_with_parent()
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(Gtk.main_quit))
    signal.signal(signal.SIGINT, lambda *_: GLib.idle_add(Gtk.main_quit))
    win = RedDotIndicator()
    win.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
