import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from cloud_storage import CloudClient, CloudError, CloudSync, Outbox, telemetry_line, start_optional_cloud, load_config

STAMP = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)


class FakeCloud:
    def __init__(self):
        self.writes = []
        self.error = None

    def write(self, lines):
        self.writes.extend(lines)
        if self.error:
            raise self.error


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "outbox.sqlite3"
        self.outbox = Outbox(self.path, max_records=2)
        self.client = FakeCloud()
        self.sync = CloudSync(self.client, self.outbox)

    def tearDown(self):
        self.outbox.close()
        self.temp.cleanup()

    def test_sensor_only_and_nulls(self):
        line = telemetry_line("uno", {"a1_distance_cm": None, "a1_occupied": None}, STAMP)
        self.assertIn("a1_distance_cm_valid=false", line)
        self.assertNotIn("a1_distance_cm=", line)
        self.assertNotIn("a1_occupied=", line)
        self.assertIsNone(telemetry_line("camera", {"license_plate": "test"}, STAMP))

    def test_durable_restart_and_bounded_capacity(self):
        self.assertEqual(self.outbox.put([("one", 1), ("two", 2), ("three", 3)]), 1)
        self.outbox.close()
        self.outbox = Outbox(self.path, max_records=2)
        self.assertEqual([r[1] for r in self.outbox.batch()], ["one", "two"])
        self.assertEqual(self.outbox.depth(), 2)

    def test_retry_identical_records(self):
        self.outbox.put([("one", 1)])
        self.client.error = CloudError(429, 20)
        with self.assertRaises(CloudError):
            self.sync.send(self.outbox.batch())
        self.assertEqual(self.outbox.depth(), 1)
        self.client.error = None
        self.sync.send(self.outbox.batch())
        self.assertEqual(self.client.writes, ["one", "one"])
        self.assertEqual(self.outbox.depth(), 0)

    def test_permanent_record_isolated(self):
        self.outbox.put([("one", 1), ("two", 2)])
        def write(lines):
            if "two" in lines:
                raise CloudError(422)
        with patch.object(self.client, "write", side_effect=write):
            self.sync.send(self.outbox.batch())
        self.assertEqual(self.outbox.depth(), 0)
        self.assertEqual(self.sync.snapshot()["dropped"], 1)

    def test_expire_and_duplicate(self):
        self.outbox.put([("same", 1), ("same", 1)])
        self.assertEqual(self.outbox.depth(), 1)
        self.assertEqual(self.outbox.expire(2), 1)

    def test_synthetic_never_uses_production_config(self):
        with patch("cloud_storage.load_config", side_effect=AssertionError):
            self.assertEqual(start_optional_cloud("synthetic", "parking", "sensor_data"), (None, None))
            self.assertEqual(start_optional_cloud("hardware", "parking/test", "sensor_data"), (None, None))

    def test_query_gaps_and_validation(self):
        client = CloudClient({"bucket":"parking_sensor_test"})
        stop = datetime.fromtimestamp(600, timezone.utc)
        result = {"results":[{"series":[{"columns":["time","value","valid_samples","samples"],
                                         "values":[[540, 20, 1, 1],[541, 21, 0, 1]]}]}]}
        with patch.object(client, "request", return_value=json.dumps(result).encode()):
            points = client.history("uno","a1_distance_cm",1,stop=stop)["points"]
            self.assertEqual(len(points), 60)
            self.assertEqual([p["value"] for p in points[:3]], [20, None, None])
            with self.assertRaises(ValueError):
                client.history("camera", "confidence", 1)

    def test_bad_config(self):
        path = Path(self.temp.name) / "config.json"
        path.write_text(json.dumps({"url":"https://evil.example","bucket":"parking_sensor_data",
                                    "free_plan_confirmed":True,"read_token":"x","write_token":"y"}))
        with self.assertRaises(ValueError):
            load_config(path)

if __name__ == "__main__":
    unittest.main()
