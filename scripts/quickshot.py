#!/usr/bin/python3 -I
"""Fast screenshot via xdg-desktop-portal (no PipeWire session, no input control).

Usage: quickshot.py /absolute/path/out.png
"""
import os
import shutil
import sys
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

if len(sys.argv) != 2 or not os.path.isabs(sys.argv[1]):
    sys.exit("usage: quickshot.py /absolute/out.png")
out = sys.argv[1]

bus = Gio.bus_get_sync(Gio.BusType.SESSION)
token = "qs%d" % os.getpid()
sender = bus.get_unique_name().lstrip(":").replace(".", "_")
req_path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)
loop = GLib.MainLoop()
result = {}


def on_response(_c, _s, _p, _i, _sig, params):
    result["code"], result["data"] = params.unpack()
    loop.quit()


bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
                     "Response", req_path, None, Gio.DBusSignalFlags.NONE, on_response)
bus.call_sync(
    "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
    "org.freedesktop.portal.Screenshot", "Screenshot",
    GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token),
                                    "interactive": GLib.Variant("b", False)})),
    None, Gio.DBusCallFlags.NONE, -1, None)
GLib.timeout_add_seconds(15, loop.quit)
loop.run()

if result.get("code") != 0:
    sys.exit("portal denied or timed out: %r" % (result,))
src = unquote(urlparse(result["data"]["uri"]).path)
shutil.move(src, out)
print(out)
