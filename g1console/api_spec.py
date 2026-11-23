"""Definition of the G1 Console API (single source of truth). Builds OpenAPI 3.0.3 and emits the following three from the same content.

  GET /api            OpenAPI (JSON)       GET /openapi.yaml  OpenAPI (YAML)
  docs/openapi.yaml   Same (file)          docs/API.md        Summary for people and AI agents

Regenerate docs/ with `python3 g1console/api_spec.py`. The tests verify "schema = actual response", so when you
change the API, fix this file as well (a mismatch makes the tests fail). The spec is built in Python rather than
hand-written YAML because it needs only the standard library, shares schema parts, and lets the tests use the same definition.
"""
import json

try:
    from g1console.modes import ACTIONS
except ImportError:  # when run directly as `python3 g1console/api_spec.py`
    from modes import ACTIONS

ERRORS = "HTTP 400=invalid input / 404=undefined / 500=save failed / 502=cannot reach the G1 or Jetson, or the G1 rejected it. The body is always Error."

# ---- Schema parts -------------------------------------------------------------------------------------------
def S(desc=None, **kw): return {"type": "string", **({"description": desc} if desc else {}), **kw}
def I(desc=None, **kw): return {"type": "integer", **({"description": desc} if desc else {}), **kw}
def N(desc=None, **kw): return {"type": "number", **({"description": desc} if desc else {}), **kw}
def B(desc=None): return {"type": "boolean", **({"description": desc} if desc else {})}
def A(items, desc=None): return {"type": "array", "items": items, **({"description": desc} if desc else {})}
def null(schema): return {**schema, "nullable": True}
def ref(name): return {"$ref": "#/components/schemas/" + name}
def free(desc=None): return null({"type": "object", **({"description": desc} if desc else {}), "additionalProperties": True})
def obj(props, required=(), desc=None, extra=False):
    return {"type": "object", **({"description": desc} if desc else {}), "properties": props,
            **({"required": list(required)} if required else {}), "additionalProperties": extra}


HEAD = {"jetson": ref("Link"), "g1": ref("Link"), "mode": ref("Mode"), "control": ref("Control"),
        "sampled_at": null(N("Time the G1 was last checked (epoch seconds). null=not checked yet")),
        "age_s": null(N("Seconds since the last check. A large value means a stale reading"))}
HEAD_REQ = list(HEAD)

MOTION_PROPS = {
    "state": S(enum=["idle", "active"], desc="idle=no operator / active=has an operator"), "operator": B("Whether an operator exists"),
    "moving": B("Whether the hub is currently sending velocity commands"), "target": obj({"vx": N("m/s"), "vy": N("m/s"), "wz": N("rad/s")}, ["vx", "vy", "wz"], "Current target velocity (already clamped to the limits)"),
    "blocked": null(S("Reason it will not move (not in a walking mode, state is stale, etc.). null=can move")),
    "last_rx_age_s": null(N("Seconds since the operator's last ctl. Automatically stops beyond 0.5")),
    "last_event": free("Most recent event {kind: claim/lost/estop/release/takeover/disabled/sender_error/shutdown, detail, at}. This shows whether the lock was released by a lost link"),
    "sender": obj({"backend": S("local / mock / unavailable"), "error": null(S("Most recent send failure"))}, ["backend", "error"]),
    "limits": free("[min, max] of vx / vy / wz. Initial values, unverified on the real robot"),
    "timing": obj({"send_period_s": N(), "duration_s": N("Validity time of SetVelocity"), "liveness_s": N("Stops if ctl is lost for this many seconds")}),
}
MOTION_REQ = ["state", "operator", "moving", "target", "blocked", "sender"]

TASK_PROPS = {
    "name": S("Task name (tasks/<name>.json)"), "title": S(), "description": S(),
    "argv": A(S(), "The command that is run (array. Does not go through a shell)"), "group": null(S("Exclusive group. Tasks in the same group are never run at the same time")),
    "timeout_s": N("SIGTERM after this many seconds"),
    "verified": B("false=unverified on the real robot (Jetson and G1). The UI shows a caution dialog before run / stop. Do not assert results"),
    "caution": A(S(), "Caution text the UI shows before run / stop (defined on the server side)"),
    "state": S(enum=["idle", "running", "stopping"]),
    "result": null(S("Result of the most recent run. ok / failed / stopped / timeout")), "exit_code": null(I("Exit code. Negative means a signal")),
    "started_at": null(N("epoch seconds")), "ended_at": null(N("epoch seconds. null=running or never run")),
}
TASK_REQ = ["name", "title", "description", "argv", "group", "timeout_s", "verified", "caution", "state", "result", "exit_code", "started_at", "ended_at"]

SCHEMAS = {
    "Error": obj({"error": S("Plain-language reason")}, ["error"], "Error body (common to all endpoints). A 502 where the G1 / Jetson cannot be reached also carries raw details such as ok=false, offline and ssh_exit", extra=True),
    "Link": obj({"state": S(enum=["ok", "down", "unknown", "checking"], desc="ok=reachable / down=unreachable / unknown=not visible because an upstream link is down"),
                 "detail": S("Reason (same as the diagnostic text on screen)")}, ["state", "detail"], "State of one connection hop. If jetson is down, g1 is unknown"),
    "Mode": obj({"state": S(enum=["ok", "debug", "unknown", "none"], desc="ok=regular mode and the FSM ID was obtained / debug=debug mode / unknown=not obtainable / none=not connected"),
                 "label": S("Display name"), "fsm_id": I("FSM ID (only when state=ok)"), "service": S("Motion service name"), "detail": S()},
                ["state", "label"], "Current mode"),
    "Control": obj({"arm": obj({"state": S(enum=["enabled", "disabled", "partial", "unknown"],
                                           desc="enabled=all 14 arm axes have motors enabled / disabled=all disabled (zero torque) / partial=only some / unknown=lowstate is stale or has no mode"),
                                "label": S("Short verdict shown large on screen (Enabled / Disabled / Partial / Unknown)"), "detail": S("Reason for the verdict (shown small on screen)"),
                                "enabled_count": null(I("Number of arm joints whose motor_state.mode in rt/lowstate is 1")),
                                "total": I("Number of arm joints (14)"), "commanded": null(B("Whether rt/lowcmd arrived within the last second"))},
                               ["state", "label", "detail", "total"], "Whether arm control is enabled. Judged by the mode in the state side (lowstate), not the command side (lowcmd)"),
                    "legs": obj({"state": S(enum=["autonomous", "not_autonomous", "unknown"],
                                            desc="autonomous=the motion controller is controlling the legs / not_autonomous=zero torque, damping or debug mode"),
                                 "label": S("Short verdict shown large on screen (Autonomous / Not autonomous / Unknown)"), "detail": S("Reason for the verdict (shown small on screen)"),
                                 "fsm_id": null(I("Only in a mode with state=ok")),
                                 "enabled_count": null(I("Number of the 12 leg joint axes whose motor_state.mode is 1")), "total": I("Number of leg joints (12)")},
                                ["state", "label", "detail", "total"], "Whether the legs are autonomous (under the standard motion service)")},
                   ["arm", "legs"], "Whether arm control is enabled and whether the legs are autonomous (computed from reads only)"),
    "Status": obj({**HEAD, "latency_ms": null(I("Round trip to the G1 in ms")), "last_g1_ok_at": null(N()),
                   "last_mode": free("Last mode that could be confirmed (reference while disconnected. Not the current value)"),
                   "paused": B("true=automatic checks and reconnection are stopped (values are not updated)"), "poll_interval_s": N(),
                   "server": obj({"backend": S("Display of the connection target"), "mock": B()}, ["backend", "mock"]),
                   "telemetry": free("Raw telemetry from the helper (shaped by /api/state and /api/joints)")},
                  HEAD_REQ + ["paused", "server"], "Connection, mode and freshness. Read this first"),
    "State": obj({**HEAD, "battery": free("soc[%], voltage, current, temperature (units are assumed. See notes)"), "imu": free("rpy[rad], gyro, accel, temperature"),
                  "imu2": free(), "odom": free("Estimated from the start position. Drifts"), "mainboard": free("Meaning of value is unverified (raw values)"),
                  "system": free("Jetson temperature, load, etc."), "remote": free("Remote controller input. null if nothing received"), "estop": free("Emergency stop. null if nothing received"),
                  "strings": free(), "ages": free("Seconds since the last reception per topic"),
                  "notes": obj({"units_assumed": A(S()), "unverified": A(S())}, desc="Items whose units are assumed or whose meaning is unverified")},
                 HEAD_REQ + ["notes"], "State tab. A null value means not received or not connected"),
    "Joints": obj({**HEAD, "mode_machine": null(I()), "age_s_joints": null(N()),
                   "items": A(obj({"index": I(), "name": S("Name by SDK order (unverified on the real robot)"), "q": N("Angle in rad"), "dq": N("Velocity in rad/s"),
                                   "tau": N("Estimated torque"), "temperature": A(N()), "mode": I("motor_state.mode in rt/lowstate (1=enabled / 0=zero torque). Absent with an old helper"),
                                   "cmd": null(free("Command values from lowcmd. Only the last command that flowed remains; this is not the current enabled state"))},
                                  ["index", "name"], extra=True), "29 joint axes (empty if not connected)"),
                   "notes": obj({"unverified": A(S())})}, HEAD_REQ + ["items"], "Joints tab"),
    "Snapshot": obj({**HEAD, "tabs": A(S(), "List of tab names (= URL hash = API name)"), "state": ref("State"), "joints": ref("Joints")},
                    HEAD_REQ + ["tabs", "state", "joints"], "state and joints combined"),
    "Volume": obj({"ok": B(), "code": I("0=accepted by the G1"), "volume": I("0 to 100", minimum=0, maximum=100)}, ["ok", "code", "volume"], extra=True),
    "VolumeSet": obj({"ok": B(), "set_code": I(), "read_code": I(), "volume_after": I("Value read back. If it equals the requested value, it has taken effect")},
                     ["ok", "set_code", "read_code", "volume_after"], extra=True),
    "Ack": obj({"ok": B(), "code": I("0=accepted by the G1 (confirm the effect by eye or ear)")}, ["ok", "code"], extra=True),
    "ModeAck": obj({"ok": B(), "set_code": I("0=accepted by the G1. This does not mean it was reached")}, ["ok", "set_code"], extra=True),
    "Cameras": obj({"enabled": B("Whether the stream source (camera_stream.py on the Jetson) is configured"), "cameras": {"type": "object", "additionalProperties": S(), "description": "name -> display name"}},
                   ["enabled", "cameras"]),
    "Dds": obj({"topics": A(obj({"topic": S(), "type": S(), "status": S(enum=["displayed", "todo", "excluded"], desc="displayed / not subscribed (not implemented) / excluded"), "note": S()},
                                ["topic", "type", "status", "note"])),
                "services": A(obj({"name": S(), "status": S(), "note": S()}, ["name", "status", "note"]))}, ["topics", "services"]),
    "Buttons": obj({"buttons": A(obj({"id": I("id for POST /api/mode"), "label": S(), "danger": B()}, ["id", "label", "danger"])),
                    "transitions": free("Current FSM ID (as a string) -> ids of the buttons that can be pressed on screen. Follows the official state transition diagram"),
                    "fallback": A(I(), "Ids of the buttons that can be pressed when the current value is not in transitions"),
                    "speed": A(obj({"value": I("value for POST /api/speed"), "label": S()}, ["value", "label"])),
                    "speed_fsm_ids": A(I(), "Current FSM IDs from which a speed mode can be sent (only while walking)")},
                   ["buttons", "transitions", "fallback", "speed", "speed_fsm_ids"]),
    "SpeedPatch": obj({"value": I("Only a value listed in speed of GET /api/buttons")}, ["value"]),
    "Features": obj({"actions": A(obj({"id": S(), "label": S(), "task_id": I()}, ["id", "label", "task_id"]), "Actions that can be run"),
                     "features": A(obj({"id": S(), "label": S(), "implemented": B(), "verified": B("false=unverified on the real robot. Do not assert results"), "note": S()},
                                       ["id", "label", "implemented", "verified"])),
                     "planned_modes": A({"type": "object", "additionalProperties": True}), "planned_actions": A({"type": "object", "additionalProperties": True})},
                    ["features"]),
    "SettingsValues": obj({"dev_pc": S("IP of the development PC (display and record only)"), "jetson_host": S("IP or hostname of the Jetson (target for ssh and the camera)"),
                           "jetson_user": S("If empty, leaves it to ~/.ssh/config"), "jetson_key": S("Path of the ssh private key. Default if empty"),
                           "g1_ip": S("IP of the G1 itself (display and record only)"), "camera_port": I(minimum=1, maximum=65535),
                           "lidar_port": I(minimum=1, maximum=65535)},
                          ["dev_pc", "jetson_host", "jetson_user", "jetson_key", "g1_ip", "camera_port", "lidar_port"]),
    "SettingsPatch": obj({"dev_pc": S("IP address or hostname. An empty string means unset"), "jetson_host": S(), "jetson_user": S(), "jetson_key": S(),
                          "g1_ip": S(), "camera_port": I(minimum=1, maximum=65535), "lidar_port": I(minimum=1, maximum=65535)}, desc="Only the specified items change (all optional)"),
    "Settings": obj({"settings": ref("SettingsValues"), "labels": {"type": "object", "additionalProperties": S()}}, ["settings", "labels"]),
    "MonitorPatch": obj({"paused": B("true=stop / false=resume"), "check": B("true=check just once")}, desc="Either one, or both"),
    "Monitor": obj({"paused": B()}, ["paused"]),
    "HubStopPatch": obj({"confirm": B("Stops only when true. 400 if absent")}, ["confirm"]),
    "HubStopAck": obj({"ok": B(), "message": S()}, ["ok", "message"]),
    "Scenarios": obj({"scenarios": {"type": "object", "additionalProperties": S()}, "current": S()}, ["scenarios", "current"]),
    "ScenarioPatch": obj({"scenario": S()}, ["scenario"]),
    "Scenario": obj({"scenario": S()}, ["scenario"]),
    "MotionStatus": obj(MOTION_PROPS, MOTION_REQ, "State of motion control", extra=True),
    "MotionClaim": obj({**MOTION_PROPS, "session": S("ID of the operator lock to attach to later ctl / release / action calls")}, MOTION_REQ + ["session"], "Result of taking the operator lock", extra=True),
    "MotionClaimPatch": obj({"takeover": B("true=take the operator lock from someone else (the other side stops)")}, desc="All optional"),
    "MotionCtlPatch": obj({"session": S(), "seq": I("Increasing number. Smaller or equal ones are discarded"), "vx": N("Forward/back m/s"), "vy": N("Left/right m/s"), "wz": N("Turn rad/s")},
                          ["session", "seq", "vx", "vy", "wz"], "Values beyond the limits are clamped by the server"),
    "MotionSessionPatch": obj({"session": S()}, ["session"]),
    "MotionActionPatch": obj({"session": S(), "name": S("id in actions of GET /api/features", enum=[a["id"] for a in ACTIONS])}, ["session", "name"]),
    "Task": obj(TASK_PROPS, TASK_REQ, "Task definition and the state of its most recent run"),
    "Tasks": obj({"tasks": A(ref("Task"))}, ["tasks"]),
    "TaskLogs": obj({"name": S(), "next": I("seq of the last line. Use as since next time"), "truncated": B("Part of what came after since was dropped from the ring buffer"),
                     "lines": A(obj({"seq": I(), "text": S()}, ["seq", "text"]))}, ["name", "next", "truncated", "lines"]),
    "TaskNamePatch": obj({"name": S("name from GET /api/tasks. Anything else (argv, paths) is not accepted")}, ["name"]),
    "Topics": obj({"enabled": B(), "backend": S("local / mock"), "deny": A(S(), "Topics that are always refused for publishing (fnmatch). Stronger than the allowlist"),
                   "supported_types": A(S(), "Types that can be read by subscribing"), "max_subscriptions": I(),
                   "publish": A(obj({"topic": S(), "type": S(), "max_bytes": I(), "min_interval_s": N(), "note": S()},
                                    ["topic", "type", "max_bytes", "min_interval_s", "note"]), "Publish allowlist (server-side file only. Cannot be extended from the UI)"),
                   "subscribed": A(S())}, ["enabled", "backend", "deny", "supported_types", "max_subscriptions", "publish", "subscribed"]),
    "TopicsReceived": obj({"items": A(obj({"topic": S(), "type": S(), "count": I("Number of messages received"), "age_s": null(N("Seconds since the last reception. null=nothing received yet")),
                                           "message": free("Latest message (arrays up to 16 elements, strings up to 512 characters)")}, ["topic", "type", "count", "age_s", "message"]))}, ["items"]),
    "TopicSubscribePatch": obj({"topic": S("A name starting with rt/"), "type": S("One of supported_types in GET /api/topics")}, ["topic", "type"]),
    "TopicNamePatch": obj({"topic": S()}, ["topic"]),
    "TopicPublishPatch": obj({"topic": S("A topic in the allowlist"), "data": S("The string to send (up to max_bytes)")}, ["topic", "data"]),
    "TopicSubscribed": obj({"topic": S(), "type": S()}, ["topic", "type"]),
    "TopicUnsubscribed": obj({"unsubscribed": S()}, ["unsubscribed"]),
    "TopicPublished": obj({"published": S(), "bytes": I()}, ["published", "bytes"]),
    "ModePatch": obj({"id": I("Only an id listed in GET /api/buttons")}, ["id"]),
    "VolumePatch": obj({"volume": I(minimum=0, maximum=100)}, ["volume"]),
    "LedPatch": obj({"r": I(minimum=0, maximum=255), "g": I(minimum=0, maximum=255), "b": I(minimum=0, maximum=255)}, ["r", "g", "b"]),
    "TtsPatch": obj({"text": S("Text to speak", minLength=1, maxLength=100), "speaker_id": I("Speaker ID (meaning unverified)", enum=[0, 1])}, ["text", "speaker_id"]),
}

TAGS = {"ops": "Ops tab (connection, mode)", "motion": "Motion tab (replacement for the physical remote controller)", "tasks": "Tasks tab (run predefined commands)", "state": "State tab", "joints": "Joints tab", "audio": "Audio tab",
        "camera": "Camera tab", "dds": "DDS tab", "settings": "Settings tab", "mock": "Only active with --mock"}

READ, SETTINGS, WRITE, MOTION = "read", "settings", "robot_write", "robot_motion"
E400, E502 = "Invalid input", "Cannot reach the G1 or Jetson, or the G1 rejected it"


def ep(method, path, op, tag, summary, effect, response, *, notes=None, request=None, example=None, errors=(),
       unverified=False, mock_only=False, ok_status="Success", content=None):
    return {"method": method, "path": path, "operationId": op, "tag": tag, "summary": summary, "effect": effect,
            "response": response, "notes": notes, "request": request, "example": example, "errors": list(errors),
            "unverified": unverified, "mock_only": mock_only, "ok_status": ok_status, "content": content}


ENDPOINTS = [
    ep("GET", "/api", "getApi", "ops", "This API definition (OpenAPI, JSON)", READ, None),
    ep("GET", "/api/status", "getStatus", "ops", "Read this first. Connection (jetson/g1), current mode, staleness of the check, and whether automatic checks are stopped", READ, "Status",
       notes="If jetson/g1 is not ok, do not trust the values beyond it. Even if ok, an age_s of several seconds or more means a stale value. Nothing is updated while paused=true."),
    ep("GET", "/api/state", "getState", "state", "Battery, IMU, odometry, main board, Jetson, remote controller, emergency stop", READ, "State",
       notes="notes.units_assumed / notes.unverified list the items whose units are assumed or whose meaning is unverified."),
    ep("GET", "/api/joints", "getJoints", "joints", "Angle, velocity, estimated torque, temperature and command values of the 29 joints", READ, "Joints"),
    ep("GET", "/api/snapshot", "getSnapshot", "ops", "Get state and joints in one call (this one call is enough to grasp the situation)", READ, "Snapshot"),
    ep("GET", "/api/audio/volume", "getVolume", "audio", "Read the speaker volume from the G1 (actually queries it via the Jetson)", READ, "Volume", errors=[(502, E502)]),
    ep("GET", "/api/motion/status", "getMotionStatus", "motion", "State of motion control (operator, target velocity, reason it cannot move, most recent event)", READ, "MotionStatus",
       notes="If last_event.kind is lost, the robot stopped and the lock was released because the link was lost. If blocked is not null, it will not move for that reason."),
    ep("GET", "/api/tasks", "getTasks", "tasks", "List of runnable tasks and the state of each one's most recent run", READ, "Tasks",
       notes="Definitions come only from tasks/*.json. Clients cannot add any."),
    ep("GET", "/api/tasks/logs", "getTaskLogs", "tasks", "Task log (line by line). Query: name and since (last seq seen)", READ, "TaskLogs",
       errors=[(400, E400 + " (since)"), (404, "Task not in the definitions")],
       notes="Passing next as the next since reads only the continuation, with no gaps or duplicates. The ring buffer holds 2000 lines; when it overflows, truncated=true."),
    ep("GET", "/api/topics", "getTopics", "dds", "Topic communication policy (always refused, publish allowlist, subscribed)", READ, "Topics",
       notes="Only with --local / --mock. Receiving is free (only types that can be read); publishing is only String_ in the allowlist. Motion, joint, arm and RPC topics are always refused."),
    ep("GET", "/api/topics/received", "getTopicsReceived", "dds", "Latest message and reception status of the subscribed topics", READ, "TopicsReceived", errors=[(502, E502)],
       notes="With 0 subscriptions it does not start the helper and returns an empty result. If age_s is null, nothing has ever been received (not necessarily an error)."),
    ep("GET", "/api/cameras","getCameras", "camera", "List of cameras and whether streaming is configured (video is GET /camera/{name})", READ, "Cameras"),
    ep("GET", "/api/camera/status", "getCameraStatus", "camera", "Start state of camera_stream, and processes holding the video device (foreign = not our own)", READ, None,
       errors=[(502, E502)]),
    ep("GET", "/api/lidar/status", "getLidarStatus", "camera", "Start state of lidar_stream (point cloud stream on the Jetson)", READ, None, errors=[(502, E502)]),
    ep("GET", "/lidar", "getLidar", "camera", "Latest single frame of the LiDAR point cloud (decimated by default). Repeated float32 little-endian (x,y,z,intensity). The point count is in X-Lidar-Points", READ, None,
       errors=[(404, "LiDAR not configured (enter the Jetson IP on the Settings tab)"), (502, "Cannot reach the stream source. Check that lidar_stream is running")],
       content="application/octet-stream", ok_status="Point cloud binary (16 bytes x number of points). With X-Lidar-Seq / X-Lidar-Points / X-Lidar-Age-Ms headers",
       notes="Coordinates are left in livox_frame (unit m). May be tilted relative to the G1's orientation. "
             "The query voxel (voxel width in m, 0 to 1, 0 disables decimation, default 0.1) and max (maximum points 100 to 30000, default 5000) set the decimation strength. Out-of-range values are ignored and the default is used."),
    ep("GET", "/api/dds", "getDds", "dds", "Ledger of DDS topics and RPC services (displayed / not implemented / excluded)", READ, "Dds"),
    ep("GET", "/api/buttons", "getButtons", "ops", "Modes that can be switched to. Choose the id for POST /api/mode from here", READ, "Buttons"),
    ep("GET", "/api/features", "getFeatures", "dds", "implemented / verified per feature (verified=false means unverified on the real robot)", READ, "Features"),
    ep("GET", "/api/settings", "getSettings", "settings", "Connection target settings (development PC / Jetson / G1 IP, etc.)", READ, "Settings"),
    ep("GET", "/api/scenarios", "getScenarios", "mock", "List of mock scenarios and the current one", READ, "Scenarios", mock_only=True),
    ep("GET", "/camera/{name}", "getCamera", "camera", "Camera video (MJPEG stream). name is a key of GET /api/cameras", READ, None,
       errors=[(404, "Camera not configured or name is invalid"), (502, "Cannot reach the stream source")],
       content="multipart/x-mixed-replace", ok_status="MJPEG stream (never ends)"),
    ep("GET", "/openapi.yaml", "getOpenapiYaml", "ops", "This API definition (OpenAPI, YAML)", READ, None, content="application/yaml"),

    ep("POST", "/api/settings", "postSettings", "settings", "Save the connection target and apply it (changing the Jetson re-establishes ssh)", SETTINGS, "Settings",
       request="SettingsPatch", example={"jetson_host": "192.168.123.164", "g1_ip": "192.168.123.161"}, errors=[(400, E400 + " (not an IP or hostname, out of range, etc. The reason is in error)"), (500, "Cannot save")]),
    ep("POST", "/api/topics/subscribe", "postTopicSubscribe", "dds", "Subscribe to a topic (starts the helper the first time)", SETTINGS, "TopicSubscribed",
       request="TopicSubscribePatch", example={"topic": "rt/rtc/state", "type": "String_"},
       errors=[(400, E400), (409, "Subscription limit"), (422, "Type cannot be read"), (502, E502)], unverified=True,
       notes="Do not guess the type from the name. The caller looks at type in GET /api/dds and specifies only one that is in supported_types."),
    ep("POST", "/api/topics/unsubscribe", "postTopicUnsubscribe", "dds", "Stop subscribing", SETTINGS, "TopicUnsubscribed",
       request="TopicNamePatch", example={"topic": "rt/rtc/state"}, errors=[(400, E400), (404, "Not subscribed"), (502, E502)], unverified=True),
    ep("POST", "/api/topics/publish", "postTopicPublish", "dds", "Send a String_ to a topic in the allowlist. **Goes out on the G1's DDS**", WRITE, "TopicPublished",
       request="TopicPublishPatch", example={"topic": "rt/console_demo/say", "data": "hello"},
       errors=[(400, E400), (403, "Always-refused topic, or not in the allowlist"), (413, "Exceeds max_bytes"), (429, "Faster than the minimum interval"), (502, E502)], unverified=True,
       notes="The deny list (motion, joint, arm, RPC, etc.) is not overridden by putting a topic in the allowlist. The allowlist is only the server-side --topics-file and cannot be extended from the UI or API."),
    ep("POST", "/api/camera/start", "postCameraStart", "camera", "Start camera_stream.py on the Jetson (does not restart. May fail if something else holds the device)", SETTINGS, None, errors=[(502, E502)]),
    ep("POST", "/api/camera/stop", "postCameraStop", "camera", "Stop only camera_stream.py (does not stop other processes such as videohub)", SETTINGS, None, errors=[(502, E502)]),
    ep("POST", "/api/lidar/start", "postLidarStart", "camera", "Start lidar_stream.py on the Jetson (only subscribes to DDS. Does not restart)", SETTINGS, None, errors=[(502, E502)]),
    ep("POST", "/api/lidar/stop", "postLidarStop", "camera", "Stop only lidar_stream.py", SETTINGS, None, errors=[(502, E502)]),
    ep("GET", "/api/lidar/sensor", "getLidarSensor", "camera", "Read the operating mode of the LiDAR unit (Livox work_tgt_mode)", READ, None, errors=[(502, E502)],
       notes="Only with --local / --mock. mode: 1=measuring (SAMPLING) / 2=standby (IDLE, laser off) / 9=ready (READY). laser_off is true when mode=2."),
    ep("POST", "/api/lidar/sensor/idle", "postLidarSensorIdle", "camera", "Put the LiDAR unit in standby (IDLE). **The laser stops and no point cloud arrives**", SETTINGS, None, errors=[(502, E502)],
       unverified=True, notes="Returns the mode read back after setting. Anything that uses the point cloud (such as mapping) stops working. Power cycling returns it to measuring."),
    ep("POST", "/api/lidar/sensor/sampling", "postLidarSensorSampling", "camera", "Return the LiDAR unit to measuring (SAMPLING)", SETTINGS, None, errors=[(502, E502)],
       unverified=True),
    ep("POST", "/api/monitor", "postMonitor", "ops", "Stop / resume automatic checks and reconnection, or check just once", SETTINGS, "Monitor",
       request="MonitorPatch", example={"paused": True}, errors=[(400, E400)],
       notes="While stopped, the server touches neither ssh nor DDS. Explicit operations such as mode switching can still be run while stopped."),
    ep("POST", "/api/hub/stop", "postHubStop", "settings", "Stop the hub (this console) itself. It cannot be restarted from the screen", SETTINGS, "HubStopAck",
       request="HubStopPatch", example={"confirm": True}, errors=[(400, E400 + " (confirm is not true)"), (409, "A task is running, or the motion operator lock is held")],
       unverified=True,
       notes="Exits after responding (exit code 0; it is not restarted by systemd's Restart=on-failure). After it stops, restart it on the Jetson. The camera and LiDAR streams are separate processes and are expected not to stop (unverified)."),
    ep("POST", "/api/mode", "postMode", "ops", "Switch the G1 mode (FSM). **The robot moves**", MOTION, "ModeAck",
       request="ModePatch", example={"id": 3}, errors=[(400, E400 + " (id not allowed)"), (502, E502)], unverified=True,
       notes="Acceptance (set_code=0) does not mean it was reached. After running, read GET /api/status repeatedly and check that mode.fsm_id becomes the target (about 15 seconds as a guide). "
             "Switching while walking (500/501) risks a fall. Always confirm with a person before running. Unverified on the real robot."),
    ep("POST", "/api/speed", "postSpeed", "ops", "Switch the speed mode (SetSpeedMode). **The robot's walking speed changes**", MOTION, "ModeAck",
       request="SpeedPatch", example={"value": 0}, errors=[(400, E400 + " (value not allowed)"), (502, E502)], unverified=True,
       notes="The meaning of value (which is slower) is undocumented and unverified. There is no way to read it back. Send only while walking (500/501)."),
    ep("POST", "/api/tasks/start", "postTaskStart", "tasks", "Start a predefined task (pass only the name). Depending on the task, the robot may move", SETTINGS, "Task",
       request="TaskNamePatch", example={"name": "sample-countdown"},
       errors=[(400, E400), (404, "Task not in the definitions"), (409, "The same task or the same exclusive group is running"), (500, "Cannot start")], unverified=True,
       notes="Does not go through a shell. After starting, check the result with GET /api/tasks/logs and state / result / exit_code of GET /api/tasks. "
             "A task with verified=false is unverified on the real robot, and caution is the warning text (the UI shows it in a dialog before running)."),
    ep("POST", "/api/tasks/stop", "postTaskStop", "tasks", "Stop a running task (SIGTERM to the process group, SIGKILL after a grace period)", SETTINGS, "Task",
       request="TaskNamePatch", example={"name": "sample-countdown"}, errors=[(400, E400), (404, "Task not in the definitions"), (409, "Not running")]),
    ep("POST", "/api/motion/claim","postMotionClaim", "motion", "Take the operator lock (starts the motion helper. Takes a few seconds the first time)", WRITE, "MotionClaim",
       request="MotionClaimPatch", example={}, errors=[(400, E400), (409, "Someone else is operating"), (502, "The motion helper does not start"), (503, "Unavailable because --local is not set")], unverified=True,
       notes="There is one operator. It does not resume automatically after a lost link, emergency stop or release, so claim again."),
    ep("POST", "/api/motion/ctl", "postMotionCtl", "motion", "Send the target velocity. **The robot moves**. Keep sending at 10 Hz (if the signal is lost for 0.5 seconds it stops and the operator lock is released)", MOTION, "MotionStatus",
       request="MotionCtlPatch", example={"session": "example", "seq": 1, "vx": 0.0, "vy": 0.0, "wz": 0.0}, errors=[(400, E400 + " (not a number, not finite)"), (409, "No operator lock")], unverified=True,
       notes="Does not move unless the FSM is 500/501 (the reason is in blocked). Velocity is clamped to the limits (initial values, unverified on the real robot). Do not send when nobody is watching. Keep the physical remote controller at hand."),
    ep("POST", "/api/motion/release", "postMotionRelease", "motion", "Give up the operator lock (sets zero velocity)", MOTION, "MotionStatus",
       request="MotionSessionPatch", example={"session": "example"}, errors=[(400, E400), (409, "No operator lock")], unverified=True),
    ep("POST", "/api/motion/estop", "postMotionEstop", "motion", "Emergency stop. Sends zero velocity plus StopMove and releases the operator lock (anyone can press it, even without the lock)", MOTION, "MotionStatus", unverified=True,
       notes="Does not go to damping or zero torque (keeps the autonomous upright posture). **A software stop does not meet any safety standard. The last resort is the physical remote controller.**"),
    ep("POST", "/api/motion/action", "postMotionAction", "motion", "Action (wave, handshake). **The robot moves**", MOTION, "MotionStatus",
       request="MotionActionPatch", example={"session": "example", "name": "wave"}, errors=[(400, E400 + " (action not allowed)"), (409, "No operator lock, or not in a walking mode"), (502, E502)], unverified=True,
       notes="The SetTaskId numbers and effects are unverified on the real robot. End a handshake with shake_end after the start."),
    ep("POST", "/api/audio/volume", "postVolume", "audio", "Set the volume, then read it back and confirm it matches", WRITE, "VolumeSet",
       request="VolumePatch", example={"volume": 40}, errors=[(400, E400), (502, E502)], unverified=True,
       notes="If volume_after equals the requested value, it has taken effect."),
    ep("POST", "/api/audio/led", "postLed", "audio", "Set the color of the head LED", WRITE, "Ack",
       request="LedPatch", example={"r": 0, "g": 255, "b": 0}, errors=[(400, E400), (502, E502)], unverified=True,
       notes="code=0 only means accepted. Check by eye whether the color changed (it cannot be read back)."),
    ep("POST", "/api/audio/tts", "postTts", "audio", "Speak the text", WRITE, "Ack",
       request="TtsPatch", example={"text": "Hello", "speaker_id": 0}, errors=[(400, E400), (502, E502)], unverified=True,
       notes="code=0 only means accepted. Check by ear whether sound came out."),
    ep("POST", "/api/scenario", "postScenario", "mock", "Switch the mock scenario", SETTINGS, "Scenario",
       request="ScenarioPatch", example={"scenario": "g1_off"}, errors=[(400, E400)], mock_only=True),
]


# ---- Building OpenAPI --------------------------------------------------------------------------------------
def _operation(e):
    resp_200 = {"description": e["ok_status"]}
    if e["response"]:
        resp_200["content"] = {"application/json": {"schema": ref(e["response"])}}
    elif e["content"]:
        resp_200["content"] = {e["content"]: {"schema": {"type": "string", "format": "binary"} if "stream" in e["ok_status"] or "MJPEG" in e["ok_status"] or e["content"].startswith("image/") else {"type": "string"}}}
    else:
        resp_200["content"] = {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}
    responses = {"200": resp_200}
    for code, why in e["errors"]:
        responses[str(code)] = {"description": why, "content": {"application/json": {"schema": ref("Error")}}}
    desc = e["notes"] or ""
    op = {"operationId": e["operationId"], "tags": [e["tag"]], "summary": e["summary"], "x-effect": e["effect"]}
    if desc:
        op["description"] = desc
    if e["unverified"]:
        op["x-real-robot-verified"] = False
    if e["mock_only"]:
        op["x-mock-only"] = True
    if e["path"] == "/camera/{name}":
        op["parameters"] = [{"name": "name", "in": "path", "required": True, "schema": S(enum=["std", "d435i"])}]
    if e["request"]:
        op["requestBody"] = {"required": True, "content": {"application/json": {
            "schema": ref(e["request"]), "example": e["example"]}}}
    if e["path"] == "/lidar":
        op["parameters"] = [{"name": "voxel", "in": "query", "required": False, "schema": {"type": "number", "minimum": 0, "maximum": 1}},
                            {"name": "max", "in": "query", "required": False, "schema": I(minimum=100, maximum=30000)}]
    op["responses"] = responses
    return op


def openapi() -> dict:
    paths = {}
    for e in ENDPOINTS:
        paths.setdefault(e["path"], {})[e["method"].lower()] = _operation(e)
    return {
        "openapi": "3.0.3",
        "info": {"title": "G1 Console API", "version": "0.1.0",
                 "description": "People see the state on the screen; client developers and AI agents read the same content and operate through this API.\n"
                                "x-effect: read=read only / settings=changes only the console's settings / robot_write=writes to the G1 (sound, LED) / robot_motion=the G1 moves.\n"
                                "x-real-robot-verified=false means unverified on the real robot. Errors: " + ERRORS},
        "servers": [{"url": "http://127.0.0.1:{port}", "variables": {"port": {"default": "18790"}}}],
        "tags": [{"name": k, "description": v} for k, v in TAGS.items()],
        "paths": paths,
        "components": {"schemas": SCHEMAS},
    }


def render_markdown() -> str:
    doc = openapi()
    lines = [
        "# G1 Console API", "",
        "<!-- Generated from api_spec.py. Do not edit by hand; regenerate with `python3 g1console/api_spec.py` -->", "",
        "The source of truth is OpenAPI: **`docs/openapi.yaml`** (`GET /openapi.yaml` while running, `GET /api` for JSON). "
        "This document is a summary that people and AI agents read first. The base URL is `http://127.0.0.1:18790`.", "",
        "## How to use it", "",
        "- **\"Check ...\"**: start with `GET /api/status` (connection, mode, staleness). One `GET /api/snapshot` is enough for details.",
        "  If `jetson.state` / `g1.state` is not ok, do not trust the values beyond it. If `age_s` is several seconds or more, or `paused=true`, the values are stale.",
        "- **\"Run ...\"**: `x-effect: robot_motion` means **the robot moves**. Confirm with a person before running, and **confirm it was reached** afterwards with `GET /api/status` (accepted != reached).",
        "  `robot_write` (sound, LED) is accepted only; confirm the effect by eye or ear.",
        "- `x-real-robot-verified: false` and `verified=false` in `GET /api/features` mean unverified on the real robot. Do not assert results.",
        "- Bodies are JSON. Every error is an `Error` (`{\"error\": \"reason\"}`). " + ERRORS,
        "- Screen tab name = URL hash = tag name (`#state` <-> `/api/state`).", "",
        "## Endpoints", "", "| Method | Path | operationId | x-effect | Summary |", "|---|---|---|---|---|",
    ]
    for path, methods in doc["paths"].items():
        for m, op in methods.items():
            flags = (" [unverified on real robot]" if op.get("x-real-robot-verified") is False else "") + (" (mock only)" if op.get("x-mock-only") else "")
            lines.append("| %s | `%s` | %s | %s | %s%s |" % (m.upper(), path, op["operationId"], op["x-effect"], op["summary"], flags))
    lines += ["", "## Request examples", ""]
    for path, methods in doc["paths"].items():
        for m, op in methods.items():
            if "requestBody" in op:
                body = op["requestBody"]["content"]["application/json"]
                lines += ["### %s %s" % (m.upper(), path), "", op["summary"], "",
                          "```json", json.dumps(body["example"], ensure_ascii=False), "```",
                          "Schema: `%s`" % body["schema"]["$ref"].rsplit("/", 1)[1] + (". " + op["description"] if op.get("description") else ""), ""]
    return "\n".join(lines)


# ---- YAML output (standard library only. Strings are quoted in JSON notation, which is valid YAML) ------------
def _scalar(v):
    return json.dumps(v, ensure_ascii=False)


def _key(k):
    k = str(k)
    return k if k.replace("_", "a").replace("-", "a").isalnum() and not k[0].isdigit() else _scalar(k)


def _yaml(v, indent=0):
    pad = "  " * indent
    if isinstance(v, dict):
        if not v:
            return "{}"
        out = []
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                out.append("%s%s:\n%s" % (pad, _key(k), _yaml(x, indent + 1)))
            else:
                out.append("%s%s: %s" % (pad, _key(k), _yaml(x, indent + 1)))
        return "\n".join(out)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "\n".join("%s- %s" % (pad, _yaml(x, indent + 1).lstrip()) for x in v)
    return _scalar(v)


def render_yaml() -> str:
    return "# Generated from api_spec.py (do not edit by hand)\n" + _yaml(openapi()) + "\n"


if __name__ == "__main__":
    from pathlib import Path
    docs = Path(__file__).resolve().parent.parent / "docs"
    (docs / "API.md").write_text(render_markdown(), encoding="utf-8")
    (docs / "openapi.yaml").write_text(render_yaml(), encoding="utf-8")
    print("[api] wrote", docs / "API.md", docs / "openapi.yaml")
