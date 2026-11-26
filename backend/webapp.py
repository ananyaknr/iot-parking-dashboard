"""Local-only authenticated dashboard; tokens never leave this process."""
import hmac
import threading
import os
import math
import json
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, Response, jsonify, render_template, request
from gate_model import GATE_RANGES
from model import unique_object

ROOT = Path(__file__).resolve().parents[1]
HISTORY = {
    'gate':('parking_gate_v2',set(GATE_RANGES)),
    "uno": ("parking_node", {"a1_distance_cm"}),
    "esp32": ("parking_gateway", {"temperature_c", "humidity_pct", "light_raw", "gas_raw"}),
    "camera": ("parking_camera", {"confidence"}),
}


def history_points(records, start, stop, every, *, counter=False):
    """Fill empty windows and keep any invalid window as a visible gap."""
    values = {}
    for record in records:
        row = record.values
        end = row["_stop"].timestamp()
        value = (row.get('last_value') if counter else row.get("total", 0) / row["count"]) if row.get("count") else None
        values[end] = value if row.get("valid") and value is not None and math.isfinite(value) else None
    first = (int(start.timestamp()) // every + 1) * every
    return [{"time": datetime.fromtimestamp(min(end, stop.timestamp()), timezone.utc).isoformat(),
             "value": values.get(end)}
            for end in range(first, math.ceil(stop.timestamp() / every) * every + 1, every)]

def create_app(latest, query_api, bucket, org, cloud=None,gate_events=None,recognition=None):
    # Reserve the other Waitress threads for local live/history requests.
    cloud_query_slot = threading.BoundedSemaphore(1)
    app = Flask(__name__, template_folder=str(ROOT / "dashboard" / "templates"),
                static_folder=str(ROOT / "dashboard" / "static"))
    app.config["MAX_CONTENT_LENGTH"] = 4096

    @app.before_request
    def authenticate():
        if request.path == "/health":
            return None
        auth = request.authorization
        username = os.environ.get("DASHBOARD_USERNAME", os.environ.get("GRAFANA_USERNAME", "parking-admin"))
        password = os.environ.get("DASHBOARD_PASSWORD", os.environ.get("GRAFANA_PASSWORD", ""))
        if not password or not auth or not (hmac.compare_digest(auth.username or "", username)
                                           and hmac.compare_digest(auth.password or "", password)):
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Parking monitor"'})

    @app.after_request
    def headers(response):
        response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    @app.get("/")
    def dashboard():
        return render_template("index.html")

    @app.get("/health")
    def health():
        state = latest()
        healthy = state["mqtt_connected"] and state["storage_connected"]
        return jsonify(ready=healthy), 200 if healthy else 503

    @app.get("/api/latest")
    def current():
        return jsonify(latest())

    @app.get('/api/gate/events')
    def events():
        return jsonify(events=gate_events.recent() if gate_events else [],simulation=True)

    @app.post('/api/integration/recognition')
    def recognition_result():
        if recognition is None or not recognition.enabled:
            return jsonify(error='Recognition delivery awaits teammate agreement'),503
        try:
            if not request.is_json:raise ValueError('JSON required')
            result=recognition.receive(json.loads(request.get_data(cache=False),object_pairs_hook=unique_object))
            return jsonify(status=result,lcd_delivery='not_sent_contract_pending',physical_movement=False),202
        except (ValueError,TypeError,KeyError):
            return jsonify(error='Invalid, stale or uncorrelated recognition result'),400

    @app.get("/api/cloud/history")
    def cloud_history():
        source, field = request.args.get("source", "uno"), request.args.get("field", "a1_distance_cm")
        try:
            minutes = int(request.args.get("minutes", "30"))
            if source not in ("uno", "esp32",'gate') or field not in HISTORY[source][1] or not 1 <= minutes <= 43200:
                raise ValueError()
        except ValueError:
            return jsonify(error="unsupported cloud source, field or range (1–43200 minutes)"), 400
        if cloud is None:
            return jsonify(error="Cloud is not configured", points=[]), 503
        if not cloud_query_slot.acquire(blocking=False):
            return jsonify(error="Cloud history busy; retry on demand", points=[]), 429
        try:
            return jsonify(cloud.client.history(source, field, minutes))
        except Exception:
            app.logger.warning("Cloud history unavailable")
            return jsonify(error="Cloud history unavailable", points=[]), 503
        finally:
            cloud_query_slot.release()

    @app.get("/api/history")
    def history():
        source, field = request.args.get("source", "uno"), request.args.get("field", "a1_distance_cm")
        try:
            minutes = int(request.args.get("minutes", "30"))
        except ValueError:
            return jsonify(error="minutes must be an integer"), 400
        if source not in HISTORY or field not in HISTORY[source][1] or not 1 <= minutes <= 10080:
            return jsonify(error="unsupported source, field or range (1–10080 minutes)"), 400
        measurement = HISTORY[source][0]
        # Only whitelisted identifiers enter Flux. Null/invalid snapshots are explicit gaps.
        every = max(1, (minutes * 60 + 599) // 600)
        stop = datetime.now(timezone.utc)
        start = datetime.fromtimestamp(stop.timestamp() - minutes * 60, timezone.utc)
        query = f'''from(bucket: {json.dumps(bucket)})
          |> range(start: time(v: "{start.isoformat()}"), stop: time(v: "{stop.isoformat()}"))
          |> filter(fn: (r) => r._measurement == "{measurement}" and r.kind == "status")
          |> filter(fn: (r) => r._field == "{field}" or r._field == "{field}_valid")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> group(columns: [])
          |> sort(columns: ["_time"])
          |> window(every: {every}s)
          |> reduce(identity: {{total: 0.0, count: 0, valid: true, last_ns: 0, last_value: 0.0}},
            fn: (r, accumulator) => ({{
              total: accumulator.total + (if exists r.{field} then float(v: r.{field}) else 0.0),
              count: accumulator.count + (if exists r.{field} then 1 else 0),
              last_ns: int(v: r._time),
              last_value: if exists r.{field} then float(v: r.{field}) else 0.0,
              valid: accumulator.valid and (if exists r.{field}_valid then r.{field}_valid else false) and exists r.{field}
                and (accumulator.last_ns == 0 or int(v: r._time) - accumulator.last_ns <= 10000000000)
            }}))'''
        try:
            records = [record for table in query_api.query(query, org=org) for record in table.records]
            points = history_points(records, start, stop, every,counter=source=='gate' and not field.endswith('_cm'))
            return jsonify(source=source, field=field, minutes=minutes, interval_seconds=every, points=points)
        except Exception:
            app.logger.warning("History query unavailable", exc_info=False)
            return jsonify(error="Historical storage is temporarily unavailable", points=[]), 503

    return app
