"""Decisions on whether arm control is enabled and whether the legs are autonomous (g1console/control.py). Does not touch the robot.
Cases that match the real-robot observation of 2026-10-18 (motor_state.mode in lowstate is 0 for all joints / the arms become 1 after enabling)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from g1console.control import control_summary  # noqa: E402

DEBUG = {"state": "debug", "label": "Debug mode", "service": ""}


def telemetry(arm_mode=1, leg_mode=0, age=0.1, cmd_age=None, with_mode=True):
    items = []
    for i in range(29):
        item = {"q": 0.0, "dq": 0.0, "tau": 0.0, "temperature": [30, 30], "lost": 0}
        if with_mode:
            item["mode"] = arm_mode if 15 <= i < 29 else leg_mode
        items.append(item)
    return {"joints": {"age_s": age, "mode_machine": 5, "items": items}, "ages": {"rt/lowcmd": cmd_age}}


class ArmTest(unittest.TestCase):
    def test_all_arm_motors_enabled(self):
        arm = control_summary(DEBUG, telemetry(arm_mode=1, cmd_age=0.2))["arm"]
        self.assertEqual((arm["state"], arm["enabled_count"], arm["commanded"]), ("enabled", 14, True))

    def test_all_zero_is_disabled_even_if_lowcmd_says_enabled(self):
        # the mode in lowcmd only keeps the last command. If the state side is 0, it is disabled
        tele = telemetry(arm_mode=0, cmd_age=88.0)
        tele["lowcmd"] = {"age_s": 88.0, "items": [{"mode": 1, "kp": 80.0}] * 29}
        arm = control_summary(DEBUG, tele)["arm"]
        self.assertEqual((arm["state"], arm["enabled_count"], arm["commanded"]), ("disabled", 0, False))

    def test_partial(self):
        tele = telemetry(arm_mode=1)
        tele["joints"]["items"][20]["mode"] = 0
        arm = control_summary(DEBUG, tele)["arm"]
        self.assertEqual((arm["state"], arm["enabled_count"]), ("partial", 13))

    def test_unknown_when_stale_missing_or_old_helper(self):
        self.assertEqual(control_summary(DEBUG, telemetry(age=10.0))["arm"]["state"], "unknown")
        self.assertEqual(control_summary(DEBUG, None)["arm"]["state"], "unknown")
        self.assertEqual(control_summary(DEBUG, telemetry(with_mode=False))["arm"]["state"], "unknown")
        self.assertEqual(control_summary(DEBUG, {"joints": {"age_s": 0.1, "items": []}})["arm"]["state"], "unknown")


class LegsTest(unittest.TestCase):
    def test_walking_is_autonomous(self):
        legs = control_summary({"state": "ok", "fsm_id": 501, "label": "Normal walking (3-axis waist)"}, telemetry(leg_mode=1))["legs"]
        self.assertEqual((legs["state"], legs["fsm_id"], legs["enabled_count"]), ("autonomous", 501, 12))

    def test_zero_torque_and_damping_are_not_autonomous(self):
        for fsm_id in (0, 1):
            legs = control_summary({"state": "ok", "fsm_id": fsm_id}, telemetry())["legs"]
            self.assertEqual(legs["state"], "not_autonomous", fsm_id)

    def test_debug_mode_is_not_autonomous(self):
        legs = control_summary(DEBUG, telemetry())["legs"]
        self.assertEqual((legs["state"], legs["fsm_id"]), ("not_autonomous", None))

    def test_unknown_when_mode_missing(self):
        for mode in ({"state": "none"}, {"state": "unknown"}, {"state": "ok"}, None):
            self.assertEqual(control_summary(mode, None)["legs"]["state"], "unknown", mode)


if __name__ == "__main__":
    unittest.main()
