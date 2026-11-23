#!/usr/bin/env python3
"""Serve the G1's cameras as MJPEG (HTTP). **Run this on the robot itself (Jetson).**

  python3 camera_stream.py --list
  python3 camera_stream.py --camera std=/dev/v4l/by-id/usb-SunplusIT_..._webcam_...-video-index0 \
                           --camera d435i=videoclient:eth0   # official path (RGB without stopping videohub)

  http://<Jetson>:8081/<name>   <- relayed by the Console's server.py (/camera/<name>)

WARNING: it does not touch the motors (it only reads the camera and streams it). It has no authentication, so use it only on a trusted network.
WARNING: specify devices by the stable by-id name, not by the /dev/videoN number (the number changes on re-enumeration).
Standard library + cv2 only, so it runs on the Jetson's Python 3.8.
"""
import argparse
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

DEFAULT_PORT = 8081
FRAME_W, FRAME_H, FPS = 640, 480, 15
JPEG_QUALITY = 80
BOUNDARY = "frame"
REOPEN_WAIT_S = 2.0
DEPTH_MAX_MM = 4000  # display limit of depth (anything farther gets the same color). One Z16 unit is 1 mm


class Grabber(threading.Thread):
    """Keep reading one camera and keep only the latest JPEG. Reopen if it gets disconnected."""

    def __init__(self, name: str, device: str):
        super().__init__(daemon=True)
        self.name, self.device = name, device
        self._lock = threading.Lock()
        self._jpeg = None
        self._seq = 0

    def latest(self):
        with self._lock:
            return self._seq, self._jpeg

    def run(self):
        while True:
            # OpenCV cannot open by a by-id name ("can't be used to capture by name").
            # Just before opening, resolve it to the real device (/dev/videoN) and open by number (follows number changes after re-enumeration).
            real = os.path.realpath(self.device)
            cap = cv2.VideoCapture(int(real.replace("/dev/video", "")), cv2.CAP_V4L2) \
                if real.startswith("/dev/video") else cv2.VideoCapture(real, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            cap.set(cv2.CAP_PROP_FPS, FPS)
            if not cap.isOpened():
                print("[camera] %s: cannot open (%s)" % (self.name, self.device), flush=True)
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ok:
                    with self._lock:
                        self._jpeg, self._seq = enc.tobytes(), self._seq + 1
            cap.release()
            with self._lock:
                self._jpeg = None  # do not keep serving old video
            time.sleep(REOPEN_WAIT_S)


class DepthGrabber(Grabber):
    """Read the D435i depth (Z16, 1 unit = 1 mm) with pyrealsense2 and make a colormap JPEG aligned to the RGB (1920x1080) viewpoint.
    The depth is on USB interface 1.0, separate from videohub_pc4 (1.3), which holds the RGB.
    Alignment reprojects in 3D using the camera intrinsics and extrinsics (profile information; no color stream is used).
    0 (no range) and outside the RGB field of view are black; nearer is redder, farther is bluer. Receive only."""

    WIDTH, HEIGHT, DEPTH_FPS, WAIT_MS = 640, 480, 15, 5000
    COLOR_W, COLOR_H, OUT_SCALE = 1920, 1080, 0.5  # output is the RGB scaled down to 960x540 (same 16:9)

    def _calibration(self, rs):
        """Return (depth ray grid xn,yn, rotation R, translation t, color fx,fy,ppx,ppy)."""
        dev = rs.context().query_devices()[0]
        color = next(s for s in dev.query_sensors() if s.get_info(rs.camera_info.name) == "RGB Camera")
        cp = next(p for p in color.get_stream_profiles() if p.stream_type() == rs.stream.color
                  and p.format() == rs.format.rgb8 and p.as_video_stream_profile().width() == self.COLOR_W
                  and p.as_video_stream_profile().height() == self.COLOR_H).as_video_stream_profile()
        dp = next(p for p in dev.first_depth_sensor().get_stream_profiles() if p.stream_type() == rs.stream.depth
                  and p.format() == rs.format.z16 and p.as_video_stream_profile().width() == self.WIDTH
                  and p.as_video_stream_profile().height() == self.HEIGHT).as_video_stream_profile()
        di, ci, ex = dp.get_intrinsics(), cp.get_intrinsics(), dp.get_extrinsics_to(cp)
        us, vs = np.meshgrid(np.arange(self.WIDTH), np.arange(self.HEIGHT))
        xn, yn = (us - di.ppx) / di.fx, (vs - di.ppy) / di.fy
        rot = np.array(ex.rotation, dtype=np.float64).reshape(3, 3).T  # librealsense is column-major
        return xn, yn, rot, np.array(ex.translation, dtype=np.float64), (ci.fx, ci.fy, ci.ppx, ci.ppy)

    def _align(self, depth, calib):
        """Turn depth (mm, 480x640) into depth in the RGB viewpoint (m, 540x960; invalid is 0). Nearer points take priority and are filled in 2x2."""
        xn, yn, rot, trans, (fx, fy, ppx, ppy) = calib
        z = depth.astype(np.float64) * 0.001
        ok = z > 0
        z, x, y = z[ok], xn[ok] * z[ok], yn[ok] * z[ok]
        zc = rot[2, 0] * x + rot[2, 1] * y + rot[2, 2] * z + trans[2]
        front = zc > 0  # project only points in front of the color camera (for 0 or less the division breaks)
        z, x, y, zc = z[front], x[front], y[front], zc[front]
        u = (fx * (rot[0, 0] * x + rot[0, 1] * y + rot[0, 2] * z + trans[0]) / zc + ppx) * self.OUT_SCALE
        v = (fy * (rot[1, 0] * x + rot[1, 1] * y + rot[1, 2] * z + trans[1]) / zc + ppy) * self.OUT_SCALE
        w, h = int(self.COLOR_W * self.OUT_SCALE), int(self.COLOR_H * self.OUT_SCALE)
        u, v = np.floor(u).astype(np.int32), np.floor(v).astype(np.int32)
        order = np.argsort(-zc)  # write from far to near = the nearer point written last remains
        out = np.full((h, w), np.inf)
        for du, dv in ((0, 0), (1, 0), (0, 1), (1, 1)):
            uu, vv = u[order] + du, v[order] + dv
            inside = (uu >= 0) & (uu < w) & (vv >= 0) & (vv < h)
            layer = np.full((h, w), np.inf)
            layer[vv[inside], uu[inside]] = zc[order][inside]
            out = np.minimum(out, layer)
        out[~np.isfinite(out)] = 0
        return out

    def run(self):
        calib = None
        while True:
            pipe = None
            try:  # initialization (import, calibration) failures are also retried. Do not let the thread end silently
                import pyrealsense2 as rs
                calib = calib or self._calibration(rs)
                pipe = rs.pipeline()
                cfg = rs.config()
                cfg.enable_stream(rs.stream.depth, self.WIDTH, self.HEIGHT, rs.format.z16, self.DEPTH_FPS)
                pipe.start(cfg)
                while True:
                    depth = np.asanyarray(pipe.wait_for_frames(self.WAIT_MS).get_depth_frame().get_data())
                    aligned_mm = self._align(depth, calib) * 1000.0
                    scaled = (255 - np.clip(aligned_mm, 0, DEPTH_MAX_MM) * 255 / DEPTH_MAX_MM).astype(np.uint8)
                    color = cv2.applyColorMap(scaled, cv2.COLORMAP_JET)
                    color[aligned_mm == 0] = 0
                    ok, enc = cv2.imencode(".jpg", color, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                    if ok:
                        with self._lock:
                            self._jpeg, self._seq = enc.tobytes(), self._seq + 1
            except Exception as exc:  # unplugged, timeout, D435i not connected, no pyrealsense2, etc.
                print("[camera] %s: cannot read depth (%s: %s)" % (self.name, type(exc).__name__, exc), flush=True)
            if pipe is not None:
                try:
                    pipe.stop()
                except RuntimeError:
                    pass
            with self._lock:
                self._jpeg = None
            time.sleep(REOPEN_WAIT_S)


class VideoClientGrabber(Grabber):
    """Official path VideoClient.GetImageSample() (receive only). Works even if videohub_pc4 holds /dev/video4.
    Keeps the JPEG as is without decoding it. It never sends any command to the robot."""

    ERROR_WAIT_S = 1.0

    def __init__(self, name: str, interface: str):
        super().__init__(name, "videoclient:" + interface)
        self.interface = interface

    def run(self):
        factory_ready = False
        while True:
            try:  # initialization failures (no SDK, wrong NIC, etc.) are also retried. Do not let the thread end silently
                if not factory_ready:
                    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
                    from unitree_sdk2py.go2.video.video_client import VideoClient
                    ChannelFactoryInitialize(0, self.interface)
                    factory_ready = True
                client = VideoClient()
                client.SetTimeout(3.0)
                client.Init()
                while True:
                    code, data = client.GetImageSample()
                    if code == 0 and data:
                        with self._lock:
                            self._jpeg, self._seq = bytes(data), self._seq + 1
                        continue
                    print("[camera] %s: GetImageSample failed code=%s" % (self.name, code), flush=True)
                    with self._lock:
                        self._jpeg = None
                    time.sleep(self.ERROR_WAIT_S)
            except Exception as exc:
                print("[camera] %s: cannot use VideoClient (%s: %s)" % (self.name, type(exc).__name__, exc), flush=True)
            with self._lock:
                self._jpeg = None
            time.sleep(REOPEN_WAIT_S)


def make_grabber(name: str, device: str):
    """If device is videoclient:<NIC>, the official path; otherwise a V4L2 device."""
    if device.startswith("videoclient:"):
        return VideoClientGrabber(name, device.split(":", 1)[1])
    if device.startswith("depth:"):
        return DepthGrabber(name, device)
    return Grabber(name, device)


def make_handler(grabbers):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            grabber = grabbers.get(self.path.strip("/"))
            if grabber is None:
                self.send_error(404, "unknown camera")
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=" + BOUNDARY)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    seq, jpeg = grabber.latest()
                    if jpeg is None or seq == last:
                        time.sleep(1.0 / (FPS * 2))
                        continue
                    last = seq
                    self.wfile.write(("--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                                      % (BOUNDARY, len(jpeg))).encode() + jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # the viewer just closed the connection

        def log_message(self, fmt, *args):
            pass

    return Handler


def list_devices():
    base = "/dev/v4l/by-id"
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        print("%s -> %s" % (name, os.path.realpath(os.path.join(base, name))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--camera", action="append", default=[], metavar="NAME=DEVICE")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--bind", default="0.0.0.0", help="Address to listen on (127.0.0.1 if the console runs on the same machine)")
    args = parser.parse_args()
    if args.list:
        return list_devices()
    grabbers = {}
    for spec in args.camera:
        name, _, device = spec.partition("=")
        if not name or not device:
            parser.error("--camera must be given as NAME=DEVICE: %r" % spec)
        grabbers[name] = make_grabber(name, device)
    if not grabbers:
        parser.error("Specify at least one --camera (use --list to see candidates)")
    for grabber in grabbers.values():
        grabber.start()
    print("[camera] serving on %s:%d: %s" % (args.bind, args.port, ", ".join(grabbers)), flush=True)
    ThreadingHTTPServer((args.bind, args.port), make_handler(grabbers)).serve_forever()


if __name__ == "__main__":
    main()
