"""Read-only verification of actual hardware MQTT, APIs and historical storage."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
from urllib.request import Request, urlopen
import paho.mqtt.client as mqtt

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from model import TOPICS, validate

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--seconds",type=int,default=60);args=parser.parse_args()
    values=dict(line.split("=",1) for line in (ROOT/".env").read_text().splitlines() if line and not line.startswith("#") and "=" in line)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder=ROOT/"docs/runtime-logs"/('hardware-'+stamp);folder.mkdir(parents=True)
    counts={source:0 for source in TOPICS.values()};errors=[];first={};connected=threading.Event()
    raw=(folder/"mqtt-events.jsonl").open("w",encoding="utf-8")
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id="parking-hardware-verifier")
    client.username_pw_set(values["MQTT_USERNAME"],values["MQTT_PASSWORD"])
    def on_connect(c,u,f,reason,p):
        if reason==0:c.subscribe([(t,1) for t in TOPICS]);connected.set()
    def on_message(c,u,m):
        event={"received_utc":datetime.now(timezone.utc).isoformat(),"topic":m.topic,"retained":m.retain}
        try:
            if m.retain:raise ValueError("retained message is not fresh hardware evidence")
            source,message=validate(m.topic,m.payload)
            event["message"]=message;counts[source]+=1
            if source not in first:first[source]=event;print("First actual",source,json.dumps(message),flush=True)
        except (ValueError,TypeError,UnicodeError) as exc:
            event["error"]=str(exc);errors.append(event)
        raw.write(json.dumps(event)+"\n");raw.flush()
    client.on_connect=on_connect;client.on_message=on_message
    try:
        client.connect(values["MQTT_BIND_IP"],1883,15);client.loop_start()
        if not connected.wait(8):raise RuntimeError("MQTT verification subscriber could not connect")
        print(f"Capturing actual hardware MQTT for {args.seconds} seconds; no messages published.",flush=True)
        time.sleep(args.seconds)
    finally:client.disconnect();client.loop_stop();raw.close()
    auth=base64.b64encode((values.get("DASHBOARD_USERNAME",values.get("GRAFANA_USERNAME","parking-admin"))+":"+values.get("DASHBOARD_PASSWORD",values.get("GRAFANA_PASSWORD",""))).encode()).decode()
    def api(path):
        with urlopen(Request("http://127.0.0.1:5000"+path,headers={"Authorization":"Basic "+auth}),timeout=15) as r:return json.load(r)
    latest=api("/api/latest");(folder/"latest.json").write_text(json.dumps(latest,indent=2))
    histories={}
    for source,field in (("uno","a1_distance_cm"),("esp32","temperature_c"),("esp32","light_raw")):
        history=api(f"/api/history?source={source}&field={field}&minutes=5")
        histories[field]=sum(p["value"] is not None for p in history["points"])
        (folder/(field+"-history.json")).write_text(json.dumps(history,indent=2))
    minimum={"uno":max(1,int(args.seconds*.8)),"esp32":max(1,int(args.seconds/3.5))}
    passed=(all(counts[k]>=v for k,v in minimum.items()) and not errors and
            latest["mqtt_connected"] and latest["storage_connected"] and
            all(latest["sources"][s]["fresh"] for s in ("uno","esp32")) and all(histories.values()))
    summary={"data_origin":"hardware","capture_seconds":args.seconds,"counts":counts,"minimum_expected":minimum,
             "errors":errors,"first_actual_messages":first,"history_nonnull_points":histories,
             "pipeline_pass":passed,"camera_physical_test":"not required; teammate interface only",
             "physical_manipulation_tests":"not established by this passive capture","folder":str(folder.relative_to(ROOT))}
    (folder/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
    if not passed:raise SystemExit(1)

if __name__=="__main__":main()
