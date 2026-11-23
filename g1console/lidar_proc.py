"""Check, start and stop the lidar stream process (lidar_stream.py on the Jetson).

Calls ~/g1_console_lidar/lidar_ctl.sh on the Jetson over ssh, once per call (same design as camera_proc. Does not touch DDS or the motors).
"""
import math
import struct
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from g1console.camera_proc import SEP, LocalRunMixin, SshCameraCtl, parse_status

REMOTE_DIR = "~/g1_console_lidar"
ACTIONS = ("status", "start", "stop")
MOCK_POINTS = 1500
MOCK_PERIOD_S = 20.0  # time for the mock point cloud to make one revolution


VOXEL_MAX_M = 1.0
POINTS_MIN, POINTS_MAX = 100, 30000  # keep in sync with the range in jetson/lidar_stream.py


def forward_query(path: str) -> str:
    """From the UI's `/lidar?voxel=..&max=..`, turn only the numerically valid values into a string to pass upstream (with a leading `?`, or empty if none).
    Unknown keys, invalid values and out-of-range values are dropped (so arbitrary strings cannot get into the upstream URL)."""
    qs = parse_qs(urlsplit(path).query)
    out = {}
    try:
        voxel = float(qs["voxel"][0])
        if 0.0 <= voxel <= VOXEL_MAX_M:
            out["voxel"] = "%g" % voxel
    except (KeyError, ValueError):
        pass
    try:
        points = int(qs["max"][0])
        if POINTS_MIN <= points <= POINTS_MAX:
            out["max"] = str(points)
    except (KeyError, ValueError):
        pass
    return "?" + urlencode(out) if out else ""


class SshLidarCtl(SshCameraCtl):
    ENV = "LIDAR"

    def __init__(self, target_fn, port_fn):
        super().__init__(target_fn, port_fn)

    def _dir(self) -> str:
        return REMOTE_DIR

    def call(self, action: str) -> dict:
        if action not in ACTIONS:
            raise ValueError("unknown action")  # only fixed words from the allowlist and integers go into the script
        ctl = self._ctl("lidar_ctl.sh")
        steps = ([ctl + " " + action] if action != "status" else ["true"]) + [ctl + " status"]
        out = self._run(("; echo %s; " % SEP).join(steps))
        message, status = (out.split(SEP + "\n") + [""])[:2]
        return {"ok": True, **parse_status(status), "message": message.strip()}


class LocalLidarCtl(LocalRunMixin, SshLidarCtl):
    def __init__(self, port_fn):
        super().__init__(lambda: (None, ""), port_fn)


class MockLidarCtl:
    """Mock without a robot. Only while started, returns a point cloud of a floor ring and a room with walls (frame())."""

    backend = "mock"

    def __init__(self):
        self.running = False

    def call(self, action: str) -> dict:
        if action not in ACTIONS:
            raise ValueError("unknown action")
        if action != "status":
            self.running = action == "start"
        return {"ok": True, "running": self.running, "pid": 4343 if self.running else None, "message": ""}

    def frame(self):
        """(binary, point count). None if not started."""
        if not self.running:
            return None
        spin = (time.time() % MOCK_PERIOD_S) / MOCK_PERIOD_S * 2 * math.pi
        out = bytearray()
        for i in range(MOCK_POINTS):
            a = i / MOCK_POINTS * 2 * math.pi * 6 + spin
            ring = 1.0 + (i % 5) * 0.8
            if i % 3:  # floor ring
                x, y, z = ring * math.cos(a), ring * math.sin(a), -0.6
            else:  # walls 4 m square
                x, y, z = 4 * max(-1.0, min(1.0, 1.6 * math.cos(a))), 4 * max(-1.0, min(1.0, 1.6 * math.sin(a))), -0.6 + (i % 7) * 0.4
            out += struct.pack("<ffff", x, y, z, float(i % 100))
        return bytes(out), MOCK_POINTS
