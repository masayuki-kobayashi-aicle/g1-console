"""verified / caution in task definitions, and the caution dialog for unverified features. Does not touch the robot."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from g1console.modes import FEATURES  # noqa: E402
from g1console.tasks import load_definitions  # noqa: E402

CONSOLE = Path(__file__).resolve().parent.parent
from web_source import source
HTML = source()
ROBOT_FREE = {"run-tests", "sample-countdown"}  # they touch neither the robot nor the Jetson, so verified=true is set


def shipped():
    return load_definitions(CONSOLE / "tasks", CONSOLE)


class TaskDefinitionTest(unittest.TestCase):
    def _load(self, raw):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.json").write_text(json.dumps(raw), encoding="utf-8")
            return load_definitions(d, d)["x"]

    def test_t7_1_defaults_are_unverified_without_caution(self):
        d = self._load({"argv": ["echo"]})
        self.assertIs(d.verified, False)
        self.assertEqual(d.caution, ())

    def test_t7_1_verified_and_caution_are_validated(self):
        ok = self._load({"argv": ["echo"], "verified": True, "caution": ["a", "b"]})
        self.assertEqual((ok.verified, ok.caution), (True, ("a", "b")))
        bad = [{"verified": "yes"}, {"verified": 1}, {"caution": "text"}, {"caution": [1]}, {"caution": [""]},
               {"caution": ["x"] * 9}, {"caution": ["x" * 201]}]
        for extra in bad:
            with self.subTest(extra):
                with self.assertRaises(ValueError):
                    self._load({"argv": ["echo"], **extra})

    def test_t7_1_view_carries_verified_and_caution(self):
        from g1console.tasks import TaskRunner
        defs = {"x": self._load({"argv": ["echo"], "caution": ["be careful"]})}
        defs.update(shipped())
        view = {t["name"]: t for t in TaskRunner(defs, CONSOLE).list()["tasks"]}
        self.assertEqual(view["x"]["verified"], False)
        self.assertEqual(view["x"]["caution"], ["be careful"])
        self.assertEqual(view["run-tests"]["verified"], True)


class ShippedTasksTest(unittest.TestCase):
    def test_t7_2_only_robot_free_tasks_are_marked_verified(self):
        self.assertEqual({n for n, d in shipped().items() if d.verified}, ROBOT_FREE)


class WebCautionTest(unittest.TestCase):
    def _func(self, name):
        m = re.search(r"(?:async )?function %s\(.*?\n\}\n" % name, HTML, re.S)
        self.assertTrue(m, name)
        return m.group(0)

    def test_t7_4_dialog_has_the_parts_the_script_uses(self):
        self.assertIn('<dialog id="caution"', HTML)
        for i in ("ca-title", "ca-unver", "ca-note", "ca-lines", "ca-check", "ca-checkbox", "ca-ok", "ca-cancel"):
            self.assertIn('id="%s"' % i, HTML, i)
        self.assertIn('id="ca-cancel" type="submit" autofocus', HTML)  # the default choice is "cancel"

    def test_t7_4_dialog_text_is_never_parsed_as_html(self):
        body = self._func("askCaution") + self._func("guard")
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("insertAdjacentHTML", body)
        self.assertIn("textContent", body)

    def test_t7_4_checkbox_gates_the_ok_button(self):
        body = self._func("askCaution")
        self.assertIn("ok.disabled=!!o.needCheck", body)
        self.assertIn("ok.disabled=!e.target.checked", body)
        self.assertIn("returnValue==='ok'", body)  # Esc and "cancel" do not execute

    def test_t7_4_unknown_feature_counts_as_unverified(self):
        self.assertIn("unverified=!f||!f.verified", self._func("guard"))

    def test_t7_5_every_robot_action_button_asks_first(self):
        wired = {"setMode": "guard('mode'", "speak": "guard('audio'", "setLed": "guard('audio'",
                 "camProc": "guard('camera'", "ldProc": "guard('lidar'", "moClaim": "guard('move'",
                 "moAction": "guard('action'"}
        for fn, call in wired.items():
            with self.subTest(fn):
                body = self._func(fn)
                self.assertIn(call, body)
                self.assertLess(body.index(call), body.index("fetch(") if "fetch(" in body else len(body))
        self.assertIn("guard('topics'", HTML)

    def test_t7_5_task_buttons_ask_for_unverified_or_cautioned_tasks(self):
        body = self._func("tkAct")
        self.assertIn("!t.verified||t.caution.length", body)
        self.assertIn("needCheck:t.caution.length>0", body)
        self.assertLess(body.index("askCaution"), body.index("tkApi('/api/tasks/'"))
        self.assertRegex(self._func("tkCard"), r"tag\('[^']+','unver'\)")  # the unverified badge (text is a UI label, so only the tag kind is checked)

    def test_hub_stop_button_asks_before_posting(self):
        body = HTML[HTML.index("$('hub-stop').onclick"):]
        body = body[:body.index("};") + 2]
        self.assertIn("guard('hubstop'", body)
        self.assertIn("needCheck:true", body)
        self.assertLess(body.index("guard('hubstop'"), body.index("/api/hub/stop"))

    def test_t7_6_guarded_features_exist_and_are_unverified(self):
        by_id = {f["id"]: f for f in FEATURES}
        guarded = set(re.findall(r"guard\('(\w+)'", HTML))
        self.assertTrue(guarded <= set(by_id), guarded - set(by_id))
        for fid in guarded - {"move"}:  # move was verified on the real robot on 2026-10-24
            self.assertIs(by_id[fid]["verified"], False, fid)
            self.assertTrue(by_id[fid]["implemented"], fid)


if __name__ == "__main__":
    unittest.main()
