#!/usr/bin/env python3
"""Thin the G1's lidar point cloud (Livox MID-360) and serve it over HTTP. **Run this on the robot itself (Jetson).**

  python3 lidar_stream.py [--port 8082] [--nic eth0]

  GET http://<Jetson>:8082/lidar[?voxel=0.1&max=5000]
                                   -> The latest 1 frame. A binary of float32 little-endian (x, y, z, intensity) repeated for each point.
                                     voxel = voxel size [m] (0 means no thinning), max = maximum number of points. Default 0.1 m and 5000 points.
                                     With X-Lidar-Seq / X-Lidar-Points / X-Lidar-Age-Ms headers (relayed by the Console's server.py)
  GET http://<Jetson>:8082/status  -> JSON with the receive count, frequency, original point count, etc.

It only subscribes to DDS (no Publisher / Writer is created). It does not touch the motors or the lidar unit's settings.
The raw frame of about 20k points (442 KB per frame, about 10 Hz) is heavy on some links, so it is thinned by voxel per request to fit the maximum point count.
How much to thin is chosen by the receiving side (the UI).
WARNING: no authentication. Use it only on a trusted network. Standard library + numpy + cyclonedds only, so it runs on the Jetson's Python 3.8.
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

DEFAULT_PORT = 8082
DEFAULT_VOXEL_M = 0.1  # default when the request does not specify. voxel=0 means no thinning
DEFAULT_MAX_POINTS = 5000
MAX_VOXEL_M = 1.0
MIN_POINTS, MAX_POINTS = 100, 30000  # one MID-360 frame is about 20k points
DEFAULT_NIC = "eth0"
TOPIC = "rt/utlidar/cloud_livox_mid360"
DOMAIN_ID = 0
POLL_S = 0.02
TAKE_N = 10  # even if several are queued, use only the latest
VOXEL_OFFSET, VOXEL_SPAN = 1024, 2048  # pack the voxel indices into a single integer key (+/-102 m at 0.1 m)
WANT_FIELDS = ("x", "y", "z", "intensity")
START_TIME = time.time()


def setup_dds(nic: str):
    """Load cyclonedds and return a receiving DataReader (nic is passed by an environment variable before import)."""
    os.environ["CYCLONEDDS_URI"] = (
        '<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="%s"/></Interfaces></General></Domain></CycloneDDS>' % nic)
    from dataclasses import dataclass
    import cyclonedds.idl as idl
    import cyclonedds.idl.types as types
    from cyclonedds.domain import DomainParticipant
    from cyclonedds.qos import Policy, Qos
    from cyclonedds.sub import DataReader
    from cyclonedds.topic import Topic

    @dataclass
    class Time_(idl.IdlStruct, typename="builtin_interfaces::msg::dds_::Time_"):
        sec: types.int32
        nanosec: types.uint32

    @dataclass
    class Header_(idl.IdlStruct, typename="std_msgs::msg::dds_::Header_"):
        stamp: Time_
        frame_id: str

    @dataclass
    class PointField_(idl.IdlStruct, typename="sensor_msgs::msg::dds_::PointField_"):
        name: str
        offset: types.uint32
        datatype: types.uint8
        count: types.uint32

    @dataclass
    class PointCloud2_(idl.IdlStruct, typename="sensor_msgs::msg::dds_::PointCloud2_"):
        header: Header_
        height: types.uint32
        width: types.uint32
        fields: types.sequence[PointField_]
        is_bigendian: bool
        point_step: types.uint32
        row_step: types.uint32
        data: types.sequence[types.uint8]
        is_dense: bool

    dp = DomainParticipant(DOMAIN_ID)
    return DataReader(dp, Topic(dp, TOPIC, PointCloud2_), Qos(Policy.History.KeepLast(1)))


def extract(msg):
    """Extract the valid points of a PointCloud2 as an (x, y, z, intensity) float32 array (Nx4). No thinning.
    Returns (array, original point count). ValueError if a required field is missing."""
    import numpy as np
    offsets = {f.name: f.offset for f in msg.fields}
    if any(n not in offsets for n in WANT_FIELDS) or msg.point_step < 16:
        raise ValueError("Unexpected field layout: %s" % sorted(offsets))
    raw = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    count = len(raw) // msg.point_step
    dtype = np.dtype({"names": list(WANT_FIELDS), "formats": ["<f4"] * 4,
                      "offsets": [offsets[n] for n in WANT_FIELDS], "itemsize": msg.point_step})
    pts = np.frombuffer(raw[:count * msg.point_step].tobytes(), dtype=dtype)
    arr = np.stack([pts[n] for n in WANT_FIELDS], axis=1).astype(np.float32)
    ok = np.isfinite(arr).all(axis=1) & (np.abs(arr[:, :3]).sum(axis=1) > 0.0)  # drop invalid points (NaN, origin)
    return np.ascontiguousarray(arr[ok], dtype="<f4"), count


def thin(arr, voxel_m: float, max_points: int):
    """Thin to one point per voxel (no thinning if voxel_m<=0) and fit to the maximum point count."""
    import numpy as np
    if len(arr) and voxel_m > 0:
        q = np.clip(np.floor(arr[:, :3] / voxel_m).astype(np.int64) + VOXEL_OFFSET, 0, VOXEL_SPAN - 1)
        key = (q[:, 0] * VOXEL_SPAN + q[:, 1]) * VOXEL_SPAN + q[:, 2]
        _, first = np.unique(key, return_index=True)
        arr = arr[np.sort(first)]
    if len(arr) > max_points:
        arr = arr[np.linspace(0, len(arr) - 1, max_points).astype(np.int64)]  # drop evenly to fit the maximum
    return np.ascontiguousarray(arr, dtype="<f4")


def decimate(msg, voxel_m: float, max_points: int):
    """extract -> thin. Returns (thinned array, original point count)."""
    arr, count = extract(msg)
    return thin(arr, voxel_m, max_points), count


def parse_query(path: str):
    """Take (voxel_m, max_points) from `/lidar?voxel=0.05&max=10000`. Out of range or invalid values are rounded to the defaults (not an error)."""
    qs = parse_qs(urlsplit(path).query)

    def num(name, default, lo, hi, cast):
        try:
            return min(hi, max(lo, cast(qs[name][0])))
        except (KeyError, IndexError, ValueError):
            return default

    return (num("voxel", DEFAULT_VOXEL_M, 0.0, MAX_VOXEL_M, float), num("max", DEFAULT_MAX_POINTS, MIN_POINTS, MAX_POINTS, int))


class Latest:
    """Holds the latest frame (before thinning) and statistics. The receiving thread writes and the HTTP thread reads."""

    def __init__(self):
        self._lock = threading.Lock()
        self.arr = None
        self.seq = 0
        self.raw_points = 0
        self.stamp = 0.0
        self.errors = 0
        self.last_error = ""
        self._recent = []
        self._cache = {}  # (seq, voxel, max) -> (body, point count). Requests with the same conditions thin only once

    def put(self, arr, raw_points: int):
        now = time.time()
        with self._lock:
            self.arr, self.raw_points, self.stamp = arr, raw_points, now
            self.seq += 1
            self._cache = {}
            self._recent = [t for t in self._recent if now - t < 5.0] + [now]

    def fail(self, text: str):
        with self._lock:
            self.errors += 1
            self.last_error = text

    def frame(self, voxel_m: float, max_points: int):
        """The latest frame thinned by (voxel, max): (body, seq, point count, receive time). body=None if there is none yet."""
        with self._lock:
            arr, seq, stamp = self.arr, self.seq, self.stamp
            hit = self._cache.get((seq, voxel_m, max_points))
        if arr is None:
            return None, 0, 0, 0.0
        if hit is None:
            thinned = thin(arr, voxel_m, max_points)
            hit = (thinned.tobytes(), len(thinned))
            with self._lock:
                if self.seq == seq:
                    self._cache[(seq, voxel_m, max_points)] = hit
        return hit[0], seq, hit[1], stamp

    def status(self) -> dict:
        now = time.time()
        with self._lock:
            hz = round((len(self._recent) - 1) / (self._recent[-1] - self._recent[0]), 2) if len(self._recent) > 1 and now - self._recent[-1] < 5.0 else 0.0
            return {"frames": self.seq, "hz": hz, "points": len(self.arr) if self.arr is not None else 0, "raw_points": self.raw_points,
                    "age_s": round(now - self.stamp, 2) if self.stamp else None,
                    "errors": self.errors, "last_error": self.last_error, "uptime_s": round(now - START_TIME, 1)}


def receive_loop(reader, latest: Latest):
    from cyclonedds.internal import InvalidSample
    while True:
        try:
            msgs = [m for m in reader.take(N=TAKE_N) if not isinstance(m, InvalidSample)]
            if msgs:
                arr, raw = extract(msgs[-1])
                latest.put(arr, raw)
        except Exception as exc:  # do not stop for one frame's failure. Continue with the next frame
            latest.fail("%s: %s" % (type(exc).__name__, exc))
            time.sleep(0.5)
        time.sleep(POLL_S)


def make_handler(latest: Latest):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, data: bytes, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/lidar":
                body, seq, points, stamp = latest.frame(*parse_query(self.path))
                if body is None:
                    return self._send(503, "application/json", b'{"error": "no frame yet"}')
                self._send(200, "application/octet-stream", body,
                           {"X-Lidar-Seq": seq, "X-Lidar-Points": points, "X-Lidar-Age-Ms": int((time.time() - stamp) * 1000)})
            elif self.path == "/status":
                self._send(200, "application/json", json.dumps(latest.status()).encode("utf-8"))
            else:
                self._send(404, "application/json", b'{"error": "not found"}')

        def log_message(self, fmt, *args):  # no access log (the log would grow)
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--nic", default=DEFAULT_NIC, help="NIC used for DDS")
    parser.add_argument("--bind", default="0.0.0.0", help="Address to listen on (127.0.0.1 if the console runs on the same machine)")
    args = parser.parse_args()
    reader = setup_dds(args.nic)
    latest = Latest()
    threading.Thread(target=receive_loop, args=(reader, latest), daemon=True).start()
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(latest))
    print("[lidar] serving http://%s:%d/lidar?voxel=<m>&max=<points> (nic=%s)" % (args.bind, args.port, args.nic), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
