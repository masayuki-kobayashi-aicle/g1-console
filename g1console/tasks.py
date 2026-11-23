"""Task definitions and execution. Only what is listed in tasks/*.json can run.

- A definition is an argv array. It does not go through a shell (shell=False), so a value containing `; rm -rf` is passed as a plain string.
- The client can pass only the task name. It cannot pass argv, cwd or environment variables.
- The child process starts in a new session (process group); to stop it, SIGTERM and then, after a grace period, SIGKILL are sent to the group.
- Tasks in the same exclusive group are not run at the same time. The log is a line-based ring buffer, and `since` (the last seq seen) returns what came after it.
Python 3.8 compatible (Jetson). Standard library only.
"""
import collections
import json
import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
DEF_KEYS = {"title", "description", "argv", "cwd", "group", "timeout_s", "verified", "caution"}
CAUTION_MAX_ITEMS = 8
CAUTION_MAX_CHARS = 200
TIMEOUT_MAX_S = 3600
DEFAULT_TIMEOUT_S = 600
RING_LINES = 2000
LINE_MAX_CHARS = 2000
TERM_GRACE_S = 3.0
READER_JOIN_S = 2.0


class TaskError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class TaskDef:
    def __init__(self, name, title, description, argv, cwd, group, timeout_s, verified=False, caution=()):
        self.name, self.title, self.description = name, title, description
        self.argv, self.cwd, self.group, self.timeout_s = tuple(argv), cwd, group, timeout_s
        self.verified, self.caution = verified, tuple(caution)


def _parse_def(name: str, raw: dict, base_dir: Path) -> TaskDef:
    if not NAME_RE.match(name):
        raise ValueError("Task name must be lowercase letters, digits, _ and - up to 40 characters: %r" % name)
    if not isinstance(raw, dict):
        raise ValueError("%s: the definition must be a JSON object" % name)
    extra = set(raw) - DEF_KEYS
    if extra:
        raise ValueError("%s: unknown key %s" % (name, sorted(extra)))
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError("%s: argv must be an array of non-empty strings (a shell string is not allowed)" % name)
    cwd = raw.get("cwd", ".")
    if not isinstance(cwd, str) or os.path.isabs(cwd):
        raise ValueError("%s: cwd must be a path relative to Console" % name)
    resolved = (base_dir / cwd).resolve()
    if base_dir.resolve() != resolved and base_dir.resolve() not in resolved.parents:
        raise ValueError("%s: cwd points outside Console" % name)
    group = raw.get("group")
    if group is not None and not (isinstance(group, str) and NAME_RE.match(group)):
        raise ValueError("%s: group must be lowercase letters, digits, _ and -" % name)
    timeout_s = raw.get("timeout_s", DEFAULT_TIMEOUT_S)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 1 <= timeout_s <= TIMEOUT_MAX_S:
        raise ValueError("%s: timeout_s must be between 1 and %d" % (name, TIMEOUT_MAX_S))
    title, description = raw.get("title", name), raw.get("description", "")
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("%s: title / description must be strings" % name)
    verified = raw.get("verified", False)  # default is "unverified on the real robot"; only what has been verified is set to true
    if not isinstance(verified, bool):
        raise ValueError("%s: verified must be true / false" % name)
    caution = raw.get("caution", [])
    if (not isinstance(caution, list) or len(caution) > CAUTION_MAX_ITEMS
            or not all(isinstance(c, str) and 0 < len(c) <= CAUTION_MAX_CHARS for c in caution)):
        raise ValueError("%s: caution must be an array of at most %d strings of at most %d characters each" % (name, CAUTION_MAX_ITEMS, CAUTION_MAX_CHARS))
    return TaskDef(name, title, description, argv, cwd, group, float(timeout_s), verified, caution)


def load_definitions(task_dir, base_dir) -> dict:
    """Read tasks/*.json. If even one is invalid, ValueError (not silently skipped, so it is noticed at startup)."""
    defs = {}
    for path in sorted(Path(task_dir).glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Cannot read %s: %s" % (path.name, exc))
        defs[path.stem] = _parse_def(path.stem, raw, Path(base_dir))
    return defs


class _Run:
    def __init__(self, proc, started_at):
        self.proc, self.started_at, self.ended_at = proc, started_at, None
        self.exit_code = None
        self.result = None  # ok / failed / stopped / timeout / error
        self.stop_requested = False
        self.timed_out = False
        self.lines = collections.deque(maxlen=RING_LINES)
        self.next_seq = 1


class TaskRunner:
    def __init__(self, defs, base_dir, term_grace_s=TERM_GRACE_S, wall=time.time):
        self._defs, self._base = dict(defs), Path(base_dir)
        self._grace, self._wall = term_grace_s, wall
        self._lock = threading.Lock()
        self._runs = {}

    # ---- lookup --------------------------------------------------------------------------------------------
    def _view(self, d: TaskDef) -> dict:
        run = self._runs.get(d.name)
        running = bool(run) and run.ended_at is None
        return {
            "name": d.name, "title": d.title, "description": d.description, "argv": list(d.argv),
            "group": d.group, "timeout_s": d.timeout_s, "verified": d.verified, "caution": list(d.caution),
            "state": "stopping" if running and run.stop_requested else ("running" if running else "idle"),
            "result": run.result if run else None, "exit_code": run.exit_code if run else None,
            "started_at": run.started_at if run else None, "ended_at": run.ended_at if run else None,
        }

    def list(self) -> dict:
        with self._lock:
            return {"tasks": [self._view(d) for d in self._defs.values()]}

    def _def(self, name) -> TaskDef:
        d = self._defs.get(name) if isinstance(name, str) else None
        if d is None:
            raise TaskError(404, "No such task in the definitions")
        return d

    def logs(self, name, since=0) -> dict:
        d = self._def(name)
        with self._lock:
            run = self._runs.get(d.name)
            if run is None:
                return {"name": d.name, "lines": [], "next": 0, "truncated": False}
            oldest = run.lines[0][0] if run.lines else run.next_seq
            return {"name": d.name, "next": run.next_seq - 1, "truncated": since + 1 < oldest,
                    "lines": [{"seq": s, "text": t} for s, t in run.lines if s > since]}

    # ---- start / stop --------------------------------------------------------------------------------------
    def start(self, name) -> dict:
        d = self._def(name)
        with self._lock:
            for other in self._defs.values():
                run = self._runs.get(other.name)
                if run and run.ended_at is None and (other.name == d.name or (d.group and other.group == d.group)):
                    raise TaskError(409, "Already running: %s" % other.title)
            try:
                proc = subprocess.Popen(
                    list(d.argv), cwd=str((self._base / d.cwd).resolve()), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, start_new_session=True,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
            except OSError as exc:
                raise TaskError(500, "Cannot start: %s" % exc)
            run = _Run(proc, self._wall())
            self._runs[d.name] = run
            reader = threading.Thread(target=self._read, args=(run,), daemon=True)
            reader.start()
            threading.Thread(target=self._wait, args=(d, run, reader), daemon=True).start()
            return self._view(d)

    def _read(self, run: _Run):
        for raw in run.proc.stdout:
            text = raw.decode("utf-8", "replace").rstrip("\r\n")[:LINE_MAX_CHARS]
            with self._lock:
                run.lines.append((run.next_seq, text))
                run.next_seq += 1

    def _kill_group(self, run: _Run, sig):
        try:
            os.killpg(run.proc.pid, sig)  # it was started in a new session, so pid = pgid
        except (ProcessLookupError, PermissionError):
            pass

    def _wait(self, d: TaskDef, run: _Run, reader):
        try:
            run.proc.wait(timeout=d.timeout_s)
        except subprocess.TimeoutExpired:
            with self._lock:
                run.timed_out = True
            self._terminate(run)
            run.proc.wait()
        self._kill_group(run, signal.SIGKILL)  # take any remaining grandchildren along
        reader.join(READER_JOIN_S)
        with self._lock:
            run.exit_code = run.proc.returncode
            run.ended_at = self._wall()
            run.result = ("timeout" if run.timed_out else "stopped" if run.stop_requested
                          else "ok" if run.exit_code == 0 else "failed")

    def _terminate(self, run: _Run):
        """Send SIGTERM to the group, then SIGKILL if anything is still left after the grace period."""
        self._kill_group(run, signal.SIGTERM)

        def escalate():
            try:
                run.proc.wait(timeout=self._grace)
            except subprocess.TimeoutExpired:
                self._kill_group(run, signal.SIGKILL)
        threading.Thread(target=escalate, daemon=True).start()

    def stop(self, name) -> dict:
        d = self._def(name)
        with self._lock:
            run = self._runs.get(d.name)
            if run is None or run.ended_at is not None:
                raise TaskError(409, "Not running")
            run.stop_requested = True
            view = self._view(d)
        self._terminate(run)
        return view

    def shutdown(self):
        """When the hub exits. Stop everything that is running (wait up to SIGKILL)."""
        with self._lock:
            running = [r for r in self._runs.values() if r.ended_at is None]
            for r in running:
                r.stop_requested = True
        for r in running:
            self._kill_group(r, signal.SIGTERM)
        deadline = time.monotonic() + self._grace
        for r in running:
            try:
                r.proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            self._kill_group(r, signal.SIGKILL)
