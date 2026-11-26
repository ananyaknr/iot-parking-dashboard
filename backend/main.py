"""MQTT receive timestamps and one-second current-state snapshots into InfluxDB 2.x."""
import logging
import os
import queue
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from model import TOPICS, Source
from runtime import Ingestion, StorageWorker
from cloud_storage import start_optional_cloud
from webapp import create_app
from waitress import create_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parking")
MEASUREMENTS = {"uno": "parking_node", "esp32": "parking_gateway", "camera": "parking_camera"}

def main():
    stop = threading.Event()
    messages = queue.Queue(maxsize=1000)
    connected = threading.Event()
    states = {name: Source(name) for name in MEASUREMENTS}
    received_utc = {name: None for name in MEASUREMENTS}
    state_lock = threading.Lock()
    status = {"dropped": 0, "generation": 0}
    ingestion = Ingestion(states)
    bucket = os.environ.get("INFLUX_BUCKET", "sensor_data")
    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "parking").rstrip("/")
    wire_topics = {topic.replace("parking/", prefix + "/", 1): topic for topic in TOPICS}
    org = os.environ.get("INFLUX_ORG", "parking")
    cloud, cloud_error = start_optional_cloud(os.environ.get("DATA_ORIGIN", "hardware"), prefix, bucket)
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

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code == 0:
            connected.set()
            c.subscribe([(topic, 1) for topic in wire_topics])
            log.info("MQTT connected; subscribed to %d source topics", len(wire_topics))
        else:
            connected.clear()
            log.warning("MQTT connection refused: %s", reason_code)

    def on_disconnect(c, userdata, flags, reason_code, properties):
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
                states[TOPICS[item[0]]].reject(item[4])
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
        return {"received_at_utc": datetime.now(timezone.utc).isoformat(),
                "data_origin": os.environ.get("DATA_ORIGIN", "hardware"),
                "mqtt_connected": connected.is_set(),
                **storage.snapshot(),
                "cloud": cloud.snapshot() if cloud else {"enabled": False, "error": cloud_error},
                "ingestion_connected": connected.is_set() and any(
                    s["fresh"] and s["payload_valid"] for s in sources.values()),
                "ingestion_queue_depth": messages.qsize(),
                "rejected_messages": ingestion.rejected, "dropped_messages": status["dropped"],
                "discarded_messages": ingestion.discarded,
                "sources": sources}

    app = create_app(latest, influx.query_api(), bucket, org, cloud=cloud)
    server = create_server(app, host="127.0.0.1", port=int(os.environ.get("DASHBOARD_PORT", "5000")), threads=4)
    threading.Thread(target=server.run, daemon=True).start()
    log.info("Dashboard listening on http://127.0.0.1:%s", os.environ.get("DASHBOARD_PORT", "5000"))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    next_snapshot = 0.0

    def point(source, fields, kind, stamp):
        p = (Point(MEASUREMENTS[source]).tag("source", source).tag("kind", kind)
             .tag("data_origin", os.environ.get("DATA_ORIGIN", "hardware"))
             .time(stamp, WritePrecision.NS))
        for name, value in fields.items():
            p.field(name, value)
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
                    rejected_before = ingestion.rejected
                    source = ingestion.receive(topic, payload, retained, duplicate,
                                               received_mono, time.monotonic())
                    if source:
                        received_utc[source] = stamp.isoformat()
                        storage.submit(point(source, states[source].snapshot(received_mono), "telemetry", stamp))
                        if cloud is not None:
                            cloud.submit(source, states[source].message, stamp)
                    elif ingestion.rejected > rejected_before:
                        log.warning("Rejected %s telemetry (invalid or retained)", TOPICS[topic])
                        storage.submit(Point("parking_events").tag("source", TOPICS[topic])
                                       .field("rejected", True).field("reason", "invalid_or_retained")
                                       .time(stamp, WritePrecision.NS))
            now = time.monotonic()
            if now >= next_snapshot:
                stamp = datetime.now(timezone.utc)
                with state_lock:
                    for source, state in states.items():
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
        writer.close()
        influx.close()

if __name__ == "__main__":
    main()
