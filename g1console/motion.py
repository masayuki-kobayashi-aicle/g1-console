"""Motion control (a substitute for the physical remote controller). Standard library only. Must work on Python 3.8.

Browser (10 Hz) -> hub (MotionController, sends at 20 Hz) -> motion-only helper -> LocoClient.SetVelocity(duration=0.2).

Safety design:
- The liveness check is the time elapsed since the last message was received. Do not rely on TCP disconnect detection (measured 2026-09-09: the robot kept walking for about 4 seconds after a disconnect).
- The decision to stop comes before sending. Even if sending is stuck, an old target is not kept being sent.
- The send period (0.05 s) is shorter than duration (0.2 s). Even if the hub dies, the robot stops by itself.
- There is a single operator. After a disconnect, emergency stop, or release, it does not resume automatically (claim is needed again).
- A software stop does not satisfy safety standards. The last line of defense is the physical remote controller.
The limits and time values are initial values and are unverified on the real robot.
"""
import math
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

WALK_FSM = frozenset((500, 501))  # walking FSMs. Motion commands are issued only here
LIMITS = {"vx": (-0.2, 0.3), "vy": (-0.2, 0.2), "wz": (-0.4, 0.4)}  # m/s, m/s, rad/s. Conservative initial values (unverified on the real robot)
DEADBAND = 0.01
SEND_PERIOD_S = 0.05  # 20 Hz
DURATION_S = 0.2  # validity time of SetVelocity. Longer than SEND_PERIOD_S; if the link is lost the robot stops by itself
LIVENESS_S = 0.5  # if no ctl arrives for this long, stop and release the operator lock
FSM_MAX_AGE_S = 5.0  # do not move if the FSM check is older than this
HELPER_TIMEOUT_S = 1.0  # wait for the helper's reply. Making it longer delays stopping
HELPER_READY_S = 30.0  # wait for DDS initialization
SEND_FAIL_LIMIT = 3  # release the operator lock after this many consecutive send failures
ZERO = (0.0, 0.0, 0.0)

HERE = Path(__file__).resolve().parent.parent
HELPER_SRC = HERE / "jetson" / "motion_helper.py"


class MotionError(Exception):
    """Error with an HTTP status. message is plain text that can be shown in the UI as is."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def parse_velocity(body: dict) -> tuple:
    """Take (vx, vy, wz) from the body and clamp to the limits. ValueError if not a number or not finite."""
    out = []
    for key in ("vx", "vy", "wz"):
        v = body.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("%s must be a finite number" % key)
        lo, hi = LIMITS[key]
        v = min(max(float(v), lo), hi)
        out.append(0.0 if abs(v) < DEADBAND else v)
    return tuple(out)


# ---- sender side -------------------------------------------------------------------------------------------------
class MockSender:
    """For use without a robot. Only records what was called."""

    backend = "mock"

    def __init__(self):
        self.calls = []
        self.fail = False

    def prepare(self):
        pass

    def _rec(self, *call):
        if self.fail:
            raise MotionError(502, "mock send failure")
        self.calls.append(call)

    def move(self, vx, vy, wz, duration):
        self._rec("move", vx, vy, wz, duration)

    def stop(self):
        self._rec("stop")

    def task(self, task_id):
        self._rec("task", task_id)

    def close(self):
        pass


class UnavailableSender:
    """Sender side when not --local. Motion is allowed only when the hub runs on the Jetson (motion over ssh has uncertain latency and disconnect detection)."""

    backend = "unavailable"

    def prepare(self):
        raise MotionError(503, "Motion control is available only when the console is run on the Jetson with --local")

    def move(self, *_):
        self.prepare()

    stop = task = move

    def close(self):
        pass


class HelperSender:
    """Holds the motion-only helper (jetson/motion_helper.py) as a child process. Serialized; if a reply is slow it is dropped."""

    backend = "local"

    def __init__(self, sdk_dir=None):
        self._sdk_dir = Path(sdk_dir or os.environ.get("UNITREE_SDK_DIR") or "~/unitree_sdk2_python").expanduser()
        self._lock = threading.Lock()
        self._proc = None
        self._lines = queue.Queue()

    def _command(self, src: str):
        return [sys.executable, "-u", "-c", src], str(self._sdk_dir)

    def _source(self) -> str:
        from g1console.modes import ACTIONS
        src = HELPER_SRC.read_text(encoding="utf-8")
        src = src.replace("__LIMITS__", repr({k: list(v) for k, v in LIMITS.items()}))
        return src.replace("__TASKS__", repr(sorted(a["task_id"] for a in ACTIONS)))

    @staticmethod
    def _pump(proc, out):
        for line in proc.stdout:
            out.put(line)
        out.put(None)

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _kill(self):
        if self._proc is not None:
            self._proc.kill()
            self._proc = None

    def _start(self):
        import json
        cmd, cwd = self._command(self._source())
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, cwd=cwd)
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc, self._lines), daemon=True).start()
        try:
            ready = self._lines.get(timeout=HELPER_READY_S)
            ok = ready is not None and json.loads(ready).get("ready")
        except (queue.Empty, ValueError):
            ok = False
        if not ok:
            self._kill()
            raise MotionError(502, "The motion helper does not start (check the SDK, DDS and eth0)")

    def prepare(self):
        with self._lock:
            if not self._alive():
                self._start()

    def _call(self, req: dict) -> dict:
        import json
        with self._lock:
            if not self._alive():
                raise MotionError(502, "The motion helper is not running")
            try:
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
                line = self._lines.get(timeout=HELPER_TIMEOUT_S)
                if line is None:
                    raise RuntimeError("helper exited")
                reply = json.loads(line)
            except (OSError, RuntimeError, queue.Empty, ValueError) as exc:
                self._kill()  # drop it so a late old reply is not mixed up, and restart next time
                raise MotionError(502, "The motion helper is not responding (%s)" % type(exc).__name__)
        if not reply.get("ok") or reply.get("code") != 0:
            raise MotionError(502, "The G1 did not accept the motion command (code=%s)" % reply.get("code"))
        return reply

    def move(self, vx, vy, wz, duration):
        self._call({"op": "move", "vx": vx, "vy": vy, "wz": wz, "duration": duration})

    def stop(self):
        if self._alive():  # do not start a helper just to stop one that is not running (the command expires by itself after duration)
            self._call({"op": "stop"})

    def task(self, task_id):
        self._call({"op": "task", "id": task_id})

    def close(self):
        with self._lock:
            if self._alive():
                try:
                    self._proc.stdin.close()  # the helper sends a stop command on EOF and exits
                    self._proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self._kill()


# ---- control -----------------------------------------------------------------------------------------------------
class MotionController:
    """Decisions on the operator lock, liveness check, FSM check and sending. The clock and the sender can be swapped (tests use a fake clock)."""

    def __init__(self, sender, fsm_source, clock=time.monotonic):
        self._sender = sender
        self._fsm_source = fsm_source  # () -> (fsm_id or None, seconds since the check or None)
        self._clock = clock
        self._lock = threading.Lock()  # state
        self._send_lock = threading.Lock()  # sending (even if stuck, state updates are not blocked)
        self._operator = None
        self._target = ZERO
        self._seq = -1
        self._last_rx = 0.0
        self._moving = False
        self._gen = 0  # advanced on every stop, to discard sends based on an old decision
        self._last_event = None
        self._last_error = None
        self._fail_count = 0

    # -- state --
    def _gate(self):
        """Whether it may move. (allowed, reason). Call it while holding the lock."""
        fsm_id, age = self._fsm_source()
        if fsm_id not in WALK_FSM:
            return False, "Not a walking mode (FSM 500/501) (FSM=%s)" % fsm_id
        if age is None or age > FSM_MAX_AGE_S:
            return False, "Not moving because the G1 state check is stale"
        return True, None

    def status(self) -> dict:
        with self._lock:
            ok, why = self._gate()
            now = self._clock()
            return {"state": "active" if self._operator else "idle", "operator": self._operator is not None,
                    "moving": self._moving, "target": dict(zip(("vx", "vy", "wz"), self._target)),
                    "blocked": None if ok else why,
                    "last_rx_age_s": round(now - self._last_rx, 3) if self._operator else None,
                    "last_event": self._last_event, "sender": {"backend": self._sender.backend, "error": self._last_error},
                    "limits": {k: list(v) for k, v in LIMITS.items()},
                    "timing": {"send_period_s": SEND_PERIOD_S, "duration_s": DURATION_S, "liveness_s": LIVENESS_S}}

    def _event(self, kind: str, detail: str):
        self._last_event = {"kind": kind, "detail": detail, "at": time.time()}

    # -- stop --
    def _halt(self, kind: str, detail: str, always_send: bool = False):
        """Release the operator lock and set zero velocity. Update the state first, then send the stop."""
        with self._lock:
            was_moving = self._moving
            self._operator, self._target, self._moving = None, ZERO, False
            self._gen += 1
            self._event(kind, detail)
        if was_moving or always_send:
            with self._send_lock:
                try:
                    self._sender.stop()
                    self._last_error = None
                except MotionError as exc:
                    self._last_error = exc.message

    def estop(self) -> dict:
        self._halt("estop", "Emergency stop", always_send=True)
        return self.status()

    def release(self, session: str) -> dict:
        self._require(session)
        self._halt("release", "Operator lock released")
        return self.status()

    def shutdown(self):
        self._halt("shutdown", "Hub exit", always_send=True)

    # -- operations --
    def _require(self, session) -> None:
        with self._lock:
            ok = (self._operator is not None and isinstance(session, str)
                  and secrets.compare_digest(session.encode("utf-8"), self._operator.encode("utf-8")))
        if not ok:
            raise MotionError(409, "You do not hold the operator lock (it was released by a disconnect, emergency stop, or another operator). Claim it again")

    def claim(self, takeover: bool = False) -> dict:
        with self._lock:
            held = self._operator is not None
        if held and not takeover:
            raise MotionError(409, "Someone else is operating")
        self._sender.prepare()  # the first time takes a few seconds for DDS initialization. A failure goes to the caller
        if held:
            self._halt("takeover", "Operator lock taken over", always_send=True)
        with self._lock:
            if self._operator is not None:  # a concurrent claim got it first
                raise MotionError(409, "Someone else is operating")
            self._operator = secrets.token_urlsafe(8)
            self._target, self._seq, self._last_rx, self._fail_count = ZERO, -1, self._clock(), 0
            self._event("claim", "Operation started")
            session = self._operator
        return {**self.status(), "session": session}

    def ctl(self, session, seq, vx, vy, wz) -> dict:
        """10 Hz keep-alive message. Out-of-order ones (seq does not increase) are discarded."""
        self._require(session)
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise ValueError("seq must be an integer")
        target = parse_velocity({"vx": vx, "vy": vy, "wz": wz})  # clamping to the limits always goes through here
        with self._lock:
            if seq > self._seq:  # an old command that arrived late (seq does not increase) is not applied and not counted as evidence of liveness
                self._seq, self._last_rx, self._target = seq, self._clock(), target
        return self.status()

    def action(self, session, name: str) -> dict:
        from g1console.modes import ACTIONS
        task = next((a["task_id"] for a in ACTIONS if a["id"] == name), None)
        if task is None:
            raise ValueError("Action not allowed")
        self._require(session)
        with self._lock:
            ok, why = self._gate()
            gen = self._gen
        if not ok:
            raise MotionError(409, why)
        with self._lock:
            self._target = ZERO  # do not let it walk during an action
        with self._send_lock:
            with self._lock:
                if gen != self._gen:
                    raise MotionError(409, "The operator lock was released")
            self._sender.task(task)
        return self.status()

    # -- 20 Hz periodic processing --
    def tick(self):
        """In the order liveness check -> decision -> send. The decision is inside the lock, the send outside it (discarded if the generation changed)."""
        with self._lock:
            lost = self._operator is not None and self._clock() - self._last_rx > LIVENESS_S
        if lost:
            return self._halt("lost", "ctl lost for %.1f s" % LIVENESS_S)
        with self._lock:
            if self._operator is None:
                return
            ok, _ = self._gate()
            target = self._target if ok else ZERO
            if any(target):
                action, self._moving = ("move", target), True
            elif self._moving:
                action, self._moving = ("stop", None), False
            else:
                return
            gen = self._gen
        self._emit(gen, action)

    def _emit(self, gen: int, action: tuple) -> bool:
        with self._send_lock:
            with self._lock:
                if gen != self._gen:
                    return False  # a stop came in after the decision. Do not send the old command
            try:
                if action[0] == "move":
                    self._sender.move(*action[1], DURATION_S)
                else:
                    self._sender.stop()
                self._last_error, self._fail_count = None, 0
                return True
            except MotionError as exc:
                self._last_error = exc.message
                self._fail_count += 1
                failed = self._fail_count >= SEND_FAIL_LIMIT
        if failed:
            self._halt("sender_error", self._last_error)
        return False


def start_ticker(controller, period: float = SEND_PERIOD_S) -> threading.Thread:
    def loop():
        while True:
            started = time.monotonic()
            try:
                controller.tick()
            except Exception as exc:  # never stop the periodic processing no matter what (if it stopped, the liveness check would no longer work)
                print("[motion] tick failed: %s: %s" % (type(exc).__name__, exc))
            time.sleep(max(0.0, period - (time.monotonic() - started)))
    t = threading.Thread(target=loop, daemon=True, name="motion-tick")
    t.start()
    return t
