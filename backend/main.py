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
from model import TOPICS, Source, validate
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
    status = {"last_write": 0.0, "dropped": 0, "rejected": 0}
    bucket = os.environ.get("INFLUX_BUCKET", "sensor_data")
    prefix = os.environ.get("MQTT_TOPIC_PREFIX", "parking").rstrip("/")
    wire_topics = {topic.replace("parking/", prefix + "/", 1): topic for topic in TOPICS}
    org = os.environ.get("INFLUX_ORG", "parking")
    influx = InfluxDBClient(url=os.environ.get("INFLUX_URL", "http://influxdb:8086"),
                            token=os.environ["INFLUX_TOKEN"], org=org, timeout=4000)
    writer = influx.write_api(write_options=SYNCHRONOUS)
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
        connected.clear()
        log.warning("MQTT disconnected: %s", reason_code)

    def on_message(c, userdata, message):
        # Callback stays short. Reject retained telemetry: it must not revive a source.
        item = (wire_topics[message.topic], bytes(message.payload), bool(message.retain),
                time.monotonic(), datetime.now(timezone.utc))
        try:
            messages.put_nowait(item)
        except queue.Full:
            status["dropped"] += 1
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
                "storage_connected": now - status["last_write"] < 10,
                "rejected_messages": status["rejected"], "dropped_messages": status["dropped"],
                "sources": sources}

    app = create_app(latest, influx.query_api(), bucket, org)
    server = create_server(app, host="127.0.0.1", port=int(os.environ.get("DASHBOARD_PORT", "5000")), threads=4)
    threading.Thread(target=server.run, daemon=True).start()
    log.info("Dashboard listening on http://127.0.0.1:%s", os.environ.get("DASHBOARD_PORT", "5000"))
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    next_snapshot = 0.0
    pending = []

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
                    topic, payload, retained, received_mono, stamp = messages.get_nowait()
                except queue.Empty:
                    break
                source = TOPICS[topic]
                try:
                    if retained:
                        raise ValueError("retained telemetry rejected")
                    source, message = validate(topic, payload)
                    with state_lock:
                        states[source].accept(message, received_mono)
                        received_utc[source] = stamp.isoformat()
                    pending.append(point(source, states[source].snapshot(received_mono), "telemetry", stamp))
                except (ValueError, TypeError, UnicodeError) as exc:
                    with state_lock:
                        states[source].reject(received_mono)
                    status["rejected"] += 1
                    log.warning("Rejected %s payload: %s", source, exc)  # never log payloads/secrets
                    pending.append(Point("parking_events").tag("source", source)
                                   .field("rejected", True).field("reason", str(exc))
                                   .time(stamp, WritePrecision.NS))
            now = time.monotonic()
            if now >= next_snapshot:
                stamp = datetime.now(timezone.utc)
                for source, state in states.items():
                    pending.append(point(source, state.snapshot(now), "status", stamp))
                next_snapshot = now + 1
            if pending:
                try:
                    writer.write(bucket=bucket, org=org, record=pending)
                    status["last_write"] = time.monotonic()
                    pending.clear()
                except Exception as exc:
                    log.warning("Influx write unavailable: %s", type(exc).__name__)
                    # Bound RAM during outages; do not invent replacement measurements.
                    if len(pending) > 2000:
                        pending = pending[-2000:]
                        log.error("Write backlog truncated to 2000 points")
                    stop.wait(1)
            stop.wait(0.05)
    finally:
        client.disconnect()
        client.loop_stop()
        server.close()
        writer.close()
        influx.close()

if __name__ == "__main__":
    main()
