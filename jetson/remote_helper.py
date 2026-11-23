# Helper that runs on the Jetson (Python 3.8). server.py starts it over ssh.
# Reads one line of JSON {"op":"status"} / {"op":"set","id":N} from stdin and returns one line of JSON on stdout.
# __ALLOWED__ is replaced by server.py with the list of allowed IDs.
import glob
import json
import os
import sys

# The SDK prints to stdout on failure ("[ClientStub] send request error" in debug mode).
# To keep the JSON reply from being corrupted, keep the original stdout for replies only and divert the SDK's output to stderr.
_reply = sys.stdout
sys.stdout = sys.stderr


def reply(obj):
    print(json.dumps(obj), file=_reply, flush=True)


import time

from cyclonedds.core import DDSException
from cyclonedds.domain import DomainParticipant
from cyclonedds.internal import InvalidSample
from cyclonedds.qos import Policy, Qos
from cyclonedds.sub import DataReader
from cyclonedds.topic import Topic
from cyclonedds.util import duration
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_
from unitree_sdk2py.idl.unitree_go.msg.dds_ import Error_, SportModeState_, WirelessController_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_, IMUState_, LowCmd_, LowState_, MainBoardState_
from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

ALLOWED = set(__ALLOWED__)
ALLOWED_SPEED = set(__ALLOWED_SPEED__)

ChannelFactoryInitialize(0, "eth0")
msc = MotionSwitcherClient()
msc.SetTimeout(2.0)
msc.Init()
loco = LocoClient()
loco.SetTimeout(2.0)
loco.Init()
audio = AudioClient()
audio.SetTimeout(3.0)
audio.Init()

# Read-only telemetry. The callback only keeps the latest message (lowstate is high frequency).
N_JOINTS = 29  # G1 29DoF. LowState's motor_state has 35 slots, but the first 29 are the joints
# Subscriptions do not use callbacks. lowstate and others arrive at hundreds of messages per second, and reading all of them in Python callbacks
# starves the process of CPU and drops RPC replies such as audio (3104 timeout); this was measured.
# So the DDS side thins them to one per 0.2 s, keeps only the latest one in the history, and takes it on every state fetch.
_latest = {}   # topic name -> (fetch time, message)
_readers = {}
_participant = None  # created after ChannelFactoryInitialize (shares the same Domain settings)
_READER_QOS = Qos(Policy.History.KeepLast(1), Policy.TimeBasedFilter(duration(milliseconds=200)))


def _watch(topic, msg_type):
    global _participant
    if _participant is None:
        _participant = DomainParticipant(0)
    _readers[topic] = DataReader(_participant, Topic(_participant, topic, msg_type), _READER_QOS)


def _refresh():
    """Take in the latest message of each topic. If nothing new arrived, keep the previous value and fetch time."""
    now = time.time()
    for topic, reader in _readers.items():
        try:
            samples = reader.take(N=1)
        except DDSException:
            continue
        for sample in samples:
            if not isinstance(sample, InvalidSample):
                _latest[topic] = (now, sample)


BINARY_TOPICS = [
    ("rt/lf/bmsstate", BmsState_), ("rt/lowstate", LowState_), ("rt/odommodestate", SportModeState_),
    ("rt/lowcmd", LowCmd_), ("rt/secondary_imu", IMUState_), ("rt/lf/mainboardstate", MainBoardState_),
    ("rt/lf/emergency_stop", Error_), ("rt/wirelesscontroller", WirelessController_),
]
# Topics that carry JSON strings (service state, communication state, etc.)
STRING_TOPICS = ["rt/rtc/state", "rt/public_network_status", "rt/arm/action/state", "rt/gpt_state",
                 "rt/servicestate", "rt/servicestateactivate", "rt/lf/battery_alarm", "rt/rtc_status",
                 "rt/multiplestate", "rt/selftest"]
for _t, _ty in BINARY_TOPICS:
    _watch(_t, _ty)
for _t in STRING_TOPICS:
    _watch(_t, String_)
reply({"ready": True})


def _get(topic):
    got = _latest.get(topic)
    return (got[1], round(time.time() - got[0], 2)) if got else (None, None)


def _plain(msg):
    """Turn a simple IDL message into a dict that can be JSON (lists are cut to the first 12 elements)."""
    out = {}
    for a in dir(msg):
        if a.startswith("_") or a in ("serialize", "deserialize", "sample_info"):
            continue
        v = getattr(msg, a)
        if callable(v):
            continue
        out[a] = list(v)[:12] if hasattr(v, "__len__") and not isinstance(v, str) else v
    return out


def _system():
    """State of the Jetson itself (only read from /proc and /sys)."""
    out = {}
    try:
        out["load"] = [float(x) for x in open("/proc/loadavg").read().split()[:3]]
        mem = dict(l.split(":") for l in open("/proc/meminfo").read().splitlines())
        kb = lambda k: int(mem[k].split()[0])
        out["mem_total_mb"], out["mem_avail_mb"] = kb("MemTotal") // 1024, kb("MemAvailable") // 1024
        out["uptime_s"] = float(open("/proc/uptime").read().split()[0])
        out["cpus"] = os.cpu_count()
        temps = {}
        for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            temps[open(z + "/type").read().strip()] = int(open(z + "/temp").read()) / 1000.0
        out["temps"] = temps
        st = os.statvfs("/")
        out["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def telemetry():
    _refresh()
    now = time.time()
    # seconds since the last reception of each topic (None means never received)
    out = {"ages": {t: round(now - _latest[t][0], 2) if t in _latest else None for t in _readers}}
    bms, age = _get("rt/lf/bmsstate")
    out["battery"] = None if bms is None else {
        "soc": bms.soc, "current": bms.current, "voltage": list(bms.bmsvoltage),
        "temperature": list(bms.temperature), "age_s": age}
    low, age = _get("rt/lowstate")
    if low is None:
        out["imu"], out["joints"] = None, None
    else:
        imu = low.imu_state
        out["imu"] = {"rpy": list(imu.rpy), "gyro": list(imu.gyroscope), "accel": list(imu.accelerometer),
                      "temperature": imu.temperature, "age_s": age}
        out["joints"] = {"age_s": age, "mode_machine": low.mode_machine, "items": [
            {"q": m.q, "dq": m.dq, "tau": m.tau_est, "temperature": list(m.temperature), "lost": m.motorstate,
             "mode": m.mode}
            for m in low.motor_state[:N_JOINTS]]}
    odom, age = _get("rt/odommodestate")
    out["odom"] = None if odom is None else {
        "position": list(odom.position), "velocity": list(odom.velocity), "yaw_speed": odom.yaw_speed,
        "mode": odom.mode, "gait_type": odom.gait_type, "body_height": odom.body_height,
        "error_code": odom.error_code, "age_s": age}
    cmd, age = _get("rt/lowcmd")
    out["lowcmd"] = None if cmd is None else {"age_s": age, "mode_machine": cmd.mode_machine, "items": [
        {"q": m.q, "dq": m.dq, "tau": m.tau, "kp": m.kp, "kd": m.kd, "mode": m.mode}
        for m in cmd.motor_cmd[:N_JOINTS]]}
    imu2, age = _get("rt/secondary_imu")
    out["imu2"] = None if imu2 is None else {"rpy": list(imu2.rpy), "gyro": list(imu2.gyroscope),
                                             "accel": list(imu2.accelerometer), "age_s": age}
    for key, topic in (("mainboard", "rt/lf/mainboardstate"), ("estop", "rt/lf/emergency_stop"),
                       ("remote", "rt/wirelesscontroller")):
        msg, age = _get(topic)
        out[key] = None if msg is None else {**_plain(msg), "age_s": age}
    strings = {}
    for topic in STRING_TOPICS:
        msg, age = _get(topic)
        if msg is not None:
            try:
                val = json.loads(msg.data)
            except ValueError:
                val = msg.data
            strings[topic] = {"value": val, "age_s": age}
    out["strings"] = strings
    out["system"] = _system()
    return out


def status():
    code, mode = msc.CheckMode()
    name = (mode or {}).get("name", "") if code == 0 else None
    fsm_code, fsm_id = loco.GetFsmId()
    return {"ok": True, "checkmode_code": code, "service": name,
            "fsm_code": fsm_code, "fsm_id": fsm_id if fsm_code == 0 else None,
            "telemetry": telemetry()}


def audio_op(req):
    """Audio and LED. Independent of the motion service (works in debug mode too). Value ranges are validated in server.py."""
    op = req["op"]
    if op == "audio_get":
        code, data = audio.GetVolume()
        return {"ok": True, "code": code, "volume": (data or {}).get("volume")}
    if op == "audio_volume":
        set_code = audio.SetVolume(int(req["volume"]))
        read_code, data = audio.GetVolume()  # read back to confirm it took effect
        return {"ok": True, "set_code": set_code, "read_code": read_code,
                "volume_after": (data or {}).get("volume")}
    if op == "audio_led":
        return {"ok": True, "code": audio.LedControl(int(req["r"]), int(req["g"]), int(req["b"]))}
    if op == "audio_tts":
        return {"ok": True, "code": audio.TtsMaker(str(req["text"]), int(req["speaker_id"]))}
    return {"ok": False, "error": "unknown audio op"}


for line in sys.stdin:
    try:
        req = json.loads(line)
        if req["op"] == "status":
            res = status()
        elif req["op"] == "set":
            fsm_id = int(req["id"])
            if fsm_id not in ALLOWED:
                res = {"ok": False, "error": "FSM ID not allowed: %d" % fsm_id}
            else:
                res = {"ok": True, "set_code": loco.SetFsmId(fsm_id)}
        elif req["op"] == "speed":
            value = int(req["value"])
            if value not in ALLOWED_SPEED:
                res = {"ok": False, "error": "Speed mode not allowed: %d" % value}
            else:
                res = {"ok": True, "set_code": loco.SetSpeedMode(value)}
        elif req["op"].startswith("audio_"):
            res = audio_op(req)
        else:
            res = {"ok": False, "error": "unknown op"}
    except Exception as exc:  # one failed request must not bring down the whole helper
        res = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    reply(res)
