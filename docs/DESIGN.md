# Design (hub resident on the Jetson)

Status legend: **implemented** / **design only** (not implemented) / **unverified** (not tried on a real robot).

## 1. Overall structure
```
Phone / external PC (browser only)
        │  HTTP (wlan0, token authentication)
        ▼
Jetson (PC2)
  ┌──────────────────────────────────────────────────────────────┐
  │ Hub  server.py (stdlib ThreadingHTTPServer)  ← only this stays resident │
  │   ├ auth.py          authentication, Host/Origin checks      │
  │   ├ LocalHelper ── remote_helper.py (child process) ── DDS (eth0) ── G1   state, modes, audio, LED │
  │   ├ MotionController ── motion_helper.py (child process) ── DDS ── G1     velocity commands │
  │   ├ LocalCameraCtl / LocalLidarCtl ── camera_ctl.sh / lidar_ctl.sh        on demand │
  │   └ TaskRunner ── child processes from tasks/*.json                       on demand │
  └──────────────────────────────────────────────────────────────┘
```
- The hub listens only on loopback and the IPv4 address of wlan0. It does not listen on eth0 (192.168.123.x).
- The hub does not depend on ROS. Anything that touches ROS stays in a separate process and talks to the hub over localhost.

## 2. Local execution, listening, authentication, residency (implemented)
### 2.1 Local execution
- `LocalHelper`, a subclass of `SshHelper`, starts `remote_helper.py` as a child process (`sys.executable -u -c <src>`, with the SDK directory as cwd: `$UNITREE_SDK_DIR` or `~/unitree_sdk2_python`). It speaks JSON lines over stdin/stdout, and requests are **processed serially**.
- `LocalRunMixin` replaces the `_run` of `camera_proc` / `lidar_proc` with a local `bash -c` execution (`LocalCameraCtl`, `LocalLidarCtl`). ssh is not called.
- `resolve_host` returns an IP literal unchanged.
- If the SDK is missing, the hub does not crash; it shows "offline".

### 2.2 Listening
- `--bind <ip>` (repeatable) and `--bind-iface <name>`. `resolve_binds` puts loopback first and removes duplicates. `--bind-iface` reads the address from `ip -4 -o addr show dev NAME`, and the name is validated.
- `0.0.0.0` is rejected. Listening on a non-loopback address requires a token (`--require-token` forces it on loopback too).
- One `ThreadingHTTPServer` per bind address. The second and later ones run in daemon threads.

### 2.3 Authentication
- Token: `~/.g1console/token` (0600). If it does not exist it is created with `secrets.token_urlsafe`. Comparison uses `hmac.compare_digest`.
- `/login?token=…` sets the cookie `g1c_token` (HttpOnly, SameSite=Strict) and redirects to `/` with 302. After that, the cookie or `Authorization: Bearer` is used.
- Order of `Handler._gate(post)`: Host check (403) → for POST, Origin check (403) → `/login` handling → authorization → for an unauthenticated request, 401 with the login page for `/` and a JSON 401 for the API.
- Five failures within 60 seconds lock out for 30 seconds (429). A success clears the history.
- `make_handler(..., auth=None)` is the default: no authentication (the original behaviour).
- `--no-auth`: `Auth("", hosts, required=False)`. `authorized()` is always true, and `/login` redirects to `/` with 302 (no cookie). The Host and Origin checks (`_gate`) remain. It is exclusive with `--require-token`. The startup log prints a warning, and the token file is not created.
- **Limit**: the transport is plain HTTP, so the token can be sniffed on the LAN. Motion safety does not rely on the token alone.

### 2.4 Residency
- 2026-10-18 decision: **only the hub starts automatically**. A person installs it.
- `jetson/g1-console.service` is a template (not installed). `ExecStart=python3 server.py --local --bind-iface wlan0`, `Restart=on-failure`. Installing and enabling it is done by a person with `sudo` (`docs/JETSON_SETUP.md` section 4). Before installation, start and stop the hub by hand.
- The camera and LiDAR streamers are not made resident and are not restarted automatically.

## 3. Screen structure (implemented; appearance unverified)
- The UI is a single page, `web/index.html`, with 11 screens. The URL hash selects the screen (`#home`, `#mode`, `#remote`, ... see [MOBILE_UI.md](MOBILE_UI.md)); the `ROUTES` table in `web/ui-core.js` maps each hash to an internal tab name.
- The `GROUPS` array in `web/ui-core.js` groups the screens for navigation: Home, Operate (mode, remote, actions, voice), State (status, joints), Tasks, Sensors and Development (DDS, settings). To add a screen, put it in the array of the matching group.
- Direct `#hash` links are kept, and browser back and forward are supported.
- The layout (for example whether it breaks at 360 px width) has not been checked visually.

## 4. Motion control (implemented; one successful run reported by the operator, nothing else verified)
### 4.1 Why a separate process
`remote_helper.py` processes requests one line at a time, and `SshHelper.call` is also serialized by a `threading.Lock`. A heavy `status` request would make velocity commands wait, so there is a **minimal helper dedicated to motion** (`jetson/motion_helper.py`). It allows only `SetVelocity` and `StopMove` of `LocoClient` and has no `SetFsmId` (the tests also check for forbidden names).

### 4.2 Command flow and time constants
| Item | Value | Basis |
|---|---|---|
| Browser → hub | `POST /api/motion/ctl {seq, vx, vy, wz}` at 10 Hz | polling, because the server is stdlib-only |
| Hub → robot | `SetVelocity(vx, vy, wz, duration=0.2)` at 20 Hz | send period < `duration` |
| Liveness check | zero velocity and state `lost` if more than 0.5 s passes since the last command | stop when commands stop arriving |
| Hub stops | the robot stops when `duration` expires | robot-side backstop |

The 0.5 s, the 0.2 s and the velocity clamp values are **initial values**, not final until confirmed on a real robot (unverified). The operator reported one successful movement on a real robot on 2026-10-24 (not independently recorded); the stop-on-release delay, the stopping distance and the loss-of-link stop (checklist E1 to E6) are still open.

### 4.3 State transitions
`disarmed` (right after start) → acquire the operator lock (`POST /api/motion/claim`) → `armed` → commands arriving: `active` → commands stop, release or emergency stop: `lost` (zero velocity). Going from `lost` back to `active` needs an **explicit resume action** (there is no automatic resume).
- Motion is allowed only in FSM 500/501 (`mode.fsm_id` from `Monitor.snapshot()`).
- Velocity is clamped on the server (constants; the browser's values are not trusted).

### 4.4 Browser
- A joystick built on Pointer Events (multi-touch). Releasing the finger, `visibilitychange` and `pagehide` send zero velocity, and `navigator.sendBeacon` sends a final zero.
- An emergency stop button is always visible. The screen states that the software stop is not a certified safety function and that the physical remote controller is the last line of defense.

### 4.5 Actions
`SetTaskId` is executed from an allowlist (`ACTIONS` in `modes.py`: wave 0 / wave_turn 1 / shake_start 2 / shake_end 3). It works only for the operator, and only in FSM 500/501. The numbers and the motions are inferred from SDK material and are unverified on a real robot. `PLANNED_ACTIONS` is empty.

### 4.6 Implementation notes
- **Structure**: `MotionController` in `g1console/motion.py` (the sender is replaceable: `HelperSender` = child process `motion_helper.py`, `MockSender`, and `UnavailableSender` in ssh mode, which answers 503). The hub's tick thread sends `SetVelocity` with `duration=0.2` at 20 Hz (`SEND_PERIOD_S=0.05`).
- **Operator lock**: `claim` returns a `session`. After a timeout, emergency stop, release, takeover or invalidation, there is no operator, and a new `claim` is needed (no automatic resume).
- **Lock and generation**: decisions are made under `_lock`, sending under a separate `_send_lock`. Every stop advances a generation `_gen`, and a stale decision made before the stop is not sent. A delayed command whose `seq` did not increase is not applied and does not count as proof of liveness.
- **Zero velocity**: after one stop has been sent, nothing more is sent (so the console does not fight the physical remote controller). If three sends in a row fail, the operator is dropped.
- **Two layers of defense**: the hub (`LIMITS`: vx -0.2 to 0.3, vy ±0.2, wz ±0.4, `DEADBAND` 0.01) and the helper (clamps again with the same values, `duration` capped at 0.5 s).
- **Known limit**: the helper is serial, so an emergency stop queues behind a `move` that is being sent (at most `HELPER_TIMEOUT_S`=1.0 s). The backstop is the robot's own `duration=0.2` expiry.
- **Lesson**: passing a stale `seq` to `status()` (which takes the same lock) while holding `_lock` caused a deadlock. Call it outside the lock.

## 5. Tasks (implemented; unverified on the Jetson)
- Definitions in `tasks/*.json`: name, title, description, argv array, cwd, exclusive group, timeout and preconditions. **Shell strings are not accepted.**
- Execution: a child process in a new process group, with the log kept in a ring buffer (polled with `since`). Stop is SIGTERM then SIGKILL (to the group). A lock per exclusive group prevents concurrent starts. `exit_code` is returned.
- A shell-string `template` and any API that reads or writes arbitrary paths are **not adopted**.

### 5.1 Implementation notes
- `g1console/tasks.py`: `load_definitions` (validates every JSON file at startup; if any is invalid the hub does not start) and `TaskRunner`. The only keys in a definition are `title / description / argv / cwd / group / timeout_s` (unknown keys are rejected). `cwd` is relative to the console directory and cannot leave it. `timeout_s` is 1 to 3600.
- Execution: `shell=False`, `stdin=DEVNULL`, `start_new_session=True`. stdout and stderr are merged and kept line by line in a 2000-line ring buffer (a line is cut at 2000 characters). The result is one of `ok / failed / stopped / timeout`, with `exit_code` (negative means a signal).
- Stop: SIGTERM to the process group, then SIGKILL after a 3-second grace period. On exit, SIGKILL is also sent to the group so that no grandchild survives the leader.
- Exclusion: a second start of the same task, or a start while another task of the same `group` runs, returns 409. A task without a group is exclusive only with itself.
- API: `GET /api/tasks`, `GET /api/tasks/logs?name=&since=` (pass `next` as the next `since` for no gaps and no duplicates), `POST /api/tasks/start|stop` (only `name` is read; extra keys are ignored).
- Hub shutdown: SIGTERM is turned into `SystemExit` so that cleanup (stopping motion, the motion helper and tasks) always runs. Previously cleanup did not run on SIGTERM and children could be orphaned. Under systemd the whole cgroup is stopped, but this covers a hub started by hand.
- Known limit: there is a path that calls `killpg` after the child has been reaped. If the pid is reused within a very short time, the signal could go to an unrelated group (the probability is negligible in practice; `waitid(WNOWAIT)` could be used if needed). When a task's content moves the robot, safety is the responsibility of that task.

## 6. Topic communication (implemented; unverified on the Jetson)
- `g1console/topics.py`: decisions and the service layer (no side effects). `topic_backend.py`: owns the Jetson DDS helper (`jetson/topic_helper.py`) as a child process. The helper does not start until the first subscribe or publish. `--mock` returns fake messages and only records publishes. Enabled only with `--local` and `--mock` (404 over ssh).
- Receive: the caller specifies the type, and only types in `SUPPORTED_TYPES` (String_, Error_, WirelessController_, BmsState_, IMUState_, SportModeState_) can be subscribed (at most 8). **A topic whose type cannot be read is refused with 422.** The original idea, "for unknown types show only the name and whether anything was received", was not adopted: without the type, DDS reception cannot be observed, so it would make something look possible that is not. Subscribing only reads, so topics on the deny list (`rt/lowcmd` and others) can also be viewed. Arrays are cut to 16 elements and strings to 512 characters.
- Publish: only `String_` to topics on the allowlist (JSON `{version:1, publish:[{topic, type:String_, max_bytes, min_interval_s, note}]}`). The allowlist is a server-side file only and cannot be extended from the UI or the API. A missing file means an empty list (nothing can be published). Order of checks: topic name validation → deny list (403) → allowlist (403) → type of `data` (400) → `max_bytes` (413) → minimum interval (429; the clock can be injected). A failed publish does not consume the interval. The helper re-checks the deny list, the allowlist and the byte count (so nothing reaches DDS even if the hub's checks are bypassed).
- Motion is available only from the dedicated motion screen. `rt/api/*` and similar topics cannot be sent from here. The UI is the "topic communication" section of the DDS screen. Values that come from DDS are rendered with `textContent` only.
- Unverified: actual subscribe and publish on a Jetson (types, QoS), and which practical topics to put on the allowlist.

## 7. Design decisions (with reasons)
| Decision | Reason |
|---|---|
| Do not make the hub depend on ROS | The goal is to reduce dependence on an external PC. Tying it to ROS would stop it from running anywhere but the Jetson |
| Separate motion-only helper | The existing helper is serial, so a heavy request would delay velocity commands |
| Liveness is judged by receive time | TCP and ssh could not detect a disconnect (measured 2026-09-09) |
| Keep autonomous upright (FSM 500/501) when the connection is lost | Damping and zero torque risk a fall |
| Use wlan0 directly (no VPN) | Several people can use it without installing anything extra. Which is faster is unmeasured |
| Topic publishing is allowlist-only | Make it structurally impossible to hit motion topics by mistake |

## 8. Update rule
When a section is implemented, remove "design only". When something is confirmed on a real robot, remove "unverified" and record the date and the measured values.

## 9. Caution dialog for unverified functions (implemented)
- Purpose: when a button for an unverified function is pressed, do not claim a result, and ask for confirmation before running.
- Functions (`FEATURES`): if `verified` is false (or the function is not in the list), pressing a mode, action, motion start, audio, LED, camera/LiDAR start or stop, or topic publish button makes `guard(feature id, …)` open a `<dialog>`. Even when `verified` is true, safety questions (mode switch, text to speech) are always asked via `always` (replacing the earlier `confirm`).
- Tasks: a definition carries `verified` (default false) and `caution` (an array of strings, at most 8 items of 200 characters each). For an unverified task or one with cautions, pressing start or stop opens the dialog, and if there are cautions, "Run" cannot be pressed until the confirmation check is ticked. The card shows an "unverified on a real robot" tag. `run-tests` and `sample-countdown` touch neither the robot nor the Jetson, so they are `verified: true`.
- Text is rendered with `textContent` only (cautions come from the server and are not interpreted as HTML). `Esc`, "Cancel" and the backdrop do not run the action. The default focus is on "Cancel". Old browsers without `<dialog>` fall back to `confirm`.
- Once a function is confirmed on a real robot, set `verified` in `modes.py` or in the task definition to true and the dialog for that function disappears (the `always` safety question stays).
- **Unverified**: the look and operation of the dialog (including phone width) have not been checked in a browser.

## 10. Hub stop button (implemented; unverified on the Jetson)
- `POST /api/hub/stop {"confirm": true}`. It is active only when `make_handler(..., hub_stop=callable)` is given (404 otherwise). It does not act on GET.
- Order: validate the body (400 unless `confirm` is the boolean `true`) → check whether the hub is busy (409 if a task is not idle or `motion.status()["operator"]` is truthy) → return 200 → after `HUB_STOP_DELAY_S` (0.3 s) call `hub_stop()` in another thread. The delay lets the response finish before the stop.
- `hub_stop` in `main()` calls `shutdown()` on every `ThreadingHTTPServer`. `serve_forever` returns, the existing `finally` block runs (cleanup of zero velocity, the motion helper, tasks, topics and the watcher), and the process exits with code 0. systemd's `Restart=on-failure` does not restart on exit code 0, so the hub stays stopped (restart it on the Jetson).
- The authentication, Host and Origin checks are the same as for other POSTs (`_gate`). With `--no-auth`, anyone on the same network can stop the hub.
- UI: the settings screen. It goes through the `guard('hubstop', {always, needCheck, danger})` dialog before the POST. After the hub stops, the state display shows a disconnection.
- **Unverified**: behaviour under systemd on the Jetson, whether the camera and LiDAR streamer processes remain after the stop, and the look on a phone.

## 11. Camera and LiDAR start/stop with `--local` (implemented; checked once on a Jetson)
Requirement: do not disturb other development projects on the same Jetson; the streamers are off by default and use a port only when started from the UI. The buttons and the off-by-default behaviour already existed, but `--local` lacked the location of the ctl scripts, the listening scope and a place for pid files.
- **Off by default**: the hub passes `start` to a ctl script only for `POST /api/{camera,lidar}/start`. GET (status, page) only runs `status`. Hub start, systemd start and a settings change do not start a streamer. There is no automatic restart.
- **Invocation** (`camera_proc.SshCameraCtl._ctl`): `[ENV_PORT=…] [extra environment variables] <dir>/<script>`. The ssh mode is unchanged (`~/g1_console_*`, default bind 0.0.0.0). `LocalRunMixin` replaces `<dir>` with `jetson/` and the extra environment variables with `G1_CTL_STATE_DIR=~/.g1console/run` and `*_BIND=127.0.0.1`. Only fixed words, integers and paths inside the repository reach the shell.
- **Listening**: `camera_stream.py` and `lidar_stream.py` take `--bind` (default `0.0.0.0`, compatible with the previous behaviour). The hub relays `/camera` and `/lidar` on the server side, so 127.0.0.1 is enough with `--local`. No unauthenticated streaming port is opened on wlan0 or eth0.
- **State location**: the ctl scripts put the pid and log in `G1_CTL_STATE_DIR` (by default next to the script, as before). `--local` uses `~/.g1console/run/`, so the repository is not polluted.
- **Camera port**: the `camera_port` setting is now passed to the ctl script (previously only for the LiDAR).
- **Decision**: the streamers are not stopped when the hub exits (a streamer may outlive the hub; stopping is done with "Stop" in the UI). Decide separately if a different operation is wanted.
- **Checked once** (2026-10-18, one run, see J23 in the checklist): start and stop on the Jetson, ports free while stopped, loopback-only listening. **Unverified**: repeatability, other Jetsons or firmware, and contention for the video device (`videohub_pc4`).
