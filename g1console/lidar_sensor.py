"""Switch the LiDAR unit (Livox MID360) between standby and measuring. Not the same thing as the "point cloud stream process" in lidar_proc.py.

From the Jetson (--local), sends the Livox control protocol directly to the LiDAR (default 192.168.123.120:56100/UDP).
Setting work_tgt_mode (key 0x001A) to IDLE(2) stops the laser, and SAMPLING(1) returns to measuring. Power cycling returns it to SAMPLING.
It goes directly to the LiDAR, not via PC1, so it does not touch the G1's DDS or motors.
Source: Livox MID-360 protocol document (return code 0x03 = value out of range. Settable values are 1 SAMPLING / 2 IDLE / 9 READY).
An independent implementation for interoperability based on the protocol document published by Livox (it contains no Livox SDK or code).
Note: with IDLE the point cloud stops. Processing that uses the point cloud (map building etc.) will stop working.
"""
import socket
import struct
import threading
import time
import zlib

LIDAR_ADDR = ("192.168.123.120", 56100)
KEY_WORK_MODE = 0x001A
CMD_SET, CMD_GET = 0x0100, 0x0101
SAMPLING, IDLE = 1, 2
MODE_NAMES = {1: "Measuring (SAMPLING)", 2: "Standby (IDLE, laser stopped)", 9: "Preparing (READY)"}
ACTIONS = {"idle": IDLE, "sampling": SAMPLING}
HEADER_LEN = 24
REPLY_WAIT_S = 0.8
SETTLE_S = 1.0
RETRIES = 3
SEQ_MAX = 0xFFFFFFFF


def crc16_ccitt_false(data: bytes) -> int:
    """Verified against real LiDAR packets (init 0xFFFF, poly 0x1021, MSB first, xorout 0)."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_packet(cmd_id: int, data: bytes, seq: int) -> bytes:
    head = struct.pack("<BBHIHBB6s", 0xAA, 0, HEADER_LEN + len(data), seq, cmd_id, 0, 0, b"\0" * 6)
    return head + struct.pack("<HI", crc16_ccitt_false(head), zlib.crc32(data) & 0xFFFFFFFF) + data


def parse_reply(pkt: bytes, cmd_id: int):
    """If it is a reply to our own cmd_id, the data part (bytes). Otherwise None."""
    if len(pkt) < HEADER_LEN or pkt[0] != 0xAA or struct.unpack_from("<H", pkt, 8)[0] != cmd_id:
        return None
    return pkt[HEADER_LEN:]


class LivoxSensorCtl:
    backend = "livox"

    def __init__(self, addr=LIDAR_ADDR):
        self.addr = addr
        self.settle_s = SETTLE_S
        self._seq = 0
        self._lock = threading.Lock()  # send one at a time so rapid clicks in the UI do not mix up the replies

    def _ask(self, cmd_id: int, data: bytes):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.2)
            sock.connect(self.addr)
            for _ in range(RETRIES):
                self._seq = (self._seq + 1) & SEQ_MAX
                sock.send(build_packet(cmd_id, data, self._seq))
                end = time.time() + REPLY_WAIT_S
                while time.time() < end:
                    try:
                        reply = parse_reply(sock.recv(2048), cmd_id)
                    except socket.timeout:
                        continue
                    if reply is not None:
                        return reply
        finally:
            sock.close()
        raise RuntimeError("No response from LiDAR %s:%d" % self.addr)

    def get_mode(self) -> int:
        reply = self._ask(CMD_GET, struct.pack("<HHH", 1, 0, KEY_WORK_MODE))
        if not reply:
            raise RuntimeError("The LiDAR response is empty")
        return reply[-1]

    def set_mode(self, mode: int) -> None:
        reply = self._ask(CMD_SET, struct.pack("<HHHHB", 1, 0, KEY_WORK_MODE, 1, mode))
        if not reply or reply[0] != 0:
            raise RuntimeError("The LiDAR did not accept the setting (ret_code=%s)" % (reply[0] if reply else "none"))

    def call(self, action: str) -> dict:
        """status / idle / sampling. After setting, read back and return the actual mode."""
        if action != "status" and action not in ACTIONS:
            raise ValueError("unknown action")
        with self._lock:
            if action != "status":
                self.set_mode(ACTIONS[action])
                time.sleep(self.settle_s)  # wait for the switch to take effect, then read back
            mode = self.get_mode()
        return reply_body(mode, action)


def reply_body(mode: int, action: str) -> dict:
    return {"ok": True, "mode": mode, "label": MODE_NAMES.get(mode, "Unknown (%s)" % mode),
            "laser_off": mode == IDLE, "action": action}


class MockSensorCtl:
    """Mock without a robot."""

    backend = "mock"

    def __init__(self):
        self.mode = SAMPLING

    def call(self, action: str) -> dict:
        if action != "status" and action not in ACTIONS:
            raise ValueError("unknown action")
        if action != "status":
            self.mode = ACTIONS[action]
        return reply_body(self.mode, action)
