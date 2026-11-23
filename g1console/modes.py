"""G1 FSM ID definitions (shared by the operator-PC-side server and the Jetson-side helper).

Sources: g1_loco_client.py in unitree_sdk2_python (0/1/3/500/702/706), and
Unitree official manual-style documents (501 = regular mode of the 3-DOF waist variant).
GetFsmId returned 501 on the real robot: once from a separate script, and once via the console on 2026-10-18
(after switching to regular mode with the remote controller).
"""

# Display labels (GetFsmId value -> name)
FSM_LABELS = {
    0: "Zero Torque",
    1: "Damping",
    3: "Seated Mode",
    4: "Locked Standing",  # Seen as 4 right after entering with the remote controller on 2026-10-18. Reproduced via the remote controller on 2026-10-24 as well
    500: "Regular Mode (1-axis waist)",
    501: "Regular Mode (3-axis waist)",
    702: "Lie -> Stand",
    706: "Squat <-> Stand",
    # 2026-10-24: entered with remote controller R1+R2+X (key value 1041) and returned to Damping after about 1 second. The robot announced "robot rising" and "damp mode".
    # The name is inferred from "Adapt rise" in a table of a third-party document (a reseller's operation guide). User report: behaves like Lie -> Stand, used with the robot lying on its back.
    # The robot was hanging from a gantry, so actual rising has not been observed. No button is provided
    1001: "Adapt rise",
    # 2026-10-24: after running Lie -> Stand from Damping, the FSM ID was 802 (service ai, legs autonomous). Meaning unverified.
    # One document says "since ai_sport 8.6.x.x, Run changed from 801 to 802", but this is unverified on the real robot. Shown as the bare number
    802: "FSM ID 802",
}

# Mode switch buttons (shown in this order). danger=True warns when pressed while walking.
# Mode names are kept in the official English wording (not translated).
# "Running Mode (801)" and "debug mode" are not included because their ID / procedure is unverified.
BUTTONS = [
    {"id": 1, "label": "Damping", "danger": True},
    {"id": 0, "label": "Zero Torque", "danger": True},
    {"id": 4, "label": "Locked Standing", "danger": False},  # ID confirmed via the remote controller. Sending from the console is unverified
    {"id": 3, "label": "Seated Mode", "danger": False},
    {"id": 706, "label": "Squat <-> Stand", "danger": False},
    {"id": 702, "label": "Lie -> Stand", "danger": False},
    {"id": 501, "label": "Regular Mode", "danger": False},
]

ALLOWED_IDS = frozenset(b["id"] for b in BUTTONS)

# Speed mode (LocoClient.SetSpeedMode). No documentation says which value is slower, so this is unverified.
# Neutral names are shown until a test settles it; once confirmed, only the label needs to change. There is no way to read the value back.
SPEED_BUTTONS = [
    {"value": 0, "label": "Speed 0 (test)"},
    {"value": 1, "label": "Speed 1 (test)"},
]
SPEED_VALUES = frozenset(b["value"] for b in SPEED_BUTTONS)
SPEED_FSM_IDS = (500, 501)  # Can be pressed only while walking (Regular Mode)

# Current FSM -> buttons that can be pressed on screen. Follows the official state transition diagram (provided by the user on 2026-10-24).
# Zero Torque is reachable only from Damping, and Zero Torque goes only to Damping. Other modes are normally entered from Damping.
# For emergencies, Damping can be pressed from any state. Transitions not in the diagram are not listed.
# 706 does not work when sent from Damping (real robot). It works when sent from Regular Mode (2026-10-24; read from the POST count, the on-screen transition display is unverified).
# The FSM ID of "Squat" (L1+DOWN) in the diagram is unverified, so there is no button. For a current value not listed here, only Damping can be pressed.
TRANSITIONS = {
    0: (1,),
    1: (0, 4, 3, 702, 706),  # 706: on 2026-10-24 the console sent it from Damping and the FSM became 706 after 1.7 s and 802 after 7.6 s (set_code 0). An earlier test the same day did not work. Cause not identified

    4: (1, 3, 501),
    3: (1, 4),
    501: (1, 3, 706),  # 2026-10-24: confirmed Damping -> 4 -> 501 -> 706 on the console (706 automatically returns to Damping at the end)
    500: (1, 3, 706),
    706: (1, 501),
    702: (1, 501),
    # 802: after Damping -> Lie -> Stand on 2026-10-24. Sending 706 from 802 switched in 1.0 s and automatically went to Damping after 8.2 s (real robot). 501 is a test (unverified)
    802: (1, 501, 706),
}
FALLBACK_TRANSITION = (1,)

# Mode switches that are not implemented yet (shown disabled as "not implemented" on screen). For the reasons, see docs/REMOTE_CONTROLLER.md.
PLANNED_MODES = [
    {"label": "Running Mode", "note": "FSM ID unverified (801 appears in only one document)"},
    {"label": "Debug mode", "note": "Switching procedure unverified"},
]

# Actions (equivalent to remote controller SELECT+Y/A/X). Run with LocoClient.SetTaskId. task_id and the effects are unverified on the real robot.
# A handshake has two stages: start (2) and end (3). Both are listed so the end can be sent.
ACTIONS = [
    {"id": "wave", "label": "Wave", "task_id": 0},
    {"id": "wave_turn", "label": "Turn around and wave", "task_id": 1},
    {"id": "shake_start", "label": "Handshake (start)", "task_id": 2},
    {"id": "shake_end", "label": "Handshake (end)", "task_id": 3},
]
PLANNED_ACTIONS = []  # There are no unimplemented actions now (the API shape is kept)

# Status of the basic features. Keep it consistent with the table in REMOTE_CONTROLLER.md.
# implemented: implemented or not / verified: tried on the real robot (G1 powered on, via the console)
FEATURES = [
    {"id": "connection", "label": "Connection status display", "implemented": True, "verified": False},
    {"id": "reconnect", "label": "Automatic reconnection", "implemented": True, "verified": False},
    {"id": "mode", "label": "Mode change", "implemented": True, "verified": False,
     "note": "Only Damping / Zero Torque / Seated Mode / Squat <-> Stand / Lie -> Stand / Regular Mode. Zero Torque -> Damping was confirmed on the real robot via the console on 2026-10-24 (1.1 s). Other transitions are unverified"},
    {"id": "speed", "label": "Speed mode (Speed 0 / Speed 1)", "implemented": True, "verified": False,
     "note": "The meaning of the SetSpeedMode values (slow / fast) is undocumented and unverified. The 2026-10-24 test was aborted because pressing the button had no effect (no send recorded in the server log). There is no way to read the value back"},
    {"id": "action", "label": "Run action", "implemented": True, "verified": False,
     "note": "Wave and handshake. The SetTaskId numbers and effects are unverified on the real robot. Only with --local"},
    {"id": "move", "label": "Move (joystick / arrow keys)", "implemented": True, "verified": True,
     "note": "Only with --local. On 2026-10-24 the operator reported successful movement on the real robot (Regular Mode; one report, not independently recorded). Stops 0.5 s after the link is lost. The speed limits are unverified"},
    {"id": "tasks", "label": "Run tasks (start / stop predefined commands, logs)", "implemented": True, "verified": False,
     "note": "Runs only the argv from tasks/*.json. Confirmed in tests on a Mac; execution on the Jetson is unverified"},
    {"id": "camera", "label": "Camera video display, and start / stop of the stream", "implemented": True, "verified": False,
     "note": "Start / stop only with --local. Start / stop on the Jetson is unverified"},
    {"id": "lidar", "label": "LiDAR point cloud display, and start / stop of the stream", "implemented": True, "verified": False,
     "note": "Start / stop only with --local. Start / stop on the Jetson is unverified"},
    {"id": "lidar_sensor", "label": "LiDAR unit stop (standby) / start (measuring)", "implemented": True, "verified": False,
     "note": "Only with --local. Switches work_tgt_mode to IDLE / SAMPLING on the LiDAR (192.168.123.120) from the Jetson via Livox control. No point cloud arrives during standby, so anything that uses the point cloud (such as mapping) does not work. Power cycling returns it to measuring. Operation via the hub is unverified (direct sending from the Jetson was confirmed on 2026-10-24)"},
    {"id": "hubstop", "label": "Stop the hub (this console)", "implemented": True, "verified": False,
     "note": "Button on the Settings tab. Once stopped it cannot be restarted from the screen (restart it on the Jetson). It refuses to stop while a task is running or an operator lock is held. Unverified on the real robot (including under systemd)"},
    {"id": "topics", "label": "Topic communication (subscribing is free, publishing only to an allowlist)", "implemented": True, "verified": False,
     "note": "Only with --local. Motion, joint, arm and RPC topics are always refused for publishing. The allowlist is --topics-file (empty by default). Unverified with the Jetson's DDS"},
    {"id": "battery", "label": "Battery display", "implemented": True, "verified": True,
     "note": "rt/lf/bmsstate. A user reported confirming it on the real robot on 2026-10-18 (the compared values were not recorded)"},
    {"id": "audio", "label": "Audio and LED (volume, head LED, text-to-speech)", "implemented": True, "verified": False,
     "note": "Volume read, LED and text-to-speech were sent on the real robot (debug mode). The LED cannot be read back and is checked by eye; text-to-speech start / end can be observed from play_state on rt/audio_msg. User confirmation is not complete"},
    {"id": "telemetry", "label": "Display of attitude (IMU), odometry, Jetson, main board, and remote controller / emergency stop / service", "implemented": True,
     "verified": True, "note": "A user reported on 2026-10-18 that values are obtained on the real robot (received and displayed). The meaning and units of the main board value, and its change when remote controller buttons are pressed, are unverified"},
    {"id": "sensors", "label": "Debug info display (joints, commands, DDS reception status)", "implemented": True,
     "verified": False, "note": "LiDAR and camera are excluded. The joint name mapping and the meaning of the main board value are unverified"},
]


# Audio and LED (writes unrelated to motion). Out-of-range values are rejected before reaching the helper.
TTS_MAX_CHARS = 100
TTS_SPEAKERS = (0, 1)  # 0=Chinese, 1=English. Verified on the real robot: speaker 1 plays sound, speaker 0 was silent (2026-10-01)


def validate_audio(kind: str, body: dict) -> dict:
    """Validate the POST body and return the request to pass to the helper. Raises ValueError if invalid."""
    def integer(key, lo, hi):
        v = body[key]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError("%s must be an integer from %d to %d" % (key, lo, hi))
        return v
    try:
        if kind == "volume":
            return {"op": "audio_volume", "volume": integer("volume", 0, 100)}
        if kind == "led":
            return {"op": "audio_led", "r": integer("r", 0, 255), "g": integer("g", 0, 255), "b": integer("b", 0, 255)}
        if kind == "tts":
            text = body["text"]
            if not isinstance(text, str) or not text.strip() or len(text) > TTS_MAX_CHARS:
                raise ValueError("text must be 1 to %d characters" % TTS_MAX_CHARS)
            speaker = integer("speaker_id", min(TTS_SPEAKERS), max(TTS_SPEAKERS))
            return {"op": "audio_tts", "text": text, "speaker_id": speaker}
    except KeyError as exc:
        raise ValueError("%s is missing" % exc.args[0])
    raise ValueError("unknown audio kind")


# Joint names follow the SDK order (12 legs, 3 waist, 14 arms). Matching against the real robot is unverified.
JOINT_NAMES = [
    "left hip pitch", "left hip roll", "left hip yaw", "left knee", "left ankle pitch", "left ankle roll",
    "right hip pitch", "right hip roll", "right hip yaw", "right knee", "right ankle pitch", "right ankle roll",
    "waist yaw", "waist roll", "waist pitch",
    "left shoulder pitch", "left shoulder roll", "left shoulder yaw", "left elbow", "left wrist roll", "left wrist pitch", "left wrist yaw",
    "right shoulder pitch", "right shoulder roll", "right shoulder yaw", "right elbow", "right wrist roll", "right wrist pitch", "right wrist yaw",
]

# Tab name = URL hash = API name. AI agents can also map the screen to the API by this name.
TABS = ("ops", "motion", "action", "state", "joints", "audio", "tasks", "camera", "dds", "settings")
