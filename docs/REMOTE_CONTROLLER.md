# The physical remote controller's functions, and where the console fits

## Role

The web console builds on **what the G1's physical remote controller (R3) can do, extends it, and realizes it through the SDKs**.
The physical remote controller sends its input directly to the robot body (it does not go through the SDK), so the console re-creates the meaning of each remote controller operation as an SDK API call.

The basic functions the console provides, and their current state (the `verified` flag of each is `FEATURES` in [`modes.py`](../g1console/modes.py)):

| # | Basic function | Status | Real-robot verification |
|---|---|---|---|
| 1 | Connection status (hub → Jetson → G1) | Implemented | Unverified (checklist A1) |
| 2 | Automatic reconnection (the screen retries every 1 s, the hub every 3 s while the Jetson is unreachable) | Implemented | Unverified |
| 3 | Mode switching | Implemented (7 modes, limited transitions; see below) | Unverified except Zero Torque to Damping, confirmed through the console on 2026-10-24 (1.1 s) |
| 4 | Actions (wave, handshake) | Implemented (`--local` or `--mock` only) | Unverified (the `SetTaskId` numbers are inferred) |
| 5 | Movement (joystick, arrow keys, Q/E) | Implemented (`--local` or `--mock` only) | The operator reported success on a real robot in Regular Mode (2026-10-24). The speed limits are unverified |
| 6 | Battery display | Implemented | The operator reported it confirmed (2026-10-18; the compared values were not recorded) |

**The screen must always show "not implemented" on functions that are not implemented, and "unverified on a real robot" on functions that have not been tried on a real robot.**
The definition of these states is kept in one place, `FEATURES` in [`modes.py`](../g1console/modes.py); the screen reads it and draws from it.

## Sources and confidence

| Source | Content | Confidence |
|---|---|---|
| Unitree "G1 Remote Control User Manual V1.1" (R3 remote controller, 12 pages; "the manual" below) | The remote controller's functions and button assignments | Official. But it is an **image-only PDF** and was transcribed by eye. Page numbers are given |
| Operator's report (a reseller's operating guide, secondary; not cited here) | The current firmware's R3 key assignments (L2 family), power-on procedure | Secondary. **On 2026-10-24 the operator judged it "probably the current specification"**. It has not been cross-checked against official material. Not tested on a real controller |
| `unitree_ros2/example/src/include/g1/g1_loco_client.hpp` (the SDK's C++ example) | `LocoClient` API IDs, arguments and high-level wrappers | SDK source. Not run on a real robot |
| Real robot (read-only check on 2026-09-30) | `GetFsmId=501`, `CheckMode name=ai` | Measured. **Only these two state reads were confirmed** |

### FSM IDs the console uses

The console sends FSM IDs, not button combinations. The labels are in `FSM_LABELS` and the buttons in `BUTTONS` in `g1console/modes.py`.

| FSM ID | State | Source |
|---|---|---|
| 0 | Zero Torque | `g1_loco_client.py` in `unitree_sdk2_python` |
| 1 | Damping | same |
| 3 | Seated Mode | same |
| 4 | Locked Standing | Observed on the real robot after entering it with the remote controller (2026-10-18, repeated 2026-10-24). Sending it from the console is unverified |
| 500 / 501 | Regular Mode (1-axis waist / 3-axis waist) | 500 from the SDK, 501 from official-manual-derived material. The real robot returned 501 |
| 702 | Lie -> Stand | SDK |
| 706 | Squat <-> Stand | SDK |

### Warning: conflict with earlier notes (reconciled on the operator's judgment on 2026-10-24; not yet confirmed by pressing keys on the real controller)

**The operator's judgment (2026-10-24)**: the L1-family table (the "Mode switching" table below, a transcription from another site and an eye transcription of this manual) is an **old specification and differs from the current robot**.
**The current robot uses the L2-family table in the next section** (from the operator's report). The L1 family is kept as history, to avoid confusion.

#### Key assignments of the current robot (L2 family; source: the operator's report; as of 2026-10-24)

"Short press" is a normal press and "long press" is holding for 2 seconds. The assignments can change with the firmware version (the sticker on the remote controller is authoritative).

| Mode | Keys | Type and notes |
|---|---|---|
| Zero moment (= Zero Torque) | L2 + Y | Short press. The robot falls unless it is hanging from a gantry |
| Damping | L2 + B | Short press. For stopping. Holding it for 5 seconds while walking triggers damping protection (the robot lowers itself slowly) |
| Locked Standing | L2 + Up | Short press |
| Lie -> Stand | L2 + X | Short press. Flat, hard floor only |
| Seated Mode | L2 + Left | Long press |
| Squat <-> Stand | L2 + A | Long press |
| Running Mode | R2 + A | Long press |
| Regular Mode (1-axis waist) | R1 + X | Long press. G1-U1 |
| Regular Mode (3-axis waist) | R1 + Y | Long press. G1-U2 and later. This robot was confirmed on the real robot to return 501 (3-axis) (2026-10-24) |
| Speed (Regular), slow / fast | double-click L2 / L1 | Short press. **The correspondence to the `SetSpeedMode` values is unverified** |
| Speed (Running), slow / fast | R2 + Up / Down | Short press |
| Stepping / standing | double-click START | Short press |
| Climb mode | R2 + B | Long press |
| Debug mode | L2 + R2 (to check whether it is on, L2 + A) | Only for SDK development |

Start-up procedure (from a seated posture, recommended): power on → Damping → Locked Standing → Running / Regular → demo → Seated Mode → power off.
Right after start-up all joints are in Zero Torque. On this robot the console's Zero Torque to Damping transition was confirmed on the real robot (2026-10-24, 1.1 s).

#### History of the conflict

An earlier note this project relied on (a different source from the SDK sources of the FSM IDs above) said
"L2+B damping, L2+Y zero torque, L2+UP locked standing, R1+X regular mode", but
**the manual for the R3 uses the L1 family** (zero torque L1+B, damping L1+A, locked standing L1+UP), and the assignments do not match.
It is likely a difference between remote controller generations (R3 and earlier), but this has **not been confirmed**.
The console sends an **FSM ID**, not a button combination, so operation is not affected. A reader of the tables should not confuse the two.

## Physical remote controller (R3) specification (manual pp. 1-5)

| Item | Content |
|---|---|
| Communication | Digital transmission module + Bluetooth. At first use, enter the remote controller ID in the Unitree Explore app under Settings to bind. After that it connects automatically at power-on |
| Connection indicator | The **DL** indicator on the right lights when it is connected to the robot |
| Range / run time | 100 m or more (open space) / 5 hours (780 mAh) |
| Power | Short press the power button, then hold for 2 seconds or more: ON (2 beeps) / OFF (3 beeps) |
| Auto power-off | After power-on, if it is connected to neither the robot nor the app and is not operated, it **turns off after 10 minutes** |
| Stick calibration | Without touching the sticks, press and release F1+F3 at the same time → beep (once per second) → turn both sticks fully several times → when the beeping stops, confirm with F3 |
| Vibration / sound | Press F3 quickly 3 times to switch vibration and sound. Press F1 quickly 3 times to turn vibration/sound ON or OFF. The setting is not saved by default; to save it, keep F1 pressed when powering off |
| Charging / battery level | USB-C (5V/2A recommended). **The remote controller's own** battery level is shown by 4 LEDs on the body (0-25 / 25-50 / 50-75 / 75-100 % / fully charged) |

Warning: the remote controller's battery level cannot be read from the SDK (physical LEDs only). The battery the console shows is that of the **robot body**.

## Operation functions (manual pp. 5-11)

### Sticks and keys (in "main operation" mode)

| Input | Action | Source |
|---|---|---|
| Left stick forward / back | Move forward / backward (the figure shows only forward and back; the overview text also mentions sideways movement) | p.5 |
| Right stick right / left | Turn right / left (in place) | p.6 |
| Y / X | Raise / lower the standing height | p.6 |
| B / A | Raise / lower the leg lift height (foot lift per step) | p.6 |
| START | Continuous walking <-> standing | p.6 |

### Concepts (p.7)

| Concept | Description |
|---|---|
| Zero torque mode | All motors stop actively driving. There is no resistance (no damping feel) when the robot is shaken |
| Damping mode | All motors stop actively driving. There is a clear damping feel when shaken. From here the robot can enter ready mode |
| **Ready mode** | Within 5 seconds, slowly takes the preparation posture before the motion mode. This is Locked Standing (`Lock stand`, L1+UP) |
| Squat mode | Slowly squats within 5 seconds (no balance control) |
| Seated mode | Slowly sits within 5 seconds (no balance control) |
| Motion mode | A mode in which movement is controlled with the remote controller |
| Continuous walking mode | Always stepping in place |
| Standing mode | If the stick input is 0, the robot stops stepping and stands. If the input is not 0, or if a disturbance is about to make it lose balance, it starts stepping |
| **Debug mode** | For low-level development. When developing and debugging with the SDK, **put the G1 into debug mode to avoid command conflicts with the motion control program**. Whether it is on can be checked with L2+A |

### Mode switching (pp. 8-9)

Button assignments:

| Posture change | Buttons |
|---|---|
| Debug mode | Hold L2 and press R2 |
| Zero torque | Hold L1 and press B |
| Damping (1) | L1 + A |
| Locked Standing = ready (2) | L1 + UP |
| Seated (4) | L1 + LEFT |
| Squat | L1 + DOWN |
| Lying <-> standing (5) | L1 + X |
| Squat toggle (6) | L1 + Y |

Transition diagram (read from the figure on p.8; check the original figure for details):

```
Power on → Zero torque ─L1+A→ Damping ─L1+B→ Zero torque
Damping ─L1+UP→ Ready ─R1+X / R2+X→ Main operation
Damping ─L1+DOWN→ Squat     Damping ─L1+LEFT→ Seated
Main operation ─L1+A→ Damping (the emergency stop route)
Main operation ─L1+DOWN→ Squat / ─L1+LEFT→ Seated
Lying posture <-> main operation: L1+X       Squat posture <-> main operation: L1+Y
Damping in regular mode ─L2+R2→ Damping in debug mode
  Inside debug: Damping <-> Zero torque (L2+B), Damping <-> diagnostic motion (L2+A)
```

Warning: after leaving main operation with squat (L1+Y), to return to main operation without powering off,
operate L1+A (damping) and then L1+Y, in that order (note on p.8).

### Interaction (p.9)

| Function | Buttons |
|---|---|
| Wave | SELECT + Y |
| Handshake | SELECT + A |
| Turn around and wave | SELECT + X |

### Key tables by operation mode (pp. 9-11)

The manual's headings have a duplicated circled number (there are two "3"). The table below follows the headings literally.

| Mode | Keys | Action |
|---|---|---|
| **R2+X (Run)** | B / A | Leg lift height up / down |
| | Y / X | Standing height up / down |
| | R1 + left stick | Slow running |
| | R2 + left stick | Fast running |
| **R1+X (main operation)** | double-click START | Keep stepping (not recommended) |
| | START | Stand |
| | double-click L2 / double-click L1 | Slow mode / fast mode |
| | While holding R1: right / left / down / up | Offset correction to the left / right / front / back |
| **R1+Y (3-DoF-waist robots only)** | double-click START / START | Keep stepping (not recommended) / stand |
| | double-click L2 / L1 | Slow / fast mode |
| | While holding R1: right / left / down / up | Offset correction (same notation as R1+X) |
| **R2+Y (3-DoF-waist robots only)** | B / A / Y / X | Leg lift height up / down, standing height up / down |
| | START | Keep stepping (not recommended) / stand |
| | Right stick while holding SELECT | **Waist control** |

For robots with a 3-DoF waist, the R1+Y mode is recommended (p.10). This robot returned `GetFsmId=501`.
`FSM_LABELS` in `g1console/modes.py` labels 501 as Regular Mode (3-axis waist), so the R1+Y table is expected to apply to this robot, but that is an **inference**.

### Start-up procedure and cautions (pp. 10-11)

- Normal start-up: power on → (1) damping → (2) locked standing → (3) main operation → (demo) → (4) seated → power off
- Start-up from the lying posture: (1) → (5) → demo → (6) → power off (**the hip post must be level with the ground**)
- Start-up from the lying or squat posture is for **flat, hard ground only**. Elsewhere, standing up is unstable
- With a dexterous hand attached, start-up from the lying or squat posture easily damages the hand
- **The current walking mode cannot climb stairs.** Do not make the robot climb stairs
- Obstacles such as walls and doors greatly weaken the remote controller's radio signal. Use it in an open space

## Remote controller function -> how to do it with the SDK

The source is `g1_loco_client.hpp` (API IDs and arguments). **The "mapping" is partly inferred from names, and none of it has been confirmed on a real robot.**

| Remote controller function | SDK means (candidate) | Real-robot verification | Notes |
|---|---|---|---|
| Show the current mode | `GetFsmId` (7001), `MotionSwitcherClient.CheckMode` | Read only, confirmed | Normal: `501` / `ai`. In debug mode `GetFsmId`=3102 and `CheckMode`=`(0, {'form':'0','name':''})` (measured 2026-09-30) |
| Zero torque / damping / seated | `SetFsmId(0)` / `(1)` / `(3)` | No (except Zero Torque to Damping, see above) | Implemented in the console |
| Squat | `SetFsmId(2)` (`Squat()` in the C++ example). The Python SDK also has `Squat2StandUp` / `StandUp2Squat` (706) | No | The relation between 2 and 706 is not sorted out |
| Ready (locked standing) | `StandUp()` in the C++ example is `SetFsmId(4)`. **2026-10-18, real robot: `fsm_id`=4 was confirmed right after entering locked standing with the remote controller (once only). The screen shows "Locked Standing"** | No | Sending it from the console is unverified |
| Main operation (can walk) | `SetFsmId(500)` (`Start()`) / 501 (the value measured on a 3-axis-waist robot) | No | Whether `SetFsmId` can enter 501 is unverified |
| Stand up from lying | `SetFsmId(702)` (`Lie2StandUp`) | No | Implemented |
| Movement (left stick, right stick) | `SetVelocity(vx, vy, omega, duration)` (7105) / `Move` / `StopMove` | The operator reported success (2026-10-24) | Implemented. Because of `duration`, sending short durations repeatedly gives "stops when released" |
| Standing height (Y / X) | `SetStandHeight` (7104), `GetStandHeight` (7005) | No | Not implemented |
| Leg lift height (B / A) | `SetSwingHeight` (7103), `GetSwingHeight` (7004) | No | Not implemented |
| Continuous walking <-> standing (START) | `SetBalanceMode` (7102) / `ContinuousGait(flag)` | No | The mapping is inferred from the names |
| Slow / fast mode | `SetSpeedMode` (7107) | No | The mapping is inferred from the names. The console offers it as "Speed 0 / Speed 1" |
| Wave / turn around and wave | `WaveHand(turn_flag)` = `SetTaskId(0 / 1)` | No | Implemented |
| Handshake | `ShakeHand(stage)` = `SetTaskId(2 / 3)` (two steps) | No | Implemented |
| Run (R2+X) | `SetFsmId(801)` appears in only one source | No | Unconfirmed officially. Not implemented |
| Switch to debug mode | `MotionSwitcherClient.ReleaseMode` | No | A failure is hard to recover from. Be careful. Not implemented |
| Waist control (SELECT + right stick) | Not investigated (arms and waist may use a different API or low-level control) | - | Not investigated |
| Offset correction (R1 + arrows) | The matching API has not been investigated | - | Not investigated |
| **The robot's battery** | `unitree_hg` has a `BmsState` type (`soc`, `current`, `bmsvoltage`, `temperature` and others). **Which topic publishes it was unconfirmed** | Yes, obtained | **`rt/lf/bmsstate`** (measured: SOC, current, voltage, cell voltages, temperature). Shown in the console. The units mV/mA are inferred; at SOC below 5% the robot stops within a few minutes |
| The remote controller's battery level | Cannot be read (physical LEDs only) | - | Out of scope |

## Arrow-key movement (implemented)

The keys are assigned to the equivalent of the remote controller sticks (`KEY_AXES` in `web/ui-core.js`).

| Key | Assignment |
|---|---|
| Up / Down | Forward / backward (`vx`). Equivalent to the left stick forward and back |
| Left / Right | Sideways to the left / right (`vy`). Equivalent to the left stick left and right |
| Q / E | Turn left / right (`omega`). Equivalent to the right stick. **Separate keys from translation** |
| Pressing the above together | Combined (for example turning while moving diagonally). Opposite keys pressed together cancel to 0 |
| Releasing a key, losing focus, losing the connection | Stop immediately |

Safe-side design: the method is to **repeatedly send `SetVelocity` with a short duration** (0.2 s; see [DESIGN.md](DESIGN.md) section 4).
Even if the console dies or the Jetson is cut off, the robot stops when the last command's duration expires.
Movement is enabled only in "main operation" (FSM 500/501). The speed limits are initial values and are unverified on a real robot.

## Open items

1. The difference in assignments between remote controller generations (L1 family / L2 family; see above)
2. The FSM IDs and switching procedures for Ready (locked standing from the console), Run and debug
3. What happens when `SetFsmId` is pressed on a real robot (how many seconds a transition takes, and whether it conflicts with a walking relay on the Jetson)
4. (Resolved) The battery was confirmed to be published on `rt/lf/bmsstate`. Remaining: the units, and the condition for `battery_alarm` to fire (it did not fire even at SOC 0%)
5. The API for waist control and offset correction
6. A safe procedure for switching to debug mode through `MotionSwitcherClient`
7. `rt/arm_sdk` in normal mode (`ai`) (it had no effect in debug mode; it must be retested in normal mode)
8. Which of the old and new remote controller assignments applies (`ai_sport` 8.7.3.4 alone cannot tell). On 2026-10-24 the operator judged the L2 family to be the current specification. Confirmation by pressing keys on the real controller is not done
9. The correspondence between the `SetSpeedMode` numbers and slow/fast (the test on 2026-10-24 was aborted because the buttons did not respond)
10. What Adapt rise (R1 + R2 + X) does. Measured on 2026-10-24 (G1 hanging from a gantry, in Damping, monitored by reading only):
    - On receiving key value `1041` (equal to the sum of the X + R2 + R1 bits), the FSM became **1001** and returned to Damping (1) about 1 second later (reproduced 3 times).
    - The robot said "robot rising" and said "damp mode" when it returned (as heard by the operator).
    - There was no change in posture (IMU). Because the robot was hanging from a gantry and there was nothing to rise from, the actual motion was not observed.
    - Other key values checked: X alone `1024`, L2 + B `544` (no change while in Damping).
    - The operator's table gives only the name and the combination, with no explanation. Whether to try it with the robot fallen will be decided after safety is confirmed.
    - The operator's report (2026-10-24): it behaves like Lie -> Stand and **is used with the robot on its back**. The lack of motion while hanging from a gantry can be read as the robot not being on its back (a test on its back has not been done on a real robot).
11. The meaning of FSM 802. Measured on 2026-10-24:
    - After running Damping then Lie -> Stand (702) from the console, `GetFsmId` was **802**, the service was `ai`, and the legs were autonomous.
    - Sending Squat <-> Stand (706) from 802 gave `set_code` 0, the FSM became 706 after 1.0 s, and it switched automatically to Damping (1) after 8.2 s (a 20-second recording).
    - One source (secondary) says "since `ai_sport` 8.6.x.x, Run changed from 801 to 802". Whether 802 is Run, or just the state right after standing up, is unconfirmed. The screen name stays "FSM ID 802".
    - Whether the robot can go from 802 to Regular Mode (501) has not been tested.
12. Climb mode (R2 + B). The operator's report on 2026-10-24: it seems to be a mode for going up and down stairs, but it is not used normally. When actually pressed, the robot **kept stepping in place** (it did not stop).
    - A secondary source (the MYBOTSHOP forum) also has one account that "the legs only moved up and down without climbing, and the robot could only return to Damping". It may be the same behavior.
    - How it was stopped (the operator's report): **switching to Regular Mode stopped it**. Damping was not used.
    - The FSM ID during Climb was not recorded. **No button is placed in the console.**
