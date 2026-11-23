"""Decide "is arm control enabled" and "are the legs autonomous" from the observed mode and telemetry (read only; does not touch the G1).

Arms: motor_state[i].mode of rt/lowstate (1 = enabled / 0 = zero torque). Not the mode of the command side rt/lowcmd
    (lowcmd only keeps the last command sent and does not represent the current enabled state).
Legs: whether the standard motion service (motion controller) is running and controlling the legs.
    Zero Torque and Damping are not autonomous even if the service is running. Debug mode is not autonomous.

label is a short verdict shown large in the UI; detail is the reason (shown small).
"""

from g1console.modes import FSM_LABELS

LEG_JOINTS = range(0, 12)
ARM_JOINTS = range(15, 29)
NOT_AUTONOMOUS_FSM = frozenset((0, 1))  # Zero Torque, Damping
JOINTS_STALE_S = 3.0  # a lowstate older than this is not used for the decision
CMD_LIVE_S = 1.0  # if a lowcmd arrived within this many seconds, "commands are flowing"


def _modes(joints, indexes):
    """List of motor_state.mode of the given joints. None if unavailable."""
    if not joints:
        return None
    age = joints.get("age_s")
    if age is None or age > JOINTS_STALE_S:
        return None
    items = joints.get("items") or []
    if len(items) <= max(indexes):
        return None
    values = [items[i].get("mode") for i in indexes]
    return None if any(v is None for v in values) else values


def _arm(telemetry):
    total = len(ARM_JOINTS)
    modes = _modes((telemetry or {}).get("joints"), ARM_JOINTS)
    if modes is None:
        return {"state": "unknown", "label": "Unknown", "detail": "Joint state is not being received",
                "enabled_count": None, "total": total, "commanded": None}
    enabled = sum(1 for m in modes if m == 1)
    cmd_age = ((telemetry or {}).get("ages") or {}).get("rt/lowcmd")
    commanded = cmd_age is not None and cmd_age <= CMD_LIVE_S
    if enabled == total:
        state, label = "enabled", "Enabled"
        detail = "Motors %d/%d · %s" % (enabled, total, "receiving commands" if commanded else "no commands")
    elif enabled == 0:
        state, label = "disabled", "Disabled"
        detail = "Zero Torque. It becomes enabled when you enter Damping with the remote controller"
    else:
        state, label, detail = "partial", "Partial only", "Motors %d/%d enabled" % (enabled, total)
    return {"state": state, "label": label, "detail": detail,
            "enabled_count": enabled, "total": total, "commanded": commanded}


def _legs(mode, telemetry):
    modes = _modes((telemetry or {}).get("joints"), LEG_JOINTS)
    enabled = None if modes is None else sum(1 for m in modes if m == 1)
    state = (mode or {}).get("state")
    fsm_id = (mode or {}).get("fsm_id")
    if state == "ok" and fsm_id is not None:
        name = FSM_LABELS.get(fsm_id, "Unknown")
        if fsm_id in NOT_AUTONOMOUS_FSM:
            result, label, detail = "not_autonomous", "Not autonomous", "%s · FSM %s" % (name, fsm_id)
        else:
            result, label, detail = "autonomous", "Autonomous", "Motion controller in control · %s · FSM %s" % (name, fsm_id)
    elif state == "debug":
        result, label, detail = "not_autonomous", "Not autonomous", "Debug mode (motion controller stopped)"
    else:
        result, label, detail = "unknown", "Unknown", "The mode is not available"
    return {"state": result, "label": label, "detail": detail, "fsm_id": fsm_id if state == "ok" else None,
            "enabled_count": enabled, "total": len(LEG_JOINTS)}


def control_summary(mode, telemetry):
    """{"arm": ..., "legs": ...}. If the mode or telemetry is missing, each item has state="unknown"."""
    return {"arm": _arm(telemetry), "legs": _legs(mode, telemetry)}
