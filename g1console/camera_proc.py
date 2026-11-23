"""Check, start and stop the camera stream process (camera_stream.py on the Jetson).

Calls ~/g1_console_camera/camera_ctl.sh on the Jetson over ssh, once per call (separate from the resident helper. Does not touch DDS).
With --local, ssh is not used and jetson/camera_ctl.sh in this repository is called directly (the stream listens only on 127.0.0.1).
The hub does not start the stream on its own (the port is used only when "Start" is pressed in the UI).
holders are "processes holding the video devices". If videohub_pc4 or similar holds one, camera_stream cannot open it.
"""
import ipaddress
import re
import shlex
import subprocess
from pathlib import Path

REMOTE_DIR = "~/g1_console_camera"
LOCAL_CTL_DIR = Path(__file__).resolve().parent.parent / "jetson"  # where to call the ctl scripts from with --local
LOCAL_STATE_DIR = "~/.g1console/run"  # where pid and log go with --local
LOOPBACK = "127.0.0.1"
CTL_TIMEOUT_S = 30.0  # start waits about 2 seconds to confirm startup
ACTIONS = ("status", "start", "stop")
OWN_MARK = "camera_stream.py"
SEP = "@@camera-ctl-sep@@"
OWN_RE = re.compile(r"(^|[\s/])python[0-9.]*\s+(-u\s+)?\S*camera_stream\.py(\s|$)")  # only "python ... camera_stream.py" counts as our own


_RESOLVED = {}


def resolve_host(host: str) -> str:
    """Turn an ssh alias (Host in ~/.ssh/config) into the real host name, because an alias cannot be used as an HTTP destination.
    If it cannot be resolved, return it as is. The result is remembered (so ssh is not called every time). An IP literal is returned as is without asking ssh."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if host not in _RESOLVED:
        try:
            done = subprocess.run(["ssh", "-G", "--", host], capture_output=True, text=True, timeout=5)
            names = [l.split(None, 1)[1] for l in done.stdout.splitlines() if l.startswith("hostname ")]
            _RESOLVED[host] = names[0].strip() if names else host
        except (OSError, subprocess.TimeoutExpired):
            _RESOLVED[host] = host  # remember failures too (do not make every call wait 5 seconds). After a settings change it is a different host string
    return _RESOLVED[host]


def parse_holders(text: str) -> list:
    """Turn the output of camera_ctl.sh holders (device<TAB>PID<TAB>user<TAB>command) into a list of dicts."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[1].isdigit():
            device, pid, user, cmd = parts
            out.append({"device": device, "pid": int(pid), "user": user, "cmd": cmd, "own": bool(OWN_RE.search(cmd))})
    return out


def parse_status(text: str) -> dict:
    """From the output of camera_ctl.sh status, extract whether it is running and the PID."""
    running = "running" in text
    pid = None
    if running and "pid=" in text:
        digits = text.split("pid=", 1)[1].rstrip(") \n")
        pid = int(digits) if digits.isdigit() else None
    return {"running": running, "pid": pid}


def summarize(status_text: str, holders_text: str) -> dict:
    holders = parse_holders(holders_text)
    return {"ok": True, **parse_status(status_text), "holders": holders,
            "foreign": [h for h in holders if not h["own"]]}  # held by something other than ours = possible conflict


class SshCameraCtl:
    backend = "ssh"
    ENV = "CAMERA"  # prefix of the environment variable CAMERA_PORT that passes the stream port (LIDAR for lidar)

    def __init__(self, target_fn, port_fn=None):
        self._target_fn = target_fn  # () -> (user@host or None, key)
        self._port_fn = port_fn  # () -> stream port (validated integer). If None, the ctl script default

    def _dir(self) -> str:
        return REMOTE_DIR

    def _extra_env(self) -> list:
        return []

    def _ctl(self, script: str) -> str:
        """Invocation of the ctl script (with environment variables). Only fixed words, integers and paths inside this repository go in."""
        env = ["%s_PORT=%d" % (self.ENV, int(self._port_fn()))] if self._port_fn else []
        return " ".join(env + self._extra_env() + ["%s/%s" % (self._dir(), script)])

    def _run(self, script: str) -> str:
        host, key = self._target_fn()
        if not host:
            raise RuntimeError("The Jetson target is not set (enter it in the Settings tab)")
        key_opt = ["-i", key] if key else []
        cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", *key_opt, "--", host, script]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=CTL_TIMEOUT_S)
        if done.returncode == 255:
            raise RuntimeError("Cannot ssh to the Jetson: %s" % (done.stderr.strip().splitlines() or [""])[-1])
        return done.stdout

    def call(self, action: str) -> dict:
        """Run the operation (other than status), status and holders in one ssh, and split them into 3 parts at the SEP line."""
        if action not in ACTIONS:
            raise ValueError("unknown action")  # only fixed words from the allowlist go into the script
        ctl = self._ctl("camera_ctl.sh")
        steps = ([ctl + " " + action] if action != "status" else ["true"]) + [ctl + " status", ctl + " holders"]
        out = self._run(("; echo %s; " % SEP).join(steps))
        message, status, holders = (out.split(SEP + "\n") + ["", ""])[:3]
        return {**summarize(status, holders), "message": message.strip()}


class LocalRunMixin:
    """Run the ctl script directly from this process on the Jetson, without ssh (when the console runs on the Jetson)."""

    backend = "local"

    def _dir(self) -> str:
        return shlex.quote(str(LOCAL_CTL_DIR))  # no need to copy to ~/g1_console_*; use jetson/ of this repository as is

    def _extra_env(self) -> list:
        # let only this machine (the hub) read the stream (do not open it to wlan0 without authentication). Put pid and log outside the repository
        return ["G1_CTL_STATE_DIR=%s" % shlex.quote(str(Path(LOCAL_STATE_DIR).expanduser())), "%s_BIND=%s" % (self.ENV, LOOPBACK)]

    def _run(self, script: str) -> str:
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=CTL_TIMEOUT_S)
        return done.stdout


class LocalCameraCtl(LocalRunMixin, SshCameraCtl):
    def __init__(self, port_fn=None):
        super().__init__(lambda: (None, ""), port_fn)


class MockCameraCtl:
    """Mock without a robot. videohub holds video4, and camera_stream can be started / stopped."""

    backend = "mock"

    def __init__(self):
        self.running = False

    def call(self, action: str) -> dict:
        if action not in ACTIONS:
            raise ValueError("unknown action")
        if action != "status":
            self.running = action == "start"
        status = "[camera] running (pid=4242)" if self.running else "[camera] stopped"
        holders = "/dev/video4\t9113\troot\t/unitree/module/video_hub_pc4/videohub_pc4 /dev/video4\n"
        if self.running:
            holders += "/dev/video0\t4242\tunitree\tpython -u camera_stream.py --camera std=/dev/video0\n"
        return {**summarize(status, holders), "message": ""}
