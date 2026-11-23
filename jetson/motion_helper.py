# Motion-only helper that runs on the Jetson (Python 3.8). Started as a child process by HelperSender in g1console/motion.py.
# The only operations allowed are move / stop / task. It has no commands for mode switching or posture changes (mode switching is on the remote_helper side).
# Reads one line of JSON from stdin and returns one line of JSON on stdout. On EOF it sends a stop command and exits.
# __LIMITS__ and __TASKS__ are substituted by HelperSender (clamped twice, with the same limits as the hub side).
import json
import math
import sys

# The SDK prints to stdout on failure. Keep the original stdout for replies only, so replies do not get corrupted.
_reply = sys.stdout
sys.stdout = sys.stderr

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

LIMITS = __LIMITS__
TASKS = set(__TASKS__)
MAX_DURATION_S = 0.5  # the hub sends 0.2. Commands longer than this are not accepted (so it does not keep walking in a runaway)
RPC_TIMEOUT_S = 0.8


def reply(obj):
    print(json.dumps(obj), file=_reply, flush=True)


def code_of(result):
    """The SDK's return is a bare code or (code, data) depending on the version."""
    return result[0] if isinstance(result, tuple) else result


def clamp(key, value):
    lo, hi = LIMITS[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(key)
    return min(max(float(value), lo), hi)


ChannelFactoryInitialize(0, "eth0")
loco = LocoClient()
loco.SetTimeout(RPC_TIMEOUT_S)
loco.Init()
reply({"ready": True})


def handle(req):
    op = req.get("op")
    if op == "move":
        duration = min(max(float(req["duration"]), 0.05), MAX_DURATION_S)
        return {"ok": True, "code": code_of(loco.SetVelocity(
            clamp("vx", req["vx"]), clamp("vy", req["vy"]), clamp("wz", req["wz"]), duration))}
    if op == "stop":
        return {"ok": True, "code": code_of(loco.StopMove())}
    if op == "task":
        if req.get("id") not in TASKS:
            raise ValueError("task")
        return {"ok": True, "code": code_of(loco.SetTaskId(int(req["id"])))}
    raise ValueError("op")


for line in sys.stdin:
    try:
        reply(handle(json.loads(line)))
    except Exception as exc:  # do not stop for one bad request. Return only the reason
        reply({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})

try:  # the parent is gone (EOF). Always stop at the end
    loco.StopMove()
except Exception:
    pass
