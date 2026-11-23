"""Settings for environment-specific connection targets (IP addresses etc.). Saved to settings.json (not tracked by git).

Values end up in ssh command lines and URLs, so they are validated strictly before saving (so a leading `-` etc. cannot inject options).
"""
import ipaddress
import json
import os
import re
import threading
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "settings.json"
DEFAULTS = {"dev_pc": "", "jetson_host": "", "jetson_user": "unitree", "jetson_key": "", "g1_ip": "", "camera_port": 8081,
            "lidar_port": 8082}
LABELS = {"dev_pc": "Development PC", "jetson_host": "Jetson PC", "jetson_user": "Jetson ssh user",
          "jetson_key": "ssh private key", "g1_ip": "G1 unit", "camera_port": "Camera stream port", "lidar_port": "lidar stream port"}

_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")
_NUMERIC = re.compile(r"^[0-9.]+$")
_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
MAX_KEY_PATH = 512


def _host(name: str, value) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        pass
    if _NUMERIC.match(v) or not _HOSTNAME.match(v):
        raise ValueError("%s must be an IP address (e.g. 192.168.123.164) or a host name" % LABELS[name])
    return v


def validate(values: dict) -> dict:
    """Return the validated settings (all items). ValueError if invalid (the message can be shown in the UI as is)."""
    out = {**DEFAULTS, **{k: values[k] for k in DEFAULTS if k in values}}
    for name in ("dev_pc", "jetson_host", "g1_ip"):
        out[name] = _host(name, out[name])
    user = str(out["jetson_user"] or "").strip()
    if user and not _USER.match(user):
        raise ValueError("%s must contain only lowercase letters, digits, _ and -" % LABELS["jetson_user"])
    out["jetson_user"] = user
    key = str(out["jetson_key"] or "").strip()
    if key.startswith("-") or "\0" in key or len(key) > MAX_KEY_PATH:
        raise ValueError("%s has an invalid path" % LABELS["jetson_key"])
    out["jetson_key"] = key
    for name in ("camera_port", "lidar_port"):
        try:
            port = int(out[name])
        except (TypeError, ValueError):
            raise ValueError("%s must be a number" % LABELS[name]) from None
        if not 1 <= port <= 65535:
            raise ValueError("%s must be between 1 and 65535" % LABELS[name])
        out[name] = port
    return out


class Settings:
    """Holds and saves the settings. If path=None, memory only (for tests). Priority: saved file > initial > defaults."""

    def __init__(self, path=DEFAULT_PATH, initial=None):
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        saved = {}
        if self._path and self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}  # if corrupt, start from the defaults (fixed on the next save)
        try:
            self._values = validate({**(initial or {}), **saved})
        except ValueError:
            self._values = validate(initial or {})

    def get(self) -> dict:
        with self._lock:
            return dict(self._values)

    def update(self, values: dict) -> dict:
        with self._lock:
            new = validate({**self._values, **values})
            if self._path:
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                os.replace(tmp, self._path)
            self._values = new
            return dict(new)

    def ssh_target(self):
        """Return (ssh target `user@host`, key path). (None, "") if not set."""
        v = self.get()
        if not v["jetson_host"]:
            return None, ""
        return (v["jetson_user"] + "@" if v["jetson_user"] else "") + v["jetson_host"], v["jetson_key"]

    def _base(self, port_key: str, resolve):
        v = self.get()
        host = resolve(v["jetson_host"]) if v["jetson_host"] else ""
        return "http://%s:%d" % (host if ":" not in host else "[%s]" % host, v[port_key]) if host else None

    def camera_base(self, resolve=lambda host: host):
        """URL of the camera stream. resolve is a function that turns an ssh alias into a name usable over HTTP."""
        return self._base("camera_port", resolve)

    def lidar_base(self, resolve=lambda host: host):
        """URL of the lidar stream."""
        return self._base("lidar_port", resolve)
