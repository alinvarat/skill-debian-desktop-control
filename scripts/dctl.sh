#!/bin/bash
# Persistent desktop-control daemon.
#   dctl.sh start                    start daemon if not running (waits for ready)
#   dctl.sh send "CMD" ["CMD" ...]   run commands in order, print one reply each,
#                                    stop at the first error (exit 1). @s = stream id
#   dctl.sh stop                     quit the daemon
R="${XDG_RUNTIME_DIR:-/tmp}/dctl"; mkdir -p "$R"
FIFO="$R/in.fifo"; LOG="$R/out.log"; PIDF="$R/pid"; SIDF="$R/sid"
CTL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/control.py"
alive() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; }
save_sid() { sed -n 's/^{"ready": {"\([0-9]*\)".*/\1/p' "$LOG" | head -n1 > "$SIDF"; }
case "$1" in
start)
  alive && { echo running; exit 0; }
  rm -f "$FIFO" "$LOG" "$SIDF"; mkfifo "$FIFO"; : > "$LOG"
  # holder keeps the fifo's write end open so the daemon never sees EOF
  setsid bash -c 'exec 3<>"$0"; exec /usr/bin/python3 -B "$1" --remember <&3 >>"$2" 2>&1' "$FIFO" "$CTL" "$LOG" &
  echo $! > "$PIDF"
  for _ in $(seq 1 600); do grep -q '"ready"' "$LOG" && { save_sid; echo ready; exit 0; }; sleep 0.05; done
  echo "not ready (GNOME may be waiting for consent)"; exit 1 ;;
send)
  shift; [ $# -gt 0 ] || { echo "usage: $0 send CMD [CMD ...]"; exit 2; }
  alive || "$0" start >/dev/null || exit 1
  [ -s "$SIDF" ] || save_sid
  read -r sid < "$SIDF"
  n=$(wc -l < "$LOG")
  exec 4< <(exec tail --pid=$$ -n +"$((n+1))" -f "$LOG"); tail_pid=$!
  trap 'kill "$tail_pid" 2>/dev/null' EXIT
  for cmd in "$@"; do
    # never rewrite @s inside text the user wants typed (e.g. an email address)
    case "$cmd" in type\ *|typekeys\ *|paste\ *) ;; *) cmd="${cmd//@s/$sid}" ;; esac
    printf '%s\n' "$cmd" > "$FIFO"
    while :; do
      IFS= read -r -t 70 -u4 reply || { echo "no reply"; exit 1; }
      case "$reply" in
        '{"ok"'*) printf '%s\n' "$reply"; break ;;
        '{"error"'*) printf '%s\n' "$reply"; exit 1 ;;
        *) printf '%s\n' "$reply" >&2 ;;   # GStreamer or Python noise, not a reply
      esac
    done
  done ;;
stop)
  alive && { printf 'quit\n' > "$FIFO"; sleep 0.3; kill "$(cat "$PIDF")" 2>/dev/null; }
  rm -f "$PIDF" "$FIFO" "$SIDF"; echo stopped ;;
*) echo "usage: $0 start|send CMD [CMD ...]|stop"; exit 2 ;;
esac
