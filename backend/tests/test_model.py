import json
import unittest
from model import Source, validate

NODE = {"node": "uno", "a1_distance_cm": 10.0, "m1_distance_cm": None,
        "a1_occupied": True, "m1_occupied": None, "vibration": None,
        "vibration_count": None, "vibration_status": "not_installed"}
GATEWAY = {"node": "esp32", "temperature_c": 23.8, "humidity_pct": 63.8,
           "light_raw": 597, "gas_raw": 489, "gas_status": "unconditioned_or_uncalibrated"}

class ModelTests(unittest.TestCase):
    def test_both_real_schemas(self):
        for topic, msg in (("parking/node/telemetry", NODE), ("parking/gateway/telemetry", GATEWAY)):
            self.assertEqual(validate(topic, json.dumps(msg))[1], msg)

    def test_null_distance_clears_numeric_current_value(self):
        s = Source("uno")
        s.accept(NODE, 10)
        s.accept(dict(NODE, a1_distance_cm=None, a1_occupied=None), 11)
        current = s.snapshot(11)
        self.assertNotIn("a1_distance_cm", current)
        self.assertFalse(current["a1_distance_cm_valid"])
        self.assertEqual(current["a1_state"], 0)
        self.assertFalse(current["a1_allocation_eligible"])

    def test_staleness_and_recovery(self):
        s = Source("uno")
        self.assertEqual(s.snapshot(0)["a1_state"], 0)
        s.accept(dict(NODE, a1_occupied=False, a1_distance_cm=30), 20)
        self.assertTrue(s.snapshot(29)["a1_allocation_eligible"])
        self.assertFalse(s.snapshot(30)["fresh"])
        self.assertNotIn("a1_distance_cm", s.snapshot(30))
        self.assertFalse(s.snapshot(30)["a1_allocation_eligible"])
        s.accept(NODE, 31)
        self.assertEqual(s.snapshot(31)["a1_state"], 2)

    def test_missing_sensor_never_allocated(self):
        s = Source("uno")
        s.accept(NODE, 0)
        for now in (0, 15):
            self.assertEqual(s.snapshot(now)["m1_state"], 3)
            self.assertFalse(s.snapshot(now)["m1_allocation_eligible"])

    def test_malformed_payload_invalidates_current(self):
        s = Source("uno")
        s.accept(NODE, 1)
        s.reject(2)
        self.assertFalse(s.snapshot(2)["payload_valid"])
        self.assertEqual(s.snapshot(2)["a1_state"], 0)

    def test_invalid_inputs(self):
        invalid = [dict(NODE, a1_occupied=1), dict(NODE, a1_distance_cm=True),
                   dict(NODE, m1_occupied=False), dict(NODE, a1_distance_cm=None),
                   dict(NODE, a1_distance_cm=float("nan")), dict(NODE, extra=1)]
        for msg in invalid:
            with self.subTest(msg=msg), self.assertRaises(ValueError):
                validate("parking/node/telemetry", json.dumps(msg))
        for payload in ('{}', '{bad}', '{"node":"uno","node":"uno"}'):
            with self.assertRaises(ValueError):
                validate("parking/node/telemetry", payload)
        with self.assertRaises(ValueError):
            validate("parking/node/telemetry", json.dumps(GATEWAY))
        with self.assertRaises(ValueError):
            validate("parking/gateway/telemetry", json.dumps(dict(GATEWAY, light_raw=1.2)))

    def test_camera_is_advisory_and_validated(self):
        msg={"node":"camera","slot":"M1","occupied":False,"confidence":.9}
        self.assertEqual(validate("parking/camera/result",json.dumps(msg))[0],"camera")
        source=Source("camera");source.accept(msg,0)
        self.assertEqual(source.snapshot(0)["camera_state"],1)
        self.assertFalse(source.snapshot(0)["allocation_eligible"])
        with self.assertRaises(ValueError):
            validate("parking/camera/result",json.dumps(dict(msg,confidence=2)))

if __name__ == "__main__":
    unittest.main()
