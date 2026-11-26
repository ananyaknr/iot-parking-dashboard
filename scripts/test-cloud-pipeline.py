"""Explicit opt-in real-provider smoke test; writes ONLY to parking_sensor_test."""
import sys
import json
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
    # Verify runtime roles against the isolated test bucket only. A read token
    # must not write, and a write token must not query. Never probe production.
    try:
        client.request('/api/v2/write',{'bucket':client.config['bucket'],'precision':'ns'},
                       'read_token',(line+'\n').encode())
    except CloudError as exc:
        if exc.code not in (401,403):raise
    else:
        raise SystemExit('Read token can write; replace it with a read-only test-bucket token.')
    query = ('SELECT count("sample_present") AS samples, mean("a1_distance_cm") AS value '
             'FROM "parking_node" WHERE time = ' + str(stamp) + 'ns')
    try:
        client.request('/query',{'db':client.config['bucket'],'epoch':'ns','q':query},'write_token')
    except CloudError as exc:
        if exc.code not in (401,403):raise
    else:
        raise SystemExit('Write token can query; replace it with a write-only test-bucket token.')
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        raw = client.request("/query", {"db": client.config["bucket"], "epoch":"ns","q":query}, "read_token")
        response = json.loads(raw)
        if response.get('error'):
            raise SystemExit('Cloud query returned an error; verify DBRP mapping and permissions.')
        for item in response.get("results", []):
            if item.get("error"):
                raise SystemExit("Cloud query returned an error; verify DBRP mapping and permissions.")
            for series in item.get("series", []):
                for row in series["values"]:
                    record = dict(zip(series["columns"], row))
                    if record.get("samples") == 1 and record.get("value") == 27.5:
                        print("PASS real cloud synthetic write/read and logical duplicate identity.")
                        receipt={'verified_at_utc':datetime.now(timezone.utc).isoformat(),
                                 'bucket':client.config['bucket'],'data_origin':'synthetic',
                                 'logical_point_count':1,'value':27.5,'token_roles':'PASS',
                                 'sample_timestamp_ns':stamp,'transfer':client.usage()}
                        (ROOT/'.runtime').mkdir(exist_ok=True)
                        (ROOT/'.runtime/cloud-test-verification.json').write_text(json.dumps(receipt,indent=2))
                        print(json.dumps(receipt,indent=2))
                        return
        time.sleep(5)
    raise SystemExit("Cloud readback not observed; no PASS claimed.")

if __name__ == "__main__":
    try:
        main()
    except CloudError as exc:
        raise SystemExit("Cloud verification failed: " + str(exc.code))
    except (ValueError, OSError, KeyError, TypeError):
        raise SystemExit('Cloud verification configuration/response unavailable; no PASS claimed.') from None
