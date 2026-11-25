"""Generate the provisioned Grafana dashboard. Queries guard snapshot age and validity."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DS = {"type": "influxdb", "uid": "parking-influx"}

def current(source):
    measurement = "parking_node" if source == "uno" else "parking_gateway"
    return f'''from(bucket: "sensor_data")
  |> range(start: -2m)
  |> filter(fn: (r) => r._measurement == "{measurement}" and r.kind == "status")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 1)
'''

def numeric(source, name):
    return current(source) + f'''  |> filter(fn: (r) => r._time >= date.sub(d: 10s, from: now()) and r.fresh and r.{name}_valid and exists r.{name})
  |> keep(columns: ["_time", "{name}"])
  |> rename(columns: {{"{name}": "_value"}})'''

def state(source, name):
    return current(source) + f'''  |> map(fn: (r) => ({{_time: r._time, _value: if r._time < date.sub(d: 10s, from: now()) then 0 else r.{name}}}))'''

def history(source, names):
    measurement = "parking_node" if source == "uno" else "parking_gateway"
    selection = " or ".join(f'r._field == "{n}"' for n in names)
    return f'''from(bucket: "sensor_data")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "{measurement}" and r.kind == "status" and ({selection}))
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: true)'''

panels = []
def add(title, query, x, y, w=6, h=4, unit="none", mappings=None, panel_type="stat", description=""):
    panels.append({"id": len(panels)+1, "title": title, "type": panel_type,
      "description": description, "datasource": DS, "gridPos": {"x": x,"y": y,"w": w,"h": h},
      "targets": [{"refId":"A", "query": 'import "date"\n' + query}],
      "fieldConfig": {"defaults": {"unit":unit,"noValue":"Unknown","decimals":1,
        "mappings": mappings or [], "thresholds": {"mode":"absolute", "steps":[{"color":"blue","value":None}]},
        "custom":{"spanNulls": False}}, "overrides":[]},
      "options": {"colorMode":"background", "graphMode":"none", "textMode":"auto",
        "reduceOptions":{"calcs":["last"], "fields":"", "values":False},
        "legend":{"displayMode":"list", "placement":"bottom"}}})

occupancy = [{"type":"value","options":{
    "0":{"text":"Unknown","color":"gray"},"1":{"text":"Available","color":"green"},
    "2":{"text":"Occupied","color":"red"},"3":{"text":"Not installed","color":"gray"}}}]
availability = [{"type":"value","options":{
    "0":{"text":"Stale / Unknown","color":"red"},"1":{"text":"Receiving","color":"green"}}}]
constant = lambda n: f'import "array"\narray.from(rows: [{{_time: now(), _value: {n}}}])'
add("A1 occupancy", state("uno", "a1_state"),0,0,mappings=occupancy)
add("A1 ultrasonic distance", numeric("uno","a1_distance_cm"),6,0,unit="lengthcm")
add("M1 occupancy — Not installed",constant(3),12,0,mappings=occupancy,
    description="D4/D5 reserved. M1 is never eligible for automatic allocation.")
add("Vibration — Not installed",constant(3),18,0,mappings=occupancy)
add("Temperature",numeric("esp32","temperature_c"),0,4,unit="celsius")
add("Relative humidity",numeric("esp32","humidity_pct"),6,4,unit="percent")
add("Ambient light — raw ADC",numeric("esp32","light_raw"),12,4,unit="none")
add("MQ-2 gas — uncalibrated raw ADC",numeric("esp32","gas_raw"),18,4,unit="none",
    description="Unconditioned or uncalibrated ADC reading. Not ppm; not a calibrated concentration.")
add("UNO freshness — 10 s timeout",state("uno","availability_state"),0,8,w=12,h=3,mappings=availability)
add("ESP32 freshness — 10 s timeout",state("esp32","availability_state"),12,8,w=12,h=3,mappings=availability)
add("A1 distance history",history("uno",["a1_distance_cm"]),0,11,w=12,h=7,unit="lengthcm",panel_type="timeseries")
add("Temperature history",history("esp32",["temperature_c"]),12,11,w=12,h=7,unit="celsius",panel_type="timeseries")
add("Humidity history",history("esp32",["humidity_pct"]),0,18,w=8,h=7,unit="percent",panel_type="timeseries")
add("Light history — raw ADC",history("esp32",["light_raw"]),8,18,w=8,h=7,panel_type="timeseries")
add("Gas history — uncalibrated raw ADC",history("esp32",["gas_raw"]),16,18,w=8,h=7,panel_type="timeseries")
dashboard = {"uid":"parking-monitor","title":"Intelligence Parking Lot — Sensor Monitoring",
    "schemaVersion":39,"version":1,"timezone":"browser","refresh":"5s","editable":False,
    "tags":["parking","hardware"],"time":{"from":"now-30m","to":"now"},"panels":panels,
    "annotations":{"list":[]},"templating":{"list":[]}}
(ROOT / "dashboard" / "parking-monitor.json").write_text(json.dumps(dashboard,indent=2), encoding="utf-8")
print(f"Generated {len(panels)} Grafana panels.")
