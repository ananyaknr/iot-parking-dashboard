"""Explicit opt-in real-provider smoke test; writes ONLY to parking_sensor_test."""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from cloud_storage import CloudClient, load_config, CloudError

def main():
    client = CloudClient(load_config(ROOT / ".secrets" / "cloud-test.json", testing=True))
    stamp = time.time_ns()
    line = "parking_node,source=uno,data_origin=synthetic sample_present=1i,a1_distance_cm=27.5,a1_distance_cm_valid=true " + str(stamp)
    # Retry same point deliberately. No production bucket or MQTT used.
    client.write([line])
    client.write([line])
    query = ('SELECT count("sample_present") AS samples, mean("a1_distance_cm") AS value '
             'FROM "parking_node" WHERE time = ' + str(stamp) + 'ns')
    import json
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        raw = client.request("/query", {"db": client.config["bucket"], "epoch":"ns","q":query}, "read_token")
        response = json.loads(raw)
        for item in response.get("results", []):
            if item.get("error"):
                raise SystemExit("Cloud query returned an error; verify DBRP mapping and permissions.")
            for series in item.get("series", []):
                for row in series["values"]:
                    record = dict(zip(series["columns"], row))
                    if record.get("samples") == 1 and record.get("value") == 27.5:
                        print("PASS real cloud synthetic write/read and logical duplicate identity.")
                        return
        time.sleep(5)
    raise SystemExit("Cloud readback not observed; no PASS claimed.")

if __name__ == "__main__":
    try:
        main()
    except CloudError as exc:
        raise SystemExit("Cloud verification failed: " + str(exc.code))
