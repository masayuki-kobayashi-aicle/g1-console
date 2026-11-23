#!/usr/bin/env bash
# Start, stop and check lidar_stream.py. **Run this on the robot itself (Jetson).**
#   [LIDAR_PORT=8082] ./lidar_ctl.sh start | stop | status
#
# WARNING: no daemonizing or automatic restart: do not create restarts via systemd / cron / rc.local / a while loop.
#    It starts only when you run start, and stops only with stop. If it dies, leave it dead.
# lidar_stream.py only subscribes to DDS (it does not touch the motors or the lidar unit's settings).
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
# Where pid and log go (default: next to this script. The console's --local passes ~/.g1console/run)
STATE="${G1_CTL_STATE_DIR:-$DIR}"
mkdir -p "$STATE" 2>/dev/null
PIDFILE="$STATE/lidar_stream.pid"
LOG="$STATE/lidar_stream.log"
STOP_WAIT_S=5
START_WAIT_S=3
PORT="${LIDAR_PORT:-8082}"
BIND="${LIDAR_BIND:-0.0.0.0}"  # use 127.0.0.1 when the console runs on the same machine
NIC="${LIDAR_NIC:-eth0}"
PYTHON="${LIDAR_PYTHON:-python3}"  # system Python 3.8 (has cyclonedds / numpy)

# Check that the PID in the pidfile is "really lidar_stream.py" (do not kill something else after PID reuse)
running_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE")"
  [ -n "$pid" ] && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q lidar_stream.py || return 1
  echo "$pid"
}

cmd_start() {
  local pid
  if pid="$(running_pid)"; then echo "[lidar] already running (pid=$pid)"; return 0; fi
  rm -f "$PIDFILE"
  # setsid: keep it alive after ssh disconnects (but it is not restarted)
  setsid nohup "$PYTHON" -u "$DIR/lidar_stream.py" --port "$PORT" --bind "$BIND" --nic "$NIC" >"$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"
  sleep "$START_WAIT_S"
  if pid="$(running_pid)"; then echo "[lidar] started (pid=$pid, port=$PORT, bind=$BIND)"; else
    echo "[lidar] failed to start. Log:"; tail -n 10 "$LOG"; rm -f "$PIDFILE"; return 1
  fi
}

cmd_stop() {
  local pid
  if ! pid="$(running_pid)"; then rm -f "$PIDFILE"; echo "[lidar] not running"; return 0; fi
  kill "$pid"
  for _ in $(seq "$STOP_WAIT_S"); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  kill -0 "$pid" 2>/dev/null && { kill -9 "$pid"; sleep 1; }
  if kill -0 "$pid" 2>/dev/null; then echo "[lidar] could not stop (pid=$pid)"; return 1; fi
  rm -f "$PIDFILE"; echo "[lidar] stopped"
}

cmd_status() {
  local pid
  if pid="$(running_pid)"; then echo "[lidar] running (pid=$pid)"; else echo "[lidar] stopped"; fi
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
