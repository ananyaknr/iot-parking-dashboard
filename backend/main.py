"""MQTT receive timestamps and one-second current-state snapshots into InfluxDB 2.x."""
import logging
import os
import queue
import signal
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from model import TOPICS, Source
from gate_model import GateSource
from gate_events import GateEvents,gate_routing
from recognition_adapter import RecognitionAdapter
from runtime import Ingestion, StorageWorker
from cloud_storage import start_optional_cloud,start_gate_test_cloud
from webapp import create_app
from parking_v1 import ParkingV1,TELEMETRY as V3_TELEMETRY,COMMAND as V1_COMMAND,WIRE_ACK as V3_ACK,FEEDBACK_ACK as V1_FEEDBACK_ACK
from waitress import create_server
from parking_clock import VerifiedClock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parking")
MEASUREMENTS = {"uno": "parking_node", "esp32": "parking_gateway", "camera": "parking_camera", "gate":"parking_gate_v2"}

def main():
    stop = threading.Event()
    messages = queue.Queue(maxsize=1000)
    connected = threading.Event()
    states = {name: GateSource() if name=='gate' else Source(name) for name in MEASUREMENTS}
    received_utc = {name: None for name in MEASUREMENTS}
    state_lock = threading.Lock()
    status = {"dropped": 0, "generation": 0}
    ingestion = Ingestion(states)
    bucket = os.environ.get("INFLUX_BUCKET", "sensor_data")
    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "parking").rstrip("/")
    origin=os.environ.get('DATA_ORIGIN','hardware')
    routing=os.environ.get('GATE_SCHEMA_ROUTING','off')
    approved=os.environ.get('GATE_PRODUCTION_APPROVED')=='yes'
    gate_enabled=gate_routing(origin,prefix,bucket,routing,approved)
    v1_enabled=os.environ.get('PARKING_V1_ENABLED')=='yes'
    if v1_enabled and not (gate_enabled and routing=='isolated' and prefix=='parking/test' and bucket=='sensor_test'):
        raise ValueError('Parking v1 simulation requires isolated test routing')
    physical_inferred=os.environ.get('PARKING_V1_PHYSICAL_INFERRED')=='yes'
    if physical_inferred and not v1_enabled:raise ValueError('Physical inferred mode requires isolated Parking v1')
    wire_topics={topic.replace('parking/',prefix+'/',1):topic for topic in TOPICS
                 if TOPICS[topic]!='gate' or gate_enabled}
    if gate_enabled and routing=='isolated' and os.environ.get('GATE_ENVIRONMENT_FROM_PRODUCTION')=='yes':
        wire_topics['parking/gateway/telemetry']='parking/gateway/telemetry'
    runtime=Path(__file__).resolve().parents[1]/'.runtime'
    event_path=Path(os.environ.get('GATE_EVENT_LEDGER_PATH',str(runtime/('gate-test-'+origin+'-events.sqlite3' if routing=='isolated' else 'gate-events.sqlite3')))).resolve()
    if not event_path.is_relative_to(runtime.resolve()):raise ValueError('Gate ledger must stay within project runtime')
    events=GateEvents(event_path) if gate_enabled else None
    event_errors=0
    def current_gate():
        with state_lock:return states['gate'].snapshot(time.monotonic())
    recognition=RecognitionAdapter(current_gate,enabled=gate_enabled and routing=='isolated'
                                   and os.environ.get('GATE_MOCK_ADAPTER')=='yes')
    org = os.environ.get("INFLUX_ORG", "parking")
    if gate_enabled and routing=='isolated' and os.environ.get('GATE_TEST_CLOUD')=='yes':
        cloud,cloud_error=start_gate_test_cloud(origin,prefix,bucket)
    else:
        cloud,cloud_error=start_optional_cloud(origin,prefix,bucket,gate_production_approved=approved)
    influx = InfluxDBClient(url=os.environ.get("INFLUX_URL", "http://influxdb:8086"),
                            token=os.environ["INFLUX_TOKEN"], org=org, timeout=4000)
    writer = influx.write_api(write_options=SYNCHRONOUS)
    storage = StorageWorker(lambda batch: writer.write(bucket=bucket, org=org, record=batch))
    storage_thread = threading.Thread(target=storage.run, args=(stop,), daemon=True)
    storage_thread.start()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id=os.environ.get("MQTT_CLIENT_ID", "parking-backend"), clean_session=True)
    client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    parking_clock=VerifiedClock(stop) if v1_enabled else None
    parking=ParkingV1(runtime/('parking-v1-physical-inferred-test.sqlite3' if physical_inferred else 'parking-v1-test.sqlite3'),lambda topic,payload:client.publish(topic,payload,qos=1,retain=False),clock=parking_clock,clock_verified=parking_clock.verified,physical_inferred=physical_inferred,test_storage=True) if v1_enabled else None
    if parking:
        for topic in (V3_TELEMETRY,V1_COMMAND,V3_ACK,V1_FEEDBACK_ACK):wire_topics[topic]=topic

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code == 0:
            connected.set()
            c.subscribe([(topic, 1) for topic in wire_topics])
            log.info("MQTT connected; subscribed to %d source topics", len(wire_topics))
        else:
            connected.clear()
            log.warning("MQTT connection refused: %s", reason_code)

    def on_disconnect(c, userdata, flags, reason_code, properties):
        if parking:parking.interrupt()
        with state_lock:
            connected.clear()
            status["generation"] += 1
            for state in states.values():
                state.reject(time.monotonic())
        log.warning("MQTT disconnected: %s", reason_code)

    def on_message(c, userdata, message):
        # Callback stays short. Reject retained telemetry: it must not revive a source.
        if message.topic not in wire_topics:
            return
        item = (wire_topics[message.topic], bytes(message.payload), bool(message.retain),
                bool(message.dup), time.monotonic(), datetime.now(timezone.utc), status["generation"])
        try:
            messages.put_nowait(item)
        except queue.Full:
            status["dropped"] += 1
            with state_lock:
                if item[0] in TOPICS:states[TOPICS[item[0]]].reject(item[4])
            log.error("Receive queue full; message dropped")

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    client.connect_async(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")), 15)
    client.loop_start()

    def latest():
        now = time.monotonic()
        with state_lock:
            sources = {name: state.snapshot(now) for name, state in states.items()}
            for name in sources:
                sources[name]["last_received_utc"] = received_utc[name]
            sources["uno"]["legacy"]=True
        p3=parking.snapshot() if parking else {'enabled':False}
        return {"received_at_utc": datetime.now(timezone.utc).isoformat(),
                "data_origin": os.environ.get("DATA_ORIGIN", "hardware"),
                "mqtt_connected": connected.is_set(),
                **storage.snapshot(),
                "cloud": cloud.snapshot() if cloud else {"enabled": False, "error": cloud_error},
                'gate_routing':routing,'gate_event_errors':event_errors,'recognition':recognition.snapshot(),
                'parking3':p3,
                "ingestion_connected": connected.is_set() and (p3.get('fresh',False) or any(
                    s["fresh"] and s["payload_valid"] for s in sources.values())),
                "ingestion_queue_depth": messages.qsize(),
                "rejected_messages": ingestion.rejected, "dropped_messages": status["dropped"],
                "discarded_messages": ingestion.discarded,
                "sources": sources}

    app = create_app(latest, influx.query_api(), bucket, org, cloud=cloud,gate_events=events,recognition=recognition)
    server = create_server(app, host="127.0.0.1", port=int(os.environ.get("DASHBOARD_PORT", "5000")), threads=8)
    threading.Thread(target=server.run, daemon=True).start()
    log.info("Dashboard listening on http://127.0.0.1:%s", os.environ.get("DASHBOARD_PORT", "5000"))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    next_snapshot = 0.0
    next_parking_tick=0.0

    def point(source, fields, kind, stamp):
        p = (Point(MEASUREMENTS[source]).tag("source", source).tag("kind", kind)
             .tag("data_origin", os.environ.get("DATA_ORIGIN", "hardware"))
             .time(stamp, WritePrecision.NS))
        for name, value in fields.items():
            if value is not None:
                # JSON permits whole-number distances; Influx field types must
                # stay float across all samples and producer implementations.
                p.field(name,float(value) if source=='gate' and name.endswith('_cm') else value)
        return p

    try:
        while not stop.is_set():
            if os.environ.get("BACKEND_STOP_FILE") and Path(os.environ["BACKEND_STOP_FILE"]).exists():
                break
            # Bound per-loop work so sustained input cannot starve freshness updates.
            for _ in range(100):
                try:
                    topic, payload, retained, duplicate, received_mono, stamp, generation = messages.get_nowait()
                except queue.Empty:
                    break
                with state_lock:
                    if generation != status["generation"] or not connected.is_set():
                        ingestion.discarded += 1
                        continue
                    if parking and topic in (V3_TELEMETRY,V1_COMMAND,V3_ACK,V1_FEEDBACK_ACK):
                        if time.monotonic()-received_mono>2:
                            ingestion.discarded+=1
                            continue
                        try:
                            data=parking.receive(topic,payload,retained)
                            if data:
                                p=(Point('parking_gate_v3').tag('source','parking3').tag('data_origin',origin)
                                   .time(stamp,WritePrecision.NS))
                                if physical_inferred:p.tag('gate_mode',data['mode']).field('servo_enabled',data['servo_enabled'])
                                for field in ('u1_distance_cm','u2_distance_cm','cycle','vibration_raw','vibration_transition_count','phase','lane','reason'):
                                    if data[field] is not None:p.field(field,float(data[field]) if field.endswith('_cm') else data[field])
                                storage.submit(p)
                        except (ValueError,TypeError,KeyError,OverflowError,RecursionError,sqlite3.Error):parking.rejected+=1
                        continue
                    rejected_before = ingestion.rejected
                    source = ingestion.receive(topic, payload, retained, duplicate,
                                               received_mono, time.monotonic())
                    if source:
                        received_utc[source] = stamp.isoformat()
                        storage.submit(point(source, states[source].snapshot(received_mono), "telemetry", stamp))
                        if source=='gate' and events is not None:
                            try:
                                remembered=events.remember(states[source].message,stamp)
                                if remembered:
                                    original,event=remembered
                                    p=(Point('parking_gate_events_v2').tag('source','gate')
                                       .tag('event_id',event['event_id']).tag('data_origin',origin)
                                       .time(original,WritePrecision.NS))
                                    for key,value in event.items():
                                        if value is not None and key!='event_id':
                                            p.field(key,float(value) if key.endswith('_cm') else value)
                                    storage.submit(p)
                            except (ValueError,OSError,sqlite3.Error):
                                event_errors+=1;log.warning('Gate event ledger unavailable; live processing continues')
                        if cloud is not None:
                            cloud.submit(source, states[source].message, stamp)
                    elif ingestion.rejected > rejected_before:
                        log.warning("Rejected %s telemetry (invalid or retained)", TOPICS[topic])
                        storage.submit(Point("parking_events").tag("source", TOPICS[topic])
                                       .field("rejected", True).field("reason", "invalid_or_retained")
                                       .time(stamp, WritePrecision.NS))
            now = time.monotonic()
            if parking and connected.is_set() and now>=next_parking_tick:
                next_parking_tick=now+1
                try:parking.tick()
                except (sqlite3.Error,OSError):parking.rejected+=1;log.warning('Parking retry ledger unavailable; sensor ingestion continues')
            if now >= next_snapshot:
                stamp = datetime.now(timezone.utc)
                with state_lock:
                    for source, state in states.items():
                        if source=="gate" and not gate_enabled:continue
                        storage.submit(point(source, state.snapshot(now), "status", stamp))
                next_snapshot = now + 1
            stop.wait(0.05)
    finally:
        stop.set()
        client.disconnect()
        client.loop_stop()
        server.close()
        storage_thread.join()
        if cloud is not None:
            cloud.close()
        if events is not None:events.close()
        if parking is not None:parking.close()
        writer.close()
        influx.close()

if __name__ == "__main__":
    main()
