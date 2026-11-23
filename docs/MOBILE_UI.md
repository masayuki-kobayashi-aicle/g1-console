# G1 Control mobile UI

The 11 screens of the mobile UI and how they map to the console's API. This is a record of the screen structure and its inputs, not a statement that any robot function has been added or verified.

## Entry points and how to run it

- `/` and `/index.html`: the UI. The initial screen is `#home`.
- To view it with the mock: `python3 server.py --mock --port 18792`. It does not connect to a real robot.

## The 11 screens and the API

| URL | Main functions |
|---|---|
| `#home` | Connection, mode, battery, data freshness, and entry points to the other screens |
| `#mode` | Modes defined by the API, transitions, Speed 0/1, waiting for arrival, response log |
| `#remote` | Operator lock, direction and turn buttons, speed multiplier, analog input, motion stop |
| `#actions` | Wave, wave_turn and handshake start/end, as allowed by the API |
| `#status` | Detailed connection state, legs, arms, physical remote controller, battery, posture, main board, reception information |
| `#joints` | The 29 joints selected by legs, arms or waist, with details and a full table of commanded values |
| `#voice` | Text to speech, volume and LED. Speech recognition and conversational AI remain unimplemented |
| `#sensors` | Switching between camera, LiDAR and IMU views, and starting and stopping the streamer processes |
| `#tasks` | Start and stop of predefined tasks, run state, logs and results |
| `#dds` | Ledger search and details of the selection, subscribe, unsubscribe and allowed publishing |
| `#settings` | Browser display settings, the existing hub settings, automatic checking, and hub stop |

A URL hash is not always the same as the API name.

## Behavior and boundaries

- The common display is a short header plus connection, mode and battery level. The detailed connection card moved to the status screen, and the controls for automatic checking moved to settings. Navigating between screens swaps the whole body and returns scroll and focus to the top. Browser back and forward are supported.
- The API supplies which modes, actions and functions are available. The official English mode names, the transition limits, the speed test, the unverified notes and the caution dialog are kept. An accepted action is not shown as a completed motion.
- The direction buttons of the remote screen can press movement and turning at the same time. The speed multiplier is applied to the existing per-axis limits. A fixed speed from the mock is not sent.
- Input is sent only after an operator lock has been acquired. Lifting the finger, `pointercancel` and `lostpointercapture` set that input to zero. After leaving the screen, hiding the page or losing the operator lock, input does not resume by itself. If the screen is left while waiting for the lock, a session that arrives late is released.
- On a communication error the browser ends the operation. The hub-side liveness check, clamping and exclusion are unchanged. Physical stopping still needs to be confirmed on a real robot.
- When the sensor view is left, the stream and point cloud fetching stop. A late response does not reopen the display connection. Starting a streamer process is still an explicit action.
- A task screen shows only the state, result and log that were fetched. There is no progress percentage, pause or resume. A running task can be reached again from the common display.
- Only the new display name and the display density are saved in `localStorage`. Connection settings are saved with the existing `POST /api/settings`. Domain ID and speech recognition settings were not added.

## Structure and checks

- `web/index.html`: the 11 screens and the common shell.
- `web/mobile.css`: colors, type, spacing and the mobile layout.
- `web/ui-core.js`: the API and control code. Screen navigation and late-response handling are included.
- `web/mobile.js`: home display, direction input, body-part selection, sensor switching, search and display settings.
- The server serves only the fixed files above, behind the existing authentication gate. It does not serve arbitrary file paths.
- `bash tests/run_tests.sh`: the control, authentication, API and feature tests, plus checks of static serving and the screen structure.
- `node tests/mobile_startup.cjs`: starts the HTML and both scripts as a whole against a stand-in DOM, and checks the initialization of the 11 screens and that navigation does not send any robot command. It does not check the look in a browser or real touch input.
- `node tests/mobile_runtime.cjs`: runs the real input, routing and operator lock code without a browser. It checks stale values, simultaneous input and late responses after navigation.

## Remaining checks

- [ ] A person checks 320 / 375 / 390 / 430 px widths, portrait and landscape, safe areas, the keyboard and long text.
- [ ] Check simultaneous touches, lifting the finger, screen lock and back/forward on a phone.
- [ ] Follow [REAL_ROBOT_CHECKLIST.md](REAL_ROBOT_CHECKLIST.md) for real-robot tests. Do not treat "implemented" or "passed in the mock" as success on a real robot.
- [ ] Check the behavior of motion, camera, LiDAR and audio on the robot, plus bandwidth and latency.

Additional features (pause and resume of tasks, conversational AI, action completion notification, changing the DDS domain) belong to a separate API and control design.
