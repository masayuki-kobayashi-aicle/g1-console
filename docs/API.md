# G1 Console API

<!-- Generated from api_spec.py. Do not edit by hand; regenerate with `python3 g1console/api_spec.py` -->

The source of truth is OpenAPI: **`docs/openapi.yaml`** (`GET /openapi.yaml` while running, `GET /api` for JSON). This document is a summary that people and AI agents read first. The base URL is `http://127.0.0.1:18790`.

## How to use it

- **"Check ..."**: start with `GET /api/status` (connection, mode, staleness). One `GET /api/snapshot` is enough for details.
  If `jetson.state` / `g1.state` is not ok, do not trust the values beyond it. If `age_s` is several seconds or more, or `paused=true`, the values are stale.
- **"Run ..."**: `x-effect: robot_motion` means **the robot moves**. Confirm with a person before running, and **confirm it was reached** afterwards with `GET /api/status` (accepted != reached).
  `robot_write` (sound, LED) is accepted only; confirm the effect by eye or ear.
- `x-real-robot-verified: false` and `verified=false` in `GET /api/features` mean unverified on the real robot. Do not assert results.
- Bodies are JSON. Every error is an `Error` (`{"error": "reason"}`). HTTP 400=invalid input / 404=undefined / 500=save failed / 502=cannot reach the G1 or Jetson, or the G1 rejected it. The body is always Error.
- Screen tab name = URL hash = tag name (`#state` <-> `/api/state`).

## Endpoints

| Method | Path | operationId | x-effect | Summary |
|---|---|---|---|---|
| GET | `/api` | getApi | read | This API definition (OpenAPI, JSON) |
| GET | `/api/status` | getStatus | read | Read this first. Connection (jetson/g1), current mode, staleness of the check, and whether automatic checks are stopped |
| GET | `/api/state` | getState | read | Battery, IMU, odometry, main board, Jetson, remote controller, emergency stop |
| GET | `/api/joints` | getJoints | read | Angle, velocity, estimated torque, temperature and command values of the 29 joints |
| GET | `/api/snapshot` | getSnapshot | read | Get state and joints in one call (this one call is enough to grasp the situation) |
| GET | `/api/audio/volume` | getVolume | read | Read the speaker volume from the G1 (actually queries it via the Jetson) |
| POST | `/api/audio/volume` | postVolume | robot_write | Set the volume, then read it back and confirm it matches [unverified on real robot] |
| GET | `/api/motion/status` | getMotionStatus | read | State of motion control (operator, target velocity, reason it cannot move, most recent event) |
| GET | `/api/tasks` | getTasks | read | List of runnable tasks and the state of each one's most recent run |
| GET | `/api/tasks/logs` | getTaskLogs | read | Task log (line by line). Query: name and since (last seq seen) |
| GET | `/api/topics` | getTopics | read | Topic communication policy (always refused, publish allowlist, subscribed) |
| GET | `/api/topics/received` | getTopicsReceived | read | Latest message and reception status of the subscribed topics |
| GET | `/api/cameras` | getCameras | read | List of cameras and whether streaming is configured (video is GET /camera/{name}) |
| GET | `/api/camera/status` | getCameraStatus | read | Start state of camera_stream, and processes holding the video device (foreign = not our own) |
| GET | `/api/lidar/status` | getLidarStatus | read | Start state of lidar_stream (point cloud stream on the Jetson) |
| GET | `/lidar` | getLidar | read | Latest single frame of the LiDAR point cloud (decimated by default). Repeated float32 little-endian (x,y,z,intensity). The point count is in X-Lidar-Points |
| GET | `/api/dds` | getDds | read | Ledger of DDS topics and RPC services (displayed / not implemented / excluded) |
| GET | `/api/buttons` | getButtons | read | Modes that can be switched to. Choose the id for POST /api/mode from here |
| GET | `/api/features` | getFeatures | read | implemented / verified per feature (verified=false means unverified on the real robot) |
| GET | `/api/settings` | getSettings | read | Connection target settings (development PC / Jetson / G1 IP, etc.) |
| POST | `/api/settings` | postSettings | settings | Save the connection target and apply it (changing the Jetson re-establishes ssh) |
| GET | `/api/scenarios` | getScenarios | read | List of mock scenarios and the current one (mock only) |
| GET | `/camera/{name}` | getCamera | read | Camera video (MJPEG stream). name is a key of GET /api/cameras |
| GET | `/openapi.yaml` | getOpenapiYaml | read | This API definition (OpenAPI, YAML) |
| POST | `/api/topics/subscribe` | postTopicSubscribe | settings | Subscribe to a topic (starts the helper the first time) [unverified on real robot] |
| POST | `/api/topics/unsubscribe` | postTopicUnsubscribe | settings | Stop subscribing [unverified on real robot] |
| POST | `/api/topics/publish` | postTopicPublish | robot_write | Send a String_ to a topic in the allowlist. **Goes out on the G1's DDS** [unverified on real robot] |
| POST | `/api/camera/start` | postCameraStart | settings | Start camera_stream.py on the Jetson (does not restart. May fail if something else holds the device) |
| POST | `/api/camera/stop` | postCameraStop | settings | Stop only camera_stream.py (does not stop other processes such as videohub) |
| POST | `/api/lidar/start` | postLidarStart | settings | Start lidar_stream.py on the Jetson (only subscribes to DDS. Does not restart) |
| POST | `/api/lidar/stop` | postLidarStop | settings | Stop only lidar_stream.py |
| GET | `/api/lidar/sensor` | getLidarSensor | read | Read the operating mode of the LiDAR unit (Livox work_tgt_mode) |
| POST | `/api/lidar/sensor/idle` | postLidarSensorIdle | settings | Put the LiDAR unit in standby (IDLE). **The laser stops and no point cloud arrives** [unverified on real robot] |
| POST | `/api/lidar/sensor/sampling` | postLidarSensorSampling | settings | Return the LiDAR unit to measuring (SAMPLING) [unverified on real robot] |
| POST | `/api/monitor` | postMonitor | settings | Stop / resume automatic checks and reconnection, or check just once |
| POST | `/api/hub/stop` | postHubStop | settings | Stop the hub (this console) itself. It cannot be restarted from the screen [unverified on real robot] |
| POST | `/api/mode` | postMode | robot_motion | Switch the G1 mode (FSM). **The robot moves** [unverified on real robot] |
| POST | `/api/speed` | postSpeed | robot_motion | Switch the speed mode (SetSpeedMode). **The robot's walking speed changes** [unverified on real robot] |
| POST | `/api/tasks/start` | postTaskStart | settings | Start a predefined task (pass only the name). Depending on the task, the robot may move [unverified on real robot] |
| POST | `/api/tasks/stop` | postTaskStop | settings | Stop a running task (SIGTERM to the process group, SIGKILL after a grace period) |
| POST | `/api/motion/claim` | postMotionClaim | robot_write | Take the operator lock (starts the motion helper. Takes a few seconds the first time) [unverified on real robot] |
| POST | `/api/motion/ctl` | postMotionCtl | robot_motion | Send the target velocity. **The robot moves**. Keep sending at 10 Hz (if the signal is lost for 0.5 seconds it stops and the operator lock is released) [unverified on real robot] |
| POST | `/api/motion/release` | postMotionRelease | robot_motion | Give up the operator lock (sets zero velocity) [unverified on real robot] |
| POST | `/api/motion/estop` | postMotionEstop | robot_motion | Emergency stop. Sends zero velocity plus StopMove and releases the operator lock (anyone can press it, even without the lock) [unverified on real robot] |
| POST | `/api/motion/action` | postMotionAction | robot_motion | Action (wave, handshake). **The robot moves** [unverified on real robot] |
| POST | `/api/audio/led` | postLed | robot_write | Set the color of the head LED [unverified on real robot] |
| POST | `/api/audio/tts` | postTts | robot_write | Speak the text [unverified on real robot] |
| POST | `/api/scenario` | postScenario | settings | Switch the mock scenario (mock only) |

## Request examples

### POST /api/audio/volume

Set the volume, then read it back and confirm it matches

```json
{"volume": 40}
```
Schema: `VolumePatch`. If volume_after equals the requested value, it has taken effect.

### POST /api/settings

Save the connection target and apply it (changing the Jetson re-establishes ssh)

```json
{"jetson_host": "192.168.123.164", "g1_ip": "192.168.123.161"}
```
Schema: `SettingsPatch`

### POST /api/topics/subscribe

Subscribe to a topic (starts the helper the first time)

```json
{"topic": "rt/rtc/state", "type": "String_"}
```
Schema: `TopicSubscribePatch`. Do not guess the type from the name. The caller looks at type in GET /api/dds and specifies only one that is in supported_types.

### POST /api/topics/unsubscribe

Stop subscribing

```json
{"topic": "rt/rtc/state"}
```
Schema: `TopicNamePatch`

### POST /api/topics/publish

Send a String_ to a topic in the allowlist. **Goes out on the G1's DDS**

```json
{"topic": "rt/console_demo/say", "data": "hello"}
```
Schema: `TopicPublishPatch`. The deny list (motion, joint, arm, RPC, etc.) is not overridden by putting a topic in the allowlist. The allowlist is only the server-side --topics-file and cannot be extended from the UI or API.

### POST /api/monitor

Stop / resume automatic checks and reconnection, or check just once

```json
{"paused": true}
```
Schema: `MonitorPatch`. While stopped, the server touches neither ssh nor DDS. Explicit operations such as mode switching can still be run while stopped.

### POST /api/hub/stop

Stop the hub (this console) itself. It cannot be restarted from the screen

```json
{"confirm": true}
```
Schema: `HubStopPatch`. Exits after responding (exit code 0; it is not restarted by systemd's Restart=on-failure). After it stops, restart it on the Jetson. The camera and LiDAR streams are separate processes and are expected not to stop (unverified).

### POST /api/mode

Switch the G1 mode (FSM). **The robot moves**

```json
{"id": 3}
```
Schema: `ModePatch`. Acceptance (set_code=0) does not mean it was reached. After running, read GET /api/status repeatedly and check that mode.fsm_id becomes the target (about 15 seconds as a guide). Switching while walking (500/501) risks a fall. Always confirm with a person before running. Unverified on the real robot.

### POST /api/speed

Switch the speed mode (SetSpeedMode). **The robot's walking speed changes**

```json
{"value": 0}
```
Schema: `SpeedPatch`. The meaning of value (which is slower) is undocumented and unverified. There is no way to read it back. Send only while walking (500/501).

### POST /api/tasks/start

Start a predefined task (pass only the name). Depending on the task, the robot may move

```json
{"name": "sample-countdown"}
```
Schema: `TaskNamePatch`. Does not go through a shell. After starting, check the result with GET /api/tasks/logs and state / result / exit_code of GET /api/tasks. A task with verified=false is unverified on the real robot, and caution is the warning text (the UI shows it in a dialog before running).

### POST /api/tasks/stop

Stop a running task (SIGTERM to the process group, SIGKILL after a grace period)

```json
{"name": "sample-countdown"}
```
Schema: `TaskNamePatch`

### POST /api/motion/claim

Take the operator lock (starts the motion helper. Takes a few seconds the first time)

```json
{}
```
Schema: `MotionClaimPatch`. There is one operator. It does not resume automatically after a lost link, emergency stop or release, so claim again.

### POST /api/motion/ctl

Send the target velocity. **The robot moves**. Keep sending at 10 Hz (if the signal is lost for 0.5 seconds it stops and the operator lock is released)

```json
{"session": "example", "seq": 1, "vx": 0.0, "vy": 0.0, "wz": 0.0}
```
Schema: `MotionCtlPatch`. Does not move unless the FSM is 500/501 (the reason is in blocked). Velocity is clamped to the limits (initial values, unverified on the real robot). Do not send when nobody is watching. Keep the physical remote controller at hand.

### POST /api/motion/release

Give up the operator lock (sets zero velocity)

```json
{"session": "example"}
```
Schema: `MotionSessionPatch`

### POST /api/motion/action

Action (wave, handshake). **The robot moves**

```json
{"session": "example", "name": "wave"}
```
Schema: `MotionActionPatch`. The SetTaskId numbers and effects are unverified on the real robot. End a handshake with shake_end after the start.

### POST /api/audio/led

Set the color of the head LED

```json
{"r": 0, "g": 255, "b": 0}
```
Schema: `LedPatch`. code=0 only means accepted. Check by eye whether the color changed (it cannot be read back).

### POST /api/audio/tts

Speak the text

```json
{"text": "Hello", "speaker_id": 0}
```
Schema: `TtsPatch`. code=0 only means accepted. Check by ear whether sound came out.

### POST /api/scenario

Switch the mock scenario

```json
{"scenario": "g1_off"}
```
Schema: `ScenarioPatch`
