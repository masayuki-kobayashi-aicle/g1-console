"""Topic communication policy (receiving is free, sending is allowlist only) and the service layer that enforces it.

- Only String_ topics listed in the `--topics-file` allowlist can be sent. Anything not listed is rejected (default is empty).
- The denylist (DENY_PATTERNS) always beats the allowlist. Writing a denied topic in the allowlist stops startup.
- Sending has a per-topic minimum interval and maximum byte size.
- Receiving is limited to topics whose type the helper knows. If the type is unsupported, the subscription is refused (do not pretend to read what cannot be read).
The backend (the DDS helper on the Jetson) is in a separate file. This file only has side-effect-free decisions and hand-offs.
"""
import fnmatch
import json
import os
import re
import threading
import time
from pathlib import Path

# Topics that are always refused for sending (fnmatch, compared in lowercase; * also matches /). All of motion, joints, arms, hands, remote controller, emergency stop, and RPC.
DENY_PATTERNS = (
    "rt/lowcmd", "rt/lf/lowcmd", "rt/arm_sdk", "rt/api/*", "rt/*/cmd",
    "rt/wirelesscontroller", "rt/lf/emergency_stop", "rt/lf/*state", "rt/lowstate", "rt/odommodestate",
)
SUPPORTED_TYPES = ("String_", "Error_", "WirelessController_", "BmsState_", "IMUState_", "SportModeState_")
PUBLISH_TYPES = ("String_",)  # for now this is the only type that can be sent

TOPIC_RE = re.compile(r"^rt/[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+){0,5}$")
MAX_SUBSCRIPTIONS = 8
MAX_ALLOWED_TOPICS = 50
DEFAULT_MAX_BYTES = 512
HARD_MAX_BYTES = 4096
DEFAULT_MIN_INTERVAL_S = 1.0
MIN_INTERVAL_FLOOR_S = 0.1


class TopicError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def validate_topic(name):
    """Validate and return the topic name. TopicError(400) if invalid."""
    if not isinstance(name, str) or len(name) > 120 or not TOPIC_RE.match(name):
        raise TopicError(400, "topic must be a name starting with rt/ made of alphanumerics, _, -, / (up to 120 characters)")
    return name


def is_denied(topic):
    low = topic.lower()
    return any(fnmatch.fnmatchcase(low, pat) for pat in DENY_PATTERNS)


def load_allowlist(path):
    """Read the allowlist (JSON). A missing file is empty. ValueError (stops startup) if broken."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = doc["publish"]
        if doc.get("version") != 1 or not isinstance(rows, list) or len(rows) > MAX_ALLOWED_TOPICS:
            raise ValueError("a {publish: [...]} with version=1 (at most %d entries) is required" % MAX_ALLOWED_TOPICS)
        out = {}
        for row in rows:
            topic = validate_topic(row.get("topic"))
            if is_denied(topic):
                raise ValueError("%s is a topic that is always refused" % topic)
            if row.get("type", "String_") not in PUBLISH_TYPES:
                raise ValueError("%s: the only type that can be sent is %s" % (topic, "/".join(PUBLISH_TYPES)))
            max_bytes = row.get("max_bytes", DEFAULT_MAX_BYTES)
            interval = row.get("min_interval_s", DEFAULT_MIN_INTERVAL_S)
            if (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= HARD_MAX_BYTES
                    or isinstance(interval, bool) or not isinstance(interval, (int, float))
                    or interval < MIN_INTERVAL_FLOOR_S):
                raise ValueError("%s: max_bytes must be 1 to %d and min_interval_s at least %.1f" % (
                    topic, HARD_MAX_BYTES, MIN_INTERVAL_FLOOR_S))
            out[topic] = {"topic": topic, "type": "String_", "max_bytes": max_bytes, "min_interval_s": float(interval),
                          "note": str(row.get("note", ""))[:200]}
        return out
    except (KeyError, TypeError, AttributeError, OSError) as exc:
        raise ValueError("Cannot read %s: %r" % (path, exc))
    except TopicError as exc:
        raise ValueError(exc.message)


class MockTopicBackend:
    """For --mock. Subscribing returns a fake String_, and sending is only recorded (nothing goes out)."""

    name = "mock"

    def __init__(self):
        self.published = []
        self._subs = {}

    def subscribe(self, topic, type_name):
        self._subs[topic] = {"topic": topic, "type": type_name, "n": 0}

    def unsubscribe(self, topic):
        self._subs.pop(topic, None)

    def poll(self):
        out = []
        for sub in self._subs.values():
            sub["n"] += 1
            out.append({"topic": sub["topic"], "type": sub["type"], "age_s": 0.0, "count": sub["n"],
                        "message": {"data": "mock %d" % sub["n"]}})
        return out

    def publish(self, topic, data):
        self.published.append((topic, data))

    def close(self):
        pass


class TopicService:
    def __init__(self, backend, allowlist=None, clock=time.monotonic):
        self._backend, self._allow, self._clock = backend, dict(allowlist or {}), clock
        self._lock = threading.Lock()
        self._subs = {}
        self._last_pub = {}

    def info(self):
        with self._lock:
            subs = sorted(self._subs)
        return {"enabled": True, "backend": self._backend.name, "deny": list(DENY_PATTERNS),
                "supported_types": list(SUPPORTED_TYPES), "max_subscriptions": MAX_SUBSCRIPTIONS,
                "publish": sorted(self._allow.values(), key=lambda r: r["topic"]), "subscribed": subs}

    def subscribe(self, topic, type_name):
        validate_topic(topic)
        if type_name not in SUPPORTED_TYPES:
            raise TopicError(422, "Type %r cannot be read (supported: %s). Subscribing by name only is not possible" % (type_name, " / ".join(SUPPORTED_TYPES)))
        with self._lock:
            if topic not in self._subs and len(self._subs) >= MAX_SUBSCRIPTIONS:
                raise TopicError(409, "At most %d subscriptions" % MAX_SUBSCRIPTIONS)
            self._backend.subscribe(topic, type_name)
            self._subs[topic] = type_name
        return {"topic": topic, "type": type_name}

    def unsubscribe(self, topic):
        validate_topic(topic)
        with self._lock:
            if topic not in self._subs:
                raise TopicError(404, "Not subscribed")
            self._backend.unsubscribe(topic)
            del self._subs[topic]
        return {"unsubscribed": topic}

    def received(self):
        with self._lock:
            if not self._subs:
                return {"items": []}
            return {"items": self._backend.poll()}

    def publish(self, topic, data):
        validate_topic(topic)
        if is_denied(topic):
            raise TopicError(403, "%s is a topic that is always refused for sending" % topic)
        rule = self._allow.get(topic)
        if rule is None:
            raise TopicError(403, "%s is not in the send allowlist" % topic)
        if not isinstance(data, str) or not data:
            raise TopicError(400, "data must be a non-empty string")
        size = len(data.encode("utf-8"))
        if size > rule["max_bytes"]:
            raise TopicError(413, "data must be at most %d bytes (got %d bytes)" % (rule["max_bytes"], size))
        with self._lock:
            now = self._clock()
            wait = self._last_pub.get(topic, -1e9) + rule["min_interval_s"] - now
            if wait > 0:
                raise TopicError(429, "Sending too fast. Wait %.1f more seconds" % wait)
            self._backend.publish(topic, data)  # do not consume the interval on failure
            self._last_pub[topic] = now
        return {"published": topic, "bytes": size}

    def close(self):
        self._backend.close()


def default_allowlist_path(console_dir):
    return os.path.join(str(console_dir), "data", "topics.json")


def handle(service, method, path, body=None):
    """HTTP entry. None for a route that does not apply. Returns (status, dict that can be JSON)."""
    try:
        if method == "GET" and path == "/api/topics":
            return 200, service.info()
        if method == "GET" and path == "/api/topics/received":
            return 200, service.received()
        if method != "POST" or not path.startswith("/api/topics/"):
            return None
        kind = path[len("/api/topics/"):]
        if kind not in ("subscribe", "unsubscribe", "publish"):
            return None
        if not isinstance(body, dict):
            raise TopicError(400, "The body must be a JSON object")
        if kind == "subscribe":
            return 200, service.subscribe(body.get("topic"), body.get("type"))
        if kind == "unsubscribe":
            return 200, service.unsubscribe(body.get("topic"))
        return 200, service.publish(body.get("topic"), body.get("data"))
    except TopicError as exc:
        return exc.status, {"error": exc.message}
