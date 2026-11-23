"""Backend for topic communication (holds the DDS helper on the Jetson as a child process).

Started on the first subscribe or send (not resident). Serialized; if a reply is slow it is dropped and restarted next time.
The send allowlist and denylist are also passed to the helper side, so they are checked twice.
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from g1console.topics import DENY_PATTERNS, TopicError

HELPER_SRC = Path(__file__).resolve().parent.parent / "jetson" / "topic_helper.py"
HELPER_READY_S = 15.0
HELPER_TIMEOUT_S = 2.0


class HelperTopicBackend:
    name = "local"

    def __init__(self, allowlist, sdk_dir=None):
        self._allow = {t: r["max_bytes"] for t, r in allowlist.items()}
        self._sdk_dir = Path(sdk_dir or os.environ.get("UNITREE_SDK_DIR") or "~/unitree_sdk2_python").expanduser()
        self._lock = threading.Lock()
        self._proc = None
        self._lines = queue.Queue()
        self._subs = {}  # kept so subscriptions can be redone after a restart

    def _command(self, src):
        return [sys.executable, "-u", "-c", src], str(self._sdk_dir)

    def _source(self):
        src = HELPER_SRC.read_text(encoding="utf-8")
        return src.replace("__PUBLISH__", repr(self._allow)).replace("__DENY__", repr(list(DENY_PATTERNS)))

    @staticmethod
    def _pump(proc, out):
        for line in proc.stdout:
            out.put(line)
        out.put(None)

    def _alive(self):
        return self._proc is not None and self._proc.poll() is None

    def _kill(self):
        if self._proc is not None:
            self._proc.kill()
            self._proc = None

    def _start(self):
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
            raise TopicError(502, "The topic helper does not start (check the SDK, DDS and eth0)")
        for topic, type_name in list(self._subs.items()):  # restore subscriptions after a restart
            self._call_started({"op": "sub", "topic": topic, "type": type_name})

    def _call_started(self, req):
        try:
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()
            line = self._lines.get(timeout=HELPER_TIMEOUT_S)
            if line is None:
                raise RuntimeError("helper exited")
            reply = json.loads(line)
        except (OSError, RuntimeError, queue.Empty, ValueError) as exc:
            self._kill()  # drop it so a late old reply is not mixed up
            raise TopicError(502, "The topic helper is not responding (%s)" % type(exc).__name__)
        if not reply.get("ok"):
            raise TopicError(502, "The topic helper rejected it: %s" % reply.get("error", "unknown"))
        return reply

    def _call(self, req):
        with self._lock:
            if not self._alive():
                self._start()
            return self._call_started(req)

    def subscribe(self, topic, type_name):
        self._call({"op": "sub", "topic": topic, "type": type_name})
        self._subs[topic] = type_name

    def unsubscribe(self, topic):
        self._subs.pop(topic, None)
        if self._alive():
            self._call({"op": "unsub", "topic": topic})

    def poll(self):
        return self._call({"op": "poll"}).get("items", [])

    def publish(self, topic, data):
        self._call({"op": "pub", "topic": topic, "data": data})

    def close(self):
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.stdin.close()  # EOF ends the helper
                    self._proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                self._kill()
