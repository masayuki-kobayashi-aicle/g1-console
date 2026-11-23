#!/usr/bin/env bash
# Start, stop and check camera_stream.py. **Run this on the robot itself (Jetson).**
#   ./camera_ctl.sh start | stop | status
#
# WARNING: no daemonizing or automatic restart: do not create restarts via systemd / cron / rc.local / a while loop.
#    It starts only when you run start, and stops only with stop. If it dies, leave it dead.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
# Where pid and log go (default: next to this script. The console's --local passes ~/.g1console/run)
STATE="${G1_CTL_STATE_DIR:-$DIR}"
mkdir -p "$STATE" 2>/dev/null
PIDFILE="$STATE/camera_stream.pid"
LOG="$STATE/camera_stream.log"
PORT="${CAMERA_PORT:-8081}"
BIND="${CAMERA_BIND:-0.0.0.0}"  # use 127.0.0.1 when the console runs on the same machine
BYID=/dev/v4l/by-id
STOP_WAIT_S=5
VIDEO_NIC="${CAMERA_NIC:-eth0}"  # NIC used by VideoClient
PYTHON="${CAMERA_PYTHON:-python3}"  # system Python 3.8 (has cv2 / pyrealsense2 / unitree_sdk2py)
SDK_DIR="${UNITREE_SDK_DIR:-$HOME/unitree_sdk2_python}"

# Check that the PID in the pidfile is "really camera_stream.py" (do not kill something else after PID reuse)
running_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE")"
  [ -n "$pid" ] && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q camera_stream.py || return 1
  echo "$pid"
}

find_dev() { ls "$BYID"/$1 2>/dev/null | head -n 1; }

cmd_start() {
  local pid
  if pid="$(running_pid)"; then echo "[camera] already running (pid=$pid)"; return 0; fi
  rm -f "$PIDFILE"
  local args=() std
  std="$(find_dev '*Sunplus*webcam*index0')"
  [ -n "$std" ] && args+=(--camera "std=$std") || echo "[camera] standard camera not found (not streaming it)"
  # videohub_pc4 holds /dev/video4 exclusively, so the D435i RGB is taken through the official VideoClient path (videohub is not stopped)
  args+=(--camera "d435i=videoclient:$VIDEO_NIC")
  # Depth is on USB interface 1.0 (separate from videohub). Read it with pyrealsense2
  args+=(--camera "depth=depth:realsense")
  [ ${#args[@]} -gt 0 ] || { echo "[camera] no camera available to stream"; return 1; }
  # setsid: keep it alive after ssh disconnects (but it is not restarted)
  PYTHONPATH="$SDK_DIR" setsid nohup "$PYTHON" -u "$DIR/camera_stream.py" --port "$PORT" --bind "$BIND" "${args[@]}" >"$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"
  sleep 2
  if pid="$(running_pid)"; then echo "[camera] started (pid=$pid, port=$PORT, bind=$BIND)"; else
    echo "[camera] failed to start. Log:"; tail -n 10 "$LOG"; rm -f "$PIDFILE"; return 1
  fi
}

cmd_stop() {
  local pid
  if ! pid="$(running_pid)"; then rm -f "$PIDFILE"; echo "[camera] not running"; return 0; fi
  kill "$pid"
  for _ in $(seq "$STOP_WAIT_S"); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -0 "$pid" 2>/dev/null && { kill -9 "$pid"; sleep 1; }
  if kill -0 "$pid" 2>/dev/null; then echo "[camera] could not stop (pid=$pid)"; return 1; fi
  rm -f "$PIDFILE"; echo "[camera] stopped"
}

cmd_status() {
  local pid
  if pid="$(running_pid)"; then echo "[camera] running (pid=$pid)"; else echo "[camera] stopped"; fi
}

# List the processes holding video devices as "device<TAB>PID<TAB>user<TAB>command".
# Processes of root are not visible to fuser without sudo, so also pick up those whose ps arguments contain /dev/videoN (videohub_pc4 etc.)
cmd_holders() {
  local dev
  for dev in /dev/video*; do
    [ -e "$dev" ] || continue
    ps -eo pid=,user=,args= | awk -v d="$dev" '{for (i = 3; i <= NF; i++) if ($i == d) { print; break }}' | \
      while read -r pid user args; do printf '%s\t%s\t%s\t%s\n' "$dev" "$pid" "$user" "${args:0:160}"; done
    fuser "$dev" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' | while read -r pid; do
      printf '%s\t%s\t%s\t%s\n' "$dev" "$pid" "$(ps -o user= -p "$pid")" "$(ps -o args= -p "$pid" | cut -c1-160)"
    done
  done | sort -u
}

case "${1:-}" in
  holders) cmd_holders ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *) echo "usage: $0 start|stop|status|holders"; exit 2 ;;
esac
