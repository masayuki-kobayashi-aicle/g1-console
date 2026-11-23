"""Console tests. No real robot or ssh is needed (MockHelper and the standard library only)."""
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g1console.dds_catalog import DISPLAYED, SERVICES, TOPICS  # noqa: E402
from g1console.motion import MockSender, MotionController  # noqa: E402
from g1console.modes import validate_audio, ALLOWED_IDS, BUTTONS, FEATURES, FSM_LABELS, JOINT_NAMES, PLANNED_MODES  # noqa: E402
from g1console.tasks import TaskRunner, load_definitions  # noqa: E402
from g1console.topics import MockTopicBackend, TopicService  # noqa: E402
from g1console.camera_proc import MockCameraCtl  # noqa: E402
from g1console.lidar_proc import MockLidarCtl  # noqa: E402
from g1console.lidar_sensor import MockSensorCtl  # noqa: E402
from server import MockHelper, Monitor, SshHelper, describe, make_handler  # noqa: E402
from g1console.settings import Settings, validate  # noqa: E402

G1_TIMEOUT = {"ok": True, "checkmode_code": 3102, "service": None, "fsm_code": 3102, "fsm_id": None}


class DescribeTest(unittest.TestCase):
    def test_known_fsm_id_is_labeled(self):
        out = describe({"ok": True, "checkmode_code": 0, "service": "ai", "fsm_code": 0, "fsm_id": 501})
        self.assertEqual(out["jetson"]["state"], "ok")
        self.assertEqual(out["g1"]["state"], "ok")
        self.assertEqual(out["mode"]["state"], "ok")
        self.assertEqual(out["mode"]["label"], FSM_LABELS[501])

    def test_unknown_fsm_id_is_not_hidden(self):
        out = describe({"ok": True, "checkmode_code": 0, "service": "ai", "fsm_code": 0, "fsm_id": 12345})
        self.assertEqual(out["mode"]["state"], "ok")
        self.assertEqual(out["mode"]["label"], "Unknown")
        self.assertEqual(out["mode"]["fsm_id"], 12345)

    def test_empty_service_name_is_debug_mode_and_g1_reachable(self):
        out = describe({"ok": True, "checkmode_code": 0, "service": "", "fsm_code": 3102, "fsm_id": None})
        self.assertEqual(out["g1"]["state"], "ok")
        self.assertEqual(out["mode"]["state"], "debug")

    def test_ssh_failure_means_jetson_down_and_g1_unverified(self):
        out = describe({"ok": False, "offline": True, "ssh_exit": 255, "error": "x"})
        self.assertEqual(out["jetson"]["state"], "down")
        self.assertIn("255", out["jetson"]["detail"])
        self.assertEqual(out["g1"]["state"], "unknown")
        self.assertEqual(out["mode"]["state"], "none")

    def test_dds_timeout_means_g1_down_while_jetson_ok(self):
        out = describe(G1_TIMEOUT)
        self.assertEqual(out["jetson"]["state"], "ok")
        self.assertEqual(out["g1"]["state"], "down")
        self.assertEqual(out["mode"]["state"], "none")

    def test_reachable_but_no_fsm_id_is_unknown_mode_not_ok(self):
        out = describe({"ok": True, "checkmode_code": 0, "service": "ai", "fsm_code": 7, "fsm_id": None})
        self.assertEqual(out["g1"]["state"], "ok")
        self.assertEqual(out["mode"]["state"], "unknown")


class ButtonsTest(unittest.TestCase):
    def test_every_button_id_is_allowed_and_labeled(self):
        for b in BUTTONS:
            self.assertIn(b["id"], ALLOWED_IDS)
            self.assertIn(b["id"], FSM_LABELS)


class FeaturesTest(unittest.TestCase):
    def test_unverified_or_unimplemented_is_never_marked_verified(self):
        for f in FEATURES:
            if not f["implemented"]:
                self.assertFalse(f["verified"], f["id"])

    def test_only_user_confirmed_features_are_marked_verified(self):
        # only features the user reported as confirmed on the real robot are verified. When adding more, record it with a date.
        self.assertEqual({f["id"] for f in FEATURES if f["verified"]}, {"battery", "telemetry", "move"})  # 2026-10-18 (for move, the user confirmed success on the real robot on 2026-10-24)

    def test_planned_modes_are_not_switchable(self):
        planned = {p["label"] for p in PLANNED_MODES}
        self.assertFalse(planned & {b["label"] for b in BUTTONS})

    def test_ids_are_unique(self):
        ids = [f["id"] for f in FEATURES]
        self.assertEqual(len(ids), len(set(ids)))


class DdsCatalogTest(unittest.TestCase):
    def test_topics_are_unique_and_status_known(self):
        names = [t[0] for t in TOPICS]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({t[2] for t in TOPICS} <= {"displayed", "todo", "excluded"})
        self.assertEqual(len(TOPICS), 65)  # the 104 discovered minus the 39 service request/response topics

    def test_displayed_topics_match_helper_subscriptions(self):
        # the topics remote_helper.py subscribes to must match the displayed list
        src = (Path(__file__).resolve().parent.parent / "jetson" / "remote_helper.py").read_text(encoding="utf-8")
        for name in (t[0] for t in TOPICS if t[2] == DISPLAYED):
            self.assertIn('"%s"' % name, src)
        self.assertEqual(len([t for t in TOPICS if t[2] == DISPLAYED]), 18)

    def test_services_have_names(self):
        self.assertEqual(len({v[0] for v in SERVICES}), len(SERVICES))
        self.assertEqual(len(SERVICES), 25)  # number of kinds of rt/api/<name> discovered


class AudioValidationTest(unittest.TestCase):
    def test_valid_requests_become_helper_ops(self):
        self.assertEqual(validate_audio("volume", {"volume": 60}), {"op": "audio_volume", "volume": 60})
        self.assertEqual(validate_audio("led", {"r": 0, "g": 255, "b": 3})["op"], "audio_led")
        self.assertEqual(validate_audio("tts", {"text": "Hello", "speaker_id": 0})["op"], "audio_tts")

    def test_out_of_range_or_wrong_type_is_rejected(self):
        bad = [("volume", {"volume": 101}), ("volume", {"volume": -1}), ("volume", {"volume": "50"}),
               ("volume", {"volume": True}), ("volume", {}), ("led", {"r": 256, "g": 0, "b": 0}),
               ("led", {"r": 0, "g": 0}), ("tts", {"text": "", "speaker_id": 0}),
               ("tts", {"text": "a" * 101, "speaker_id": 0}), ("tts", {"text": "a", "speaker_id": 7}),
               ("nope", {})]
        for kind, body in bad:
            with self.assertRaises(ValueError, msg=(kind, body)):
                validate_audio(kind, body)


class MonitorTest(unittest.TestCase):
    def test_before_first_poll_nothing_is_claimed_connected(self):
        snap = Monitor(MockHelper()).snapshot()
        self.assertIsNone(snap["sampled_at"])
        self.assertIsNone(snap["age_s"])
        self.assertEqual(snap["g1"]["state"], "unknown")

    def test_snapshot_reports_age_and_latency(self):
        mon = Monitor(MockHelper())
        mon.poll_once()
        time.sleep(0.05)
        snap = mon.snapshot()
        self.assertGreaterEqual(snap["age_s"], 0.05)
        self.assertIsNotNone(snap["latency_ms"])
        self.assertTrue(snap["server"]["mock"])

    def test_last_known_mode_survives_disconnect(self):
        helper = MockHelper()
        mon = Monitor(helper)
        mon.poll_once()
        helper.scenario = "g1_off"
        snap = mon.poll_once()
        self.assertEqual(snap["g1"]["state"], "down")
        self.assertEqual(snap["mode"]["state"], "none")
        self.assertEqual(snap["last_mode"]["fsm_id"], 1)

    def test_snapshots_are_replaced_not_mutated(self):
        mon = Monitor(MockHelper())
        first = mon.poll_once()
        second = mon.poll_once()
        self.assertIsNot(first, second)
        self.assertLessEqual(first["sampled_at"], second["sampled_at"])


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = MockHelper()
        cls.settings = Settings(None)
        cls.monitor = Monitor(cls.helper)
        cls.monitor.poll_once()
        console = Path(__file__).resolve().parent.parent
        cls.tasks = TaskRunner(load_definitions(console / "tasks", console), console)
        cls.tmp = tempfile.mkdtemp(prefix="g1console-test-")
        allow = {"rt/console_demo/say": {"topic": "rt/console_demo/say", "type": "String_", "max_bytes": 64, "min_interval_s": 0.1, "note": ""}}
        cls.topics = TopicService(MockTopicBackend(), allow)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.helper, cls.monitor, None, cls.settings, MockCameraCtl(), MockLidarCtl(),
                                                                   motion=MotionController(MockSender(), lambda: (501, 0.1)),
                                                                   tasks=cls.tasks, topics=cls.topics,
                                                                   lidar_sensor=MockSensorCtl(),
                                                                   hub_stop=lambda: None))  # do not actually stop with the example send
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.tasks.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.helper.scenario = "ok"

    def _post(self, path: str, body: bytes):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=body, method="POST")
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def _status(self):
        return json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/status" % self.port, timeout=5))

    def test_status_carries_links_and_freshness(self):
        s = self._status()
        for key in ("jetson", "g1", "mode", "age_s", "latency_ms", "poll_interval_s", "server"):
            self.assertIn(key, s)

    def test_allowed_mode_is_sent_and_reached_after_transition(self):
        code, _ = self._post("/api/mode", json.dumps({"id": 3}).encode())
        self.assertEqual(code, 200)
        time.sleep(MockHelper.TRANSITION_S + 0.2)
        self.monitor.poll_once()
        self.assertEqual(self._status()["mode"]["fsm_id"], 3)

    def test_disallowed_id_is_rejected_before_reaching_helper(self):
        code, _ = self._post("/api/mode", json.dumps({"id": 999}).encode())
        self.assertEqual(code, 400)

    def test_malformed_body_is_rejected(self):
        self.assertEqual(self._post("/api/mode", b"not json")[0], 400)
        self.assertEqual(self._post("/api/mode", json.dumps({"x": 1}).encode())[0], 400)

    def test_set_is_reported_as_failure_when_g1_unreachable(self):
        self.helper.scenario = "g1_off"
        code, _ = self._post("/api/mode", json.dumps({"id": 3}).encode())
        self.assertEqual(code, 502)

    def test_scenario_switch_is_reflected_immediately(self):
        code, _ = self._post("/api/scenario", json.dumps({"scenario": "jetson_off"}).encode())
        self.assertEqual(code, 200)
        self.assertEqual(self._status()["jetson"]["state"], "down")
        self.assertEqual(self._post("/api/scenario", json.dumps({"scenario": "nope"}).encode())[0], 400)

    def test_features_endpoint_lists_planned_items(self):
        d = json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/dds" % self.port, timeout=5))
        self.assertEqual(len(d["topics"]), 65)
        self.assertEqual(d["topics"][0]["status"], "displayed")
        self.assertTrue(d["services"])
        j = json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/features" % self.port, timeout=5))
        self.assertEqual({f["id"] for f in j["features"]},
                         {"connection", "reconnect", "mode", "speed", "action", "move", "tasks", "topics", "battery", "audio", "telemetry", "sensors", "camera", "lidar", "lidar_sensor", "hubstop"})
        self.assertTrue(j["planned_modes"] and j["actions"])
        self.assertEqual(j["planned_actions"], [])  # there are no unimplemented actions (the shape is kept)

    def test_volume_set_is_read_back_and_verified(self):
        self.assertEqual(json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/audio/volume" % self.port))["volume"], 85)
        code, body = self._post("/api/audio/volume", json.dumps({"volume": 40}).encode())
        self.assertEqual((code, body["volume_after"]), (200, 40))
        self._post("/api/audio/volume", json.dumps({"volume": 85}).encode())

    def test_led_and_tts_are_accepted_but_bad_input_is_400(self):
        self.assertEqual(self._post("/api/audio/led", json.dumps({"r": 1, "g": 2, "b": 3}).encode())[0], 200)
        self.assertEqual(self._post("/api/audio/tts", json.dumps({"text": "test", "speaker_id": 0}).encode())[0], 200)
        self.assertEqual(self._post("/api/audio/led", json.dumps({"r": 999, "g": 0, "b": 0}).encode())[0], 400)
        self.assertEqual(self._post("/api/audio/volume", b"not json")[0], 400)

    def test_audio_is_reported_as_failure_when_g1_unreachable(self):
        self.helper.scenario = "g1_off"
        self.assertEqual(self._post("/api/audio/led", json.dumps({"r": 1, "g": 2, "b": 3}).encode())[0], 502)

    def test_settings_roundtrip_and_validation(self):
        code, body = self._post("/api/settings", json.dumps({"jetson_host": "192.168.123.164", "g1_ip": "192.168.123.161"}).encode())
        self.assertEqual(code, 200)
        self.assertEqual(body["settings"]["jetson_host"], "192.168.123.164")
        got = json.load(urllib.request.urlopen("http://127.0.0.1:%d/api/settings" % self.port, timeout=5))
        self.assertEqual(got["settings"]["g1_ip"], "192.168.123.161")
        for bad in ({"jetson_host": "-oProxyCommand=x"}, {"g1_ip": "999.1.1.1"}, {"camera_port": "0"}, {"jetson_user": "a b"}):
            self.assertEqual(self._post("/api/settings", json.dumps(bad).encode())[0], 400, bad)

    def test_pause_stops_background_checks_and_can_resume(self):
        self.assertEqual(self._post("/api/monitor", b'{"paused": true}')[1], {"paused": True})
        self.assertTrue(self._status()["paused"])
        before = self._status()["sampled_at"]
        time.sleep(0.01)
        self.assertEqual(self._post("/api/monitor", b'{"check": true}')[0], 200)  # a manual single check works
        self.assertGreater(self._status()["sampled_at"], before)
        self.assertEqual(self._post("/api/monitor", b'{"paused": false}')[1], {"paused": False})

    def _api_doc(self):
        return json.load(urllib.request.urlopen("http://127.0.0.1:%d/api" % self.port, timeout=5))

    def test_every_documented_response_matches_its_schema_in_every_scenario(self):
        from schema_check import check
        doc = self._api_doc()
        comps = doc["components"]["schemas"]
        for scenario in ("ok", "g1_off", "jetson_off", "debug"):
            self.helper.scenario = scenario
            self.monitor.poll_once()
            for path, methods in doc["paths"].items():
                op = methods.get("get")
                if not op or "{" in path or path in ("/openapi.yaml", "/api/scenarios"):
                    continue
                try:
                    r = urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=5)
                    code, body = r.status, json.load(r)
                except urllib.error.HTTPError as e:
                    code, body = e.code, json.load(e)
                self.assertIn(str(code), op["responses"], "%s %s: undefined code %s" % (scenario, path, code))
                schema = op["responses"][str(code)]["content"]["application/json"]["schema"]
                self.assertEqual(check(body, schema, comps), [], "%s %s" % (scenario, path))

    def test_documented_requests_are_accepted_and_bad_ones_are_400(self):
        from schema_check import check
        doc = self._api_doc()
        comps = doc["components"]["schemas"]
        for path, methods in doc["paths"].items():
            op = methods.get("post")
            if not op or path == "/api/scenario" or "requestBody" not in op:  # POSTs without a body (camera start/stop) are out of scope
                continue
            content = op["requestBody"]["content"]["application/json"]
            self.assertEqual(check(content["example"], content["schema"], comps), [], path)  # the example matches the schema
            code, body = self._post(path, json.dumps(content["example"]).encode())
            self.assertIn(str(code), op["responses"], "%s -> %s" % (path, code))
            self.assertEqual(check(body, op["responses"][str(code)]["content"]["application/json"]["schema"], comps), [], path)
            if "400" in op["responses"]:
                self.assertEqual(self._post(path, b"not json")[0], 400, path)
        self._post("/api/audio/volume", b'{"volume": 85}')  # restore the mock volume changed by the example send

    def test_every_route_in_the_spec_exists_and_openapi_yaml_is_served(self):
        doc = self._api_doc()
        self.assertEqual(doc["openapi"], "3.0.3")
        ids = [op["operationId"] for m in doc["paths"].values() for op in m.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("openapi", urllib.request.urlopen("http://127.0.0.1:%d/openapi.yaml" % self.port, timeout=5).read().decode())
        for path, methods in doc["paths"].items():
            if "post" in methods and path != "/api/scenario":
                self.assertNotEqual(self._post(path, b"{}")[0], 404, path)

    def test_generated_api_docs_are_up_to_date(self):
        from g1console.api_spec import render_markdown, render_yaml
        docs = Path(__file__).resolve().parent.parent / "docs"
        self.assertEqual((docs / "API.md").read_text(encoding="utf-8"), render_markdown(), "regenerate with python3 g1console/api_spec.py")
        self.assertEqual((docs / "openapi.yaml").read_text(encoding="utf-8"), render_yaml(), "regenerate with python3 g1console/api_spec.py")

    def test_index_html_is_served(self):
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=5).read().decode()
        self.assertIn("G1 Control", html)

    def test_every_tab_has_button_and_panel_in_html(self):
        from g1console.modes import TABS
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=5).read().decode()
        for name in TABS:
            self.assertIn('id="tab-b-%s"' % name, html)
            self.assertIn('id="tab-%s"' % name, html)
        self.assertIn('id="bat-soc"', html)  # battery % is always shown in the header

    def test_tab_apis_return_the_same_data_as_the_screen(self):
        self.helper.scenario = "debug"
        self.monitor.poll_once()
        get = lambda path: json.loads(urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=5).read())
        state, joints, snap = get("/api/state"), get("/api/joints"), get("/api/snapshot")
        self.assertIn("soc", state["battery"])
        self.assertIn("units_assumed", state["notes"])
        self.assertEqual(len(joints["items"]), 29)
        self.assertEqual(joints["items"][0]["name"], JOINT_NAMES[0])
        self.assertIsNotNone(joints["items"][0]["cmd"])
        self.assertEqual(snap["state"]["battery"]["soc"], state["battery"]["soc"])
        self.assertEqual(snap["tabs"], ["ops", "motion", "action", "state", "joints", "audio", "tasks", "camera", "dds", "settings"])


if __name__ == "__main__":
    unittest.main()


class CameraProxyTest(unittest.TestCase):
    """Set up a fake upstream instead of camera_stream.py and check the /camera/<name> relay."""

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                self.wfile.write(b"--frame\r\nFRAMEDATA")

            def log_message(self, *args):
                pass

        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        helper = MockHelper()
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(helper, Monitor(helper), "http://127.0.0.1:%d" % cls.upstream.server_address[1]))
        cls.off = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(helper, Monitor(helper)))
        for srv in (cls.upstream, cls.server, cls.off):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.upstream, cls.server, cls.off):
            srv.shutdown()

    def test_known_camera_is_relayed_with_upstream_content_type(self):
        with urllib.request.urlopen("http://127.0.0.1:%d/camera/std" % self.server.server_address[1]) as r:
            self.assertIn("multipart/x-mixed-replace", r.headers["Content-Type"])
            self.assertIn(b"FRAMEDATA", r.read())

    def test_unknown_camera_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen("http://127.0.0.1:%d/camera/nope" % self.server.server_address[1])
        self.assertEqual(ctx.exception.code, 404)

    def test_without_camera_url_it_is_disabled(self):
        url = "http://127.0.0.1:%d/api/cameras" % self.off.server_address[1]
        with urllib.request.urlopen(url) as r:
            self.assertFalse(json.loads(r.read())["enabled"])


class SettingsTest(unittest.TestCase):
    def test_saved_file_survives_restart_and_broken_file_falls_back(self):
        import tempfile
        path = Path(tempfile.mkdtemp()) / "settings.json"
        Settings(path).update({"jetson_host": "jetson.local", "jetson_user": "unitree", "jetson_key": "~/k"})
        again = Settings(path)
        self.assertEqual(again.ssh_target(), ("unitree@jetson.local", "~/k"))
        self.assertEqual(again.camera_base(), "http://jetson.local:8081")
        path.write_text("{broken")
        self.assertIsNone(Settings(path).ssh_target()[0])

    def test_ipv6_and_hostname_validation(self):
        self.assertEqual(validate({"jetson_host": "::1"})["jetson_host"], "::1")
        self.assertEqual(validate({"jetson_host": "my-jetson"})["jetson_host"], "my-jetson")
        with self.assertRaises(ValueError):
            validate({"jetson_host": "1.2.3"})

    def test_unconfigured_ssh_helper_reports_offline_without_spawning(self):
        raw = SshHelper(None).call({"op": "status"})
        self.assertTrue(raw["unconfigured"])
        self.assertIn("not set", describe(raw)["jetson"]["detail"])
