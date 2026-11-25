"""Initialize/update project-local InfluxDB with seven-day retention, via official HTTP API."""
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

def load_env():
    return dict(line.split("=", 1) for line in ENV.read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)

def main():
    values = load_env()
    token = values["INFLUX_TOKEN"]
    def api(method, path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = Request("http://127.0.0.1:8086" + path, data=body, method=method,
                      headers={"Authorization": "Token " + token, "Content-Type": "application/json"})
        with urlopen(req, timeout=10) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    if api("GET", "/api/v2/setup")["allowed"]:
        api("POST", "/api/v2/setup", {"username": values["INFLUX_USERNAME"],
            "password": values["INFLUX_PASSWORD"], "token": token,
            "org": "parking", "bucket": "sensor_data", "retentionPeriodSeconds": 604800})
        print("Initialized local InfluxDB organization and seven-day sensor bucket.")
    orgs = api("GET", "/api/v2/orgs?org=parking")["orgs"]
    if not orgs:
        raise RuntimeError("Local InfluxDB parking organization missing; refusing to change another server")
    org_id = orgs[0]["id"]
    buckets = api("GET", "/api/v2/buckets?orgID=" + org_id)["buckets"]
    bucket_ids = {}
    for name in ("sensor_data", "sensor_test"):
        bucket = next((b for b in buckets if b["name"] == name), None)
        retention = [{"type": "expire", "everySeconds": 604800}]
        if bucket is None:
            bucket = api("POST", "/api/v2/buckets", {"orgID":org_id,"name":name,"retentionRules":retention})
        else:
            api("PATCH", "/api/v2/buckets/" + bucket["id"], {"retentionRules":retention})
        bucket_ids[name] = bucket["id"]
    if not values.get("INFLUX_RUNTIME_TOKEN"):
        runtime = api("POST", "/api/v2/authorizations", {"orgID":org_id,
            "description":"Parking native runtime: sensor_data read/write only",
            "permissions":[{"action":action,"resource":{"type":"buckets","id":bucket_ids["sensor_data"],"orgID":org_id}}
                           for action in ("read", "write")]})
        with ENV.open("a") as file:
            file.write("INFLUX_RUNTIME_TOKEN=" + runtime["token"] + "\n")
    print("Verified sensor_data and isolated sensor_test retention: seven days. No tokens printed.")

if __name__ == "__main__":
    main()
