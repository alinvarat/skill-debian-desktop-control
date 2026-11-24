# Manual controller and command protocol

Read when daemon commands beyond the entrypoint are needed, or the daemon is unavailable.

## Slow path: manual controller
Run the controller on the local GNOME Wayland session. It uses Python GI, GDK 4 and the GStreamer PipeWire, video conversion, PNG and appsink plugins. Unicode paste uses `wl-copy`. For websites and apps with a dedicated connector, prefer that connector when it covers the task.

```bash
timeout 600s /usr/bin/python3 -B "$HOME/.claude/skills/debian-desktop-control/scripts/control.py" --remember
```

Start in a terminal session whose stdin stays open, wait for `ready`, and tell the user if GNOME needs consent. The user requested remembered consent on this machine. `--remember` saves the rotating GNOME restore token in `~/.local/state/debian-desktop-control/restore-token` (or under `XDG_STATE_HOME`). Run only one controller at a time. GNOME may prompt if it rejects the token. To forget the saved token, remove that file and revoke the app permission through GNOME if available. Use a fresh capture to identify the intended window and target before clicking or typing. Use a private temporary directory for captures and remove them after use. Never enter passwords or OTPs or bypass CAPTCHAs.

Send one command per line to the same process. Stream IDs come from `streams` or `ready`. Coordinates are PNG pixels of the last capture of that stream (any point on the whole frame works; the script handles GNOME's absolute-motion quirk by finishing far moves with relative motion). Capture both streams before using `drag-between`. To move a focused GNOME window across monitors, use the configured window-manager shortcut. On this Debian setup it is `key Super_L+Shift_L+Right` or `key Super_L+Shift_L+Left`. Verify the window on the destination stream.

Mouse moves, clicks and drags follow a curved, eased, human-like path (about 120 steps/s, duration grows with distance, small jitter, natural pauses before/after clicks). Use `speed fast` for quick runs or `speed slow` for deliberate movement. The API also exposes instant/jump commands, but this user’s smooth-cursor rule excludes them. `shot` waits briefly so the frame reflects the last input.

```text
streams
where                                   tracked pointer position (PNG px)
speed human|fast|slow
shot STREAM /absolute/private/path/unique.png
move STREAM X Y                         smooth curve
click STREAM X Y [left|right|middle|back|forward] [COUNT 1-3]
down [button]    up [button]            press / release without moving
drag STREAM X1 Y1 X2 Y2 [button]        smooth human drag
drag-between SOURCE X1 Y1 DESTINATION X2 Y2
scroll vertical|horizontal STEPS        notches, positive = down/right
smoothscroll vertical|horizontal PIXELS eased continuous scroll
key ctrl+shift+t [COUNT]                physical keys, works on any layout
keydown KEY      keyup KEY              hold / release (e.g. shift)
hold KEY[+KEY] SECONDS
keycode EVDEV[+EVDEV]                   raw codes, e.g. 30 = A
type "any text, ไทย ok"                 via clipboard (restores text clipboard)
typekeys "text"                         char by char with human delays, any layout
paste "text"                            like type but leaves text on the clipboard
wait SECONDS
quit
```

Key names: letters, digits, punctuation, `ctrl alt shift super enter esc tab space backspace delete home end pgup pgdn up down left right F1-F12`, plus GDK keysym names as a fallback. `key` uses physical key positions, so shortcuts such as `ctrl+a` work even when the Thai layout is active. `type` is layout independent and handles Thai and English mixed; use it by default. `typekeys` types one character at a time with human-like delays (slower, any layout and language). After typing or pasting, verify the text before a dependent action such as Enter or Save. The app can process the paste asynchronously.

## Portal bridge (`hermes-portal`)
A second controller runs as the user service `hermes-portal` (Python bridge `portal_bridge.py`, client `pc.py`, from the user's own agent profile; optional). Check it with `systemctl --user status hermes-portal`; it should report READY with the screen size.

Commands sent through the `pc` client, one JSON object each:
- `{"cmd":"move","x":..,"y":..}` absolute move
- `{"cmd":"click","x":..,"y":..,"button":"left|right"}` absolute move + click; may not register on some web pages, so use the relative workaround in SKILL.md step 8
- `{"cmd":"press","button":"left|right"}` click at the current pointer position without moving (the reliable click for the relative workaround)
- `{"cmd":"rel","dx":..,"dy":..}` relative move; a large negative dx/dy clamps the pointer to the top-left corner, giving a known origin
- `{"cmd":"drag","x1","y1","x2","y2","button"}` drag
- `{"cmd":"key","keysym":N}` single key by X keysym; Escape = 65307, Enter = 65293. Type text by sending one `key` per character with a short delay (about 0.03 s)
- `shot` with a `path` writes a PNG of the full screen

Relative-origin procedure: `rel -3000 -3000` (corner), `rel dx dy` to the target in full-resolution pixels (screenshot coordinates, not the 960-wide vision thumbnail), pause about 0.5 s, `press`, then wait 5–7 s for the page and capture. Re-check with a fresh capture before the next step, because a moved pointer can hover a different element.

After editing `portal_bridge.py`, run `python3 -m py_compile` on it and restart with `systemctl --user restart hermes-portal`, then wait about 12 s for READY before sending commands. The saved GNOME token normally avoids a new consent prompt on restart.
