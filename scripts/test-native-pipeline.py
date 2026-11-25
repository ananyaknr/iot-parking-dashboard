"""Explicitly SYNTHETIC end-to-end test, isolated in sensor_test / parking/test/*.

Never sends synthetic data to production topics. Runs a separate backend on port 5001.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
def env_values():
    return dict(line.split("=",1) for line in (ROOT/".env").read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)

def main():
    values=env_values()
    stop_file=ROOT/".runtime"/"test-backend.stop"
    stop_file.unlink(missing_ok=True)
    env=dict(os.environ, **values)
    env.update(MQTT_HOST=values["MQTT_BIND_IP"], INFLUX_URL="http://127.0.0.1:8086",
               INFLUX_ORG="parking", INFLUX_BUCKET="sensor_test", MQTT_TOPIC_PREFIX="parking/test",
               MQTT_CLIENT_ID="parking-synthetic-backend", DATA_ORIGIN="synthetic",
               DASHBOARD_PORT="5001", BACKEND_STOP_FILE=str(stop_file))
    log_path=ROOT/"docs/runtime-logs/synthetic-backend.log"
    results=[]
    def passed(name):
        results.append({"check":name,"result":"PASS","data_origin":"synthetic"})
        print("SYNTHETIC PASS:", name, flush=True)
    auth=base64.b64encode((values["GRAFANA_USERNAME"]+":"+values["GRAFANA_PASSWORD"]).encode()).decode()
    def api(path):
        with urlopen(Request("http://127.0.0.1:5001"+path,headers={"Authorization":"Basic "+auth}),timeout=10) as r:
            return json.load(r)
    def wait_for(predicate, seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                data=api("/api/latest")
                if predicate(data):return data
            except OSError:pass
            time.sleep(.3)
        raise AssertionError("Timed out waiting for expected synthetic API state")
    with log_path.open("w") as log:
        process=subprocess.Popen([sys.executable,str(ROOT/"backend/main.py")],cwd=ROOT,env=env,
                                 stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="parking-synthetic-publisher")
        client.username_pw_set(values["MQTT_USERNAME"],values["MQTT_PASSWORD"])
        try:
            client.connect(values["MQTT_BIND_IP"],1883,15);client.loop_start()
            wait_for(lambda d:d["mqtt_connected"] and d["storage_connected"])
            passed("isolated test backend ready")
            uno={"node":"uno","a1_distance_cm":11.4,"m1_distance_cm":None,"a1_occupied":True,
                 "m1_occupied":None,"vibration":None,"vibration_count":None,"vibration_status":"not_installed"}
            gateway={"node":"esp32","temperature_c":23.8,"humidity_pct":63.8,"light_raw":597,
                     "gas_raw":489,"gas_status":"unconditioned_or_uncalibrated"}
            camera={"node":"camera","slot":"A1","occupied":True,"confidence":.93}
            def publish(topic,msg,retain=False):
                payload=msg if isinstance(msg,str) else json.dumps(msg)
                client.publish("parking/test/"+topic,payload,qos=1,retain=retain).wait_for_publish(5)
            publish("node/telemetry",uno);publish("gateway/telemetry",gateway);publish("camera/result",camera)
            wait_for(lambda d:d["sources"]["uno"]["a1_state"]==2 and d["sources"]["esp32"].get("light_raw")==597 and d["sources"]["camera"]["camera_state"]==2)
            passed("three authenticated MQTT topics processed")
            publish("node/telemetry",dict(uno,a1_distance_cm=None,a1_occupied=None))
            wait_for(lambda d:d["sources"]["uno"]["a1_state"]==0 and not d["sources"]["uno"]["a1_distance_cm_valid"])
            passed("null measurement becomes unknown rather than zero")
            publish("gateway/telemetry","{malformed")
            wait_for(lambda d:not d["sources"]["esp32"]["payload_valid"] and d["rejected_messages"]>=1)
            passed("malformed payload rejected without stopping backend")
            publish("gateway/telemetry",gateway)
            wait_for(lambda d:d["sources"]["esp32"]["payload_valid"])
            passed("recovery after invalid payload")
            wait_for(lambda d:all(not s["fresh"] for s in d["sources"].values()),seconds=15)
            passed("all three sources stale after ten seconds")
            publish("node/telemetry",dict(uno,a1_distance_cm=30.,a1_occupied=False))
            current=wait_for(lambda d:d["sources"]["uno"]["a1_state"]==1)
            assert current["sources"]["uno"]["a1_allocation_eligible"]
            assert not current["sources"]["uno"]["m1_allocation_eligible"]
            passed("fresh recovery and independent M1 allocation exclusion")
            time.sleep(2)
            history=api("/api/history?source=uno&field=a1_distance_cm&minutes=5")
            assert any(p["value"] is not None for p in history["points"])
            passed("InfluxDB historical query via Flask API")
        finally:
            client.disconnect();client.loop_stop();stop_file.write_text("synthetic test finished")
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
            (ROOT/"docs/runtime-logs/synthetic-results.json").write_text(json.dumps(results,indent=2))
    print("Synthetic test complete. No production-topic messages published.")

if __name__=="__main__":main()
