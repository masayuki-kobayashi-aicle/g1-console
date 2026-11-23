# Items to check the next time a real robot is connected

Do not set `verified` to true in `FEATURES` in `g1console/modes.py` until it has been confirmed on a real robot.
Safety procedure: at least 2 people, `L2 + B` (on the physical remote controller) within reach, a clear area around the robot, and the robot hanging from a gantry or seated.
Write the date and the value into the `[ ]` of each row.

Preconditions: battery SOC 30% or more (the robot stops within a few minutes at SOC below 5%) / you can log in to the Jetson /
start `python3 server.py --local` on the Jetson and open `http://127.0.0.1:18790/`.

## A. Read only (nothing moves) - do this first

| # | Check | Expected | Result |
|---|---|---|---|
| A1 | The 3-stage connection in the header is shown correctly as "hub → Jetson → G1". The display matches reality when the G1 is powered off, the Jetson is cut off, and in debug mode | State and diagnostic text match reality (the display reflects a disconnect within 15 seconds = the give-up threshold) | [ ] |
| A2 | The battery % in the header matches the G1's actual level display (remote controller / body). Compare the voltage and current units (mV/mA) against the power supply's display | SOC within ±2 points of the display. Voltage within ±1 V of the power supply's display (around 40 V) | [x] 2026-10-18 the operator reported it confirmed on the real robot (the compared values were not recorded) |
| A3 | The look of the main navigation and the screen switching inside it, direct `#hash` links, and breakage on a narrow screen (the navigation was reorganized on 2026-10-18; no visual check done) | No horizontal scroll at 360 px width, all screens reachable, a direct `#hash` link opens the matching screen | [ ] |
| A4 | `GET /api/state` `/api/joints` `/api/snapshot` return the same values as the screen | Values match | 2026-10-18 real robot (Jetson `--local`, normal mode fsm_id=501, SOC 57%): the mode in `/api/state` and `/api/snapshot` matched, and `/api/joints` had 29 rows. A visual comparison with the screen was not done [ ] |
| A5 | The return value of `CheckMode` in normal mode (`name` / `form`) and `GetFsmId` (in debug mode `CheckMode`=`(0,{'form':'0','name':''})` and `GetFsmId`=`(3102, None)`, which was the RPC return code, so the ID could not be read) | Record it | 2026-10-18 real robot (Jetson `--local`, normal mode fsm_id=501, SOC 57%): `GetFsmId` through the hub was 4 in locked standing, and 501 after switching to normal mode with the remote controller (the first record of confirming 501 through the console). `service`=ai. The raw `name`/`form` of `CheckMode` were not recorded [ ] |
| A6 | Joint name mapping: move one joint at a time by hand (lightly, with power on and the joint limp via `L2+B`) and check which row moves | For every joint moved, it matches `JOINT_NAMES` (0 mismatches) | [ ] |
| A7 | The main board `value` (meaning of the third value 1.0 to 1.7), `state`=[32,…], `temperature`=50, `fan_state` | Record the meaning | 2026-10-18 real robot (Jetson `--local`, normal mode fsm_id=501, SOC 57%): `mainboard.value`=[49.31, 49.01, 2.0, 0, 0, 0] (different from the earlier third value 1.0 to 1.7), `state`=all 0, `temperature`=[53,0,…], `fan_state`=all 0. The meaning is unconfirmed (values 1 and 2 are close to a voltage, but that is a guess) [ ] |
| A8 | The origin of the internal lowcmd, and whether lowcmd exists in normal mode (it was published at 200 Hz in debug mode) | Record it | 2026-10-18 real robot (Jetson `--local`, normal mode fsm_id=501, SOC 57%): `rt/lowcmd` is received in normal mode (age 0.0 s). The origin is not identified and the frequency was not measured [ ] |
| A9 | Whether `rt/lf/*` is a low-rate copy (frequency and content match) | Frequency and values within 1% of `rt/lowstate` | [ ] |
| A10 | The remote controller input (`wirelesscontroller`) and emergency stop (`emergency_stop`) appear on the screen. The value changes when the remote controller is pressed | The value on the screen changes within 1 second of the press | [ ] |
| A11 | Which remote controller assignment, old or new, applies (does `L2+B` make the robot limp, or `L1+A`? `ai_sport` 8.7.3.4) | Record the version | [ ] |
| A12 | Whether `battery_alarm` fires at low charge (it did not fire even at SOC 0%). Whether `servicestateactivate`, `multiplestate` and `selftest` appear under any condition | Record it | 2026-10-18 real robot (Jetson `--local`, normal mode fsm_id=501, SOC 57%): `battery_alarm`, `rt/servicestateactivate`, `multiplestate` and `selftest` were not received (null). `rt/servicestate` was received once (ai_sport version 8.7.3.4). Firing at low charge is unconfirmed [ ] |

## B. Operation in normal mode

| # | Check | Expected | Result |
|---|---|---|---|
| B1 | Low-risk `SetFsmId` such as seated or damping works, and "in transition → arrived" is shown | Record the seconds to arrival | Partial: 2026-10-18 the operator reported "Zero Torque → Damping" confirmed on the real robot (no seconds or other transitions recorded). 2026-10-24 real robot (Jetson `--local`, hanging from a gantry, SOC 46%): sent `POST /api/mode {"id":1}` once from the console, and it reached Damping(1) from Zero Torque(0) in **1.1 seconds** (`set_code=0`, posture change 0.001 rad or less). Other transitions such as seated, and a visual check of the "in transition → arrived" display, were not done. The rest is [ ] |
| B2 | With the physical remote controller in use, a mode changed with the remote controller is followed by the console (the display does not disagree) | It follows | Partial: 2026-10-24 real robot: changed Damping(1) → Zero Torque(0) and Damping(1) → Locked Standing(4) with the remote controller, and `mode.fsm_id` in `/api/state` followed (detected by reading every 0.5 seconds). A precise measurement of the follow time and a visual check of the screen were not done [ ] |
| B2a | Locked Standing (FSM 4): enter it with the remote controller and read the ID and leg state | Record the ID | 2026-10-24 real robot (hanging from a gantry): Damping(1) → **Locked Standing(4)** (matches the 2026-10-18 record). The legs went from "not autonomous" to "autonomous", and the rpy change was 0.06 rad or less. Whether FSM 4 can be sent from the console is unconfirmed (it is not registered in the allowed IDs). `body_height` stayed 0.0 (meaning unconfirmed) |
| B3 | Standing up → entering main operation (500/501). Whether the ID differs between the 1-axis and 3-axis waist versions | Record it | [ ] |
| B4 | The FSM IDs and procedures for ready (locked standing), Run and switching to debug (the reason they are not implemented) | Record the ID | [ ] |
| B5 | Damping can be pressed during a transition (the emergency stop is not blocked) | It can be pressed | [ ] |

## C. Audio, LED and text to speech

| # | Check | Expected | Result |
|---|---|---|---|
| C1 | Change the volume and the read-back matches, and the sound actually changes (the original was 85) | Match plus listening | [ ] |
| C2 | Sending an LED color changes the color (visual). **The default color in normal mode is remembered as blue. It is now still the changed color** | The color changes | [ ] |
| C3 | Whether the LED returns after a reboot (persistence). The color in debug mode (yellow) and the normal color | Record it | [ ] |
| C4 | Text to speech produces sound. At the same time, `play_state` 1→0 of `rt/audio_msg` can be observed (usable to detect the end of TTS) | Sound plus event | [ ] |
| C5 | The difference between speaker ID 0 and 1, the 100-character limit, whether Japanese works | Record it | [ ] |
| C6 | Microphone: whether a sentence actually spoken appears in `text` of `audio_msg` (a misrecognition appeared even in silence; `confidence` is fixed at 0.5). Whether `angle` changes | Record it | [ ] |

## D. Arms (normal mode only; clear the arm range of motion)

| # | Check | Expected | Result |
|---|---|---|---|
| D3 | Run one arm action (`G1ArmActionClient.ExecuteAction`) (`release_arm` 99, then from small motions). The change of `holding/id/name` in `rt/arm/action/state` | The state changes | [ ] |
| D4 | Whether `GetActionList` (27 kinds) matches the real robot, and the meaning of the `mode_machine` 5/6 premise | Record it | [ ] |

## E. Walking (last; hanging from a gantry or with enough space)

| # | Check | Expected | Result |
|---|---|---|---|
| E1 | Whether sending `SetVelocity` continuously with a short duration gives "stops when released". The delay until it stops | Within a few hundred ms | [ ] |
| E2 | The assignment (arrows = forward/back/left/right, Q/E = turn) and the upper limits of maximum speed. The assignment is implemented; the limits are initial values | Decide the limits | [ ] |
| E3 | Whether the robot stops when the connection is cut (turn off Wi-Fi/VPN). Whether the console's stop method is adequate | It stops | [ ] |
| E4 | Walk with the motion screen (`claim` → pad). Whether `SetVelocity` is accepted continuously at the hub's 20 Hz with `duration=0.2` (the helper's response time, and whether `HELPER_TIMEOUT_S`=1.0 s is enough). The limits (vx -0.2 to 0.3, vy ±0.2, wz ±0.4) are initial values | Walks smoothly. No timeouts | [ ] |
| E5 | The robot stops on lifting the finger, switching to another tab, screen lock and a radio dropout of about 0.5 seconds, and does not resume by itself. Measure the stopping distance | It stops | [ ] |
| E6 | One operator with 2 phones. How well the emergency stop (floating button) works, and a measurement of the delay of queuing behind a `move` being sent (a design limit) | It stops. Record the delay | [ ] |
| E7 | The numbers and the actual motions of the actions (`SetTaskId` 0 wave / 1 wave_turn / 2 shake_start / 3 shake_end). **The numbers are inferred** | Record the motions | [ ] |

## F. Peripherals (if time allows)

- Camera: start `camera_stream.py` on the Jetson and see it in the console with `--camera-url`.
- LiDAR: whether the reception bandwidth of `rt/utlidar/cloud_livox_mid360` holds over Wi-Fi/VPN (4.4 MB/s). If it does not, thin it out on the Jetson.
- Whether the robot has Dex3 hands (no `rt/dex3/*` data this time).
- Show `rt/audio_msg` on the screen (not started).

## G. Debug mode and low-level control (**first while hanging from a gantry, one joint at a time, with a small gain**)

| # | Check | Pass condition | Result |
|---|---|---|---|
| G1 | Whether debug mode can be entered while seated (the official documentation mentions only hanging from a gantry) | Record whether it can or cannot be entered. Even if it can, do not try it while seated | [ ] |
| G2 | Whether the diagnostic posture of `L2 + A` matches the official video. Whether the LED turns yellow | The posture matches and the LED is yellow | [ ] |
| G3 | Whether "return to the zero position in the first 3 seconds" in the ankle sample `g1_ankle_swing_example.cpp` affects only the legs or all joints (**read the source first**) | Identify the target joints before running | [ ] |
| G4 | `rt/arm_sdk`: in a usable state (locked stand, normal operation 1/2), interpolate the weight (index 29) from 0 to 1 | The arm follows the command with no sudden motion | [ ] |
| G5 | The procedure to stop the built-in arm control service (not documented in this repository) | It stops, with no conflict | [ ] |
| G6 | Whether `rt/sportmodestate` (`fsm_id` / `fsm_mode`) arrives (firmware 1.5.1 or later) | Values arrive and match the mode | [ ] |
| G7 | The procedure to return from debug mode to normal mode, and `CheckMode` after returning | It returns to normal mode and `CheckMode` is normal | [ ] |

## H. Camera (G1 powered on, manual start and stop only)

For the D435i RGB, the plan is to stop using the method of opening `/dev/video4` with OpenCV and switch to the **official `VideoClient.GetImageSample()`**.

| # | Check | Pass condition | Result |
|---|---|---|---|
| H1 | Get RGB with `VideoClient.GetImageSample()` and show it in the console's camera screen (replace the source in `camera_stream.py`) | It shows for 1 minute continuously. A capture failure recovers or stops within 5 seconds | [ ] |
| H2 | Check with `fuser -v /dev/video4` and `ps` that `videohub_pc4` holds the device (**do not stop or kill it**) | Record the holder | [ ] |
| H3 | For the additional USB camera (SunplusIT): **start the G1 with it unplugged, and plug it in after the built-in video returns**. Whether it appears in `lsusb` and `/dev/v4l/by-id` | It appears. The built-in video does not drop | [ ] |
| H4 | `import` of `pyrealsense2` (system Python 3.8, 2.55.1) and `rs.context().devices` (it may conflict with videohub, so only once, after H2) | Record the result (abort if it conflicts) | [ ] |
| H5 | `ROS_DOMAIN_ID` / `RMW_IMPLEMENTATION` / `CYCLONEDDS_URI`, whether librealsense and GStreamer exist, OpenCV build information, and the Jetson's time and time zone (it was about 1 hour off from the operator's PC) | Record the values | [ ] |
| H6 | `camera_ctl.sh start → check video → stop → status` shows "stopped" | Confirm it is stopped | [ ] |

Rules:
- The camera streaming server is **started and stopped by hand only**. Do not create anything that runs all the time or restarts automatically (systemd / cron / a loop).
- Do not stop `videohub_pc4` (an operator reported that it was restarted by a watchdog even after being stopped).
- Do not run `ros2 topic list` on the G1 (it failed with `bad_alloc`, and `_ros2_daemon` used about 7 GB). Check liveness by reading DDS directly.
- `camera_stream.py` keeps re-opening a camera it cannot open at 2-second intervals. If it cannot open it, run `stop`.

## J. Resident hub on the Jetson and phone connection

| # | Check | Expected | Result |
|---|---|---|---|
| J1 | On the Jetson (Python 3.8), `python3 server.py --local --bind-iface wlan0` starts and finds `~/unitree_sdk2_python` | It starts and the state appears | [ ] |
| J2 | `--bind-iface wlan0` obtains the IP. How often the IP changes with DHCP | Record it | [ ] |
| J3 | A person installs and enables `jetson/g1-console.service` (not automated). It starts automatically after a reboot | It starts | [ ] |
| J4 | From a phone, `http://<wlan0 IP>:18790/?token=…` opens, and the token is no longer needed afterwards thanks to the cookie | It opens | [ ] |
| J5 | The eth0 address (the robot's internal LAN) is not reachable | Not reachable | [ ] |
| J6 | From another device, no token or a wrong token gives 401. Five failures lock it | Rejected | [ ] |
| J7 | No horizontal scroll at 360 px width, and the main navigation can be pressed | No breakage | [ ] |
| J9 | From the tasks screen, `sample-countdown` can be run, stopped and its log shown. `run-tests` passes on the Jetson (Python 3.8) | It works | [ ] |
| J10 | Under systemd, `systemctl stop g1-console` leaves no task child behind | None remain | [ ] |
| J16 | With a `--local` hub, subscribe to `rt/rtc/state` (String_) from the DDS screen, and the value and "how many seconds ago" appear. A topic whose type cannot be read (such as a point cloud) is refused with 422. The helper does not start until a subscription is made (check with `ps`) | It appears / it is refused | [ ] |
| J17 | Put only a harmless existing String_ topic in `--topics-file`, publish, and observe it on the receiving side (for example a subscription from another device). If `rt/lowcmd` is written into the allowlist, the hub does not start. The allowlist cannot be extended from the screen or the API | It is observed / it does not start | [ ] |
| J22 | Caution dialog (also at 360 px width): it appears when a button for an unverified function (mode, audio, LED, camera, LiDAR, motion, action, topic publish, task) is pressed. "Cancel" is the default, it cannot be run until the check is ticked, and Esc closes it with nothing happening | It appears / it can be operated | [ ] |
| J23 | With a `--local` hub, right after start `ss -ltn` does not show 8081 or 8082 (off by default). Start the camera and LiDAR from the screen (dialog → run) → they listen only on `127.0.0.1:8081` and `:8082` (not on 0.0.0.0 or wlan0), and video and a point cloud can be seen on a phone. Stopping frees both ports. The pid and log are in `~/.g1console/run/` (nothing is added to `jetson/`). A streamer that was already started remains when the hub is restarted | As expected | 2026-10-18 confirmed on the real robot (Jetson Python 3.8.10, a `git clone` version). Right after start, neither 8081 nor 8082 was in use. With the same POST as the screen, starting the LiDAR → only `127.0.0.1:8082` (real data of 16 bytes × the number of points was obtained through the hub), starting the camera → only `127.0.0.1:8081` (an MJPEG of d435i and depth was obtained; `std` is not in the ctl default `--camera`, so 502). Stopping freed both ports, and the pid and log are in `~/.g1console/run/`, so `jetson/` stays clean. **Unverified**: the look on a phone, whether a streamer remains after the hub is restarted, and the `std` camera. Found and fixed a defect where `lidar_ctl.sh` lacked the execute permission after a clone and could not start. [x] |
| J24 | "Stop the hub" in the settings screen: dialog (check required, "Cancel" is the default) → stop → `pgrep` shows the hub gone and port 18790 free. While a task is running or an operator lock is held, it does not stop (409). Under systemd (after installation) it does not restart. Record whether the camera and LiDAR streamer processes remain (expected to remain; unconfirmed). It can be pressed on a phone (360 px) | It stops | [ ] |
| J25 | The header's status card (also at 360 px on a phone): the arm motors "enabled N/14" match the actual arm state (limp = 0/14, after enabling = 14/14). In debug mode it shows "standard motion service = released" and "debug mode = yes" | Matches the real robot, no breakage | [ ] |

## When done

1. Fill in the results in the tables above.
2. Set `verified` in `FEATURES` in `g1console/modes.py` to `True` only for the functions that were confirmed (do not change it on a guess).
