"""Local-only dashboard with optional authentication; tokens stay in this process."""
import hmac
import threading
import os
import math
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, Response, jsonify, render_template, request
from gate_model import GATE_RANGES
from model import unique_object

import parking_proxy

UPLOAD_LIMIT = 15 * 1024 * 1024
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

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
        if request.path == "/api/parking/analyze":
            # Photos for recognition are the only large request bodies this dashboard accepts.
            request.max_content_length = UPLOAD_LIMIT + 64 * 1024
        if (os.environ.get("DASHBOARD_AUTH_REQUIRED", "yes") == "no"
                and request.remote_addr in ("127.0.0.1", "::1")):
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
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'"
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

    # ---- Camera/parking service (cameras, recognition, bays, visits, decisions, photos) ----
    def parking_error(exc):
        return jsonify(error=str(exc), available=exc.status < 500), exc.status

    @app.get("/api/parking/status")
    def parking_status():
        try:
            return jsonify(parking_proxy.status())
        except parking_proxy.ParkingUnavailable as exc:
            return parking_error(exc)

    @app.get("/api/parking/history")
    def parking_history():
        try:
            limit = int(request.args.get("limit", "100"))
        except ValueError:
            return jsonify(error="limit must be an integer"), 400
        if not 1 <= limit <= 100:
            return jsonify(error="limit must be 1–100"), 400
        try:
            return jsonify(parking_proxy.history(limit))
        except parking_proxy.ParkingUnavailable as exc:
            return parking_error(exc)

    @app.get("/api/parking/media/<uuid:media_id>")
    def parking_media(media_id):
        try:
            return Response(parking_proxy.media(str(media_id)), mimetype="image/jpeg")
        except parking_proxy.ParkingUnavailable as exc:
            return Response("Photo unavailable", exc.status if exc.status == 404 else 503, mimetype="text/plain")

    @app.get("/api/camera/frame")
    def camera_frame():
        try:
            data, camera_ms = parking_proxy.camera_frame(request.args.get("camera", ""))
        except parking_proxy.ParkingUnavailable as exc:
            return parking_error(exc)
        response = Response(data, mimetype="image/jpeg")
        if camera_ms and re.fullmatch(r"[0-9.]{1,12}", camera_ms):
            response.headers["X-Camera-Ms"] = camera_ms
        return response

    # One live preview per camera: each open stream holds a server thread, so a second
    # viewer of the same camera is refused and that page falls back to still frames.
    stream_slots = {role: threading.BoundedSemaphore(1) for role in parking_proxy.CAMERAS}

    @app.get("/api/camera/stream")
    def camera_stream():
        camera = request.args.get("camera", "")
        if camera not in stream_slots:
            return jsonify(error="camera must be entrance or exit"), 400
        slot = stream_slots[camera]
        if request.args.get("probe"):
            # Lets a page whose stream failed tell "busy elsewhere" apart from "camera down".
            return jsonify(busy=slot._value == 0), 200
        if not slot.acquire(blocking=False):
            return jsonify(error="This camera is already streaming to another page"), 409
        try:
            content_type, upstream = parking_proxy.camera_stream(camera)
        except parking_proxy.ParkingUnavailable as exc:
            slot.release()
            return parking_error(exc)

        def relay():
            try:
                while True:
                    chunk = upstream.read1(parking_proxy.STREAM_CHUNK) if hasattr(upstream, "read1") else upstream.read(parking_proxy.STREAM_CHUNK)
                    if not chunk:
                        break
                    yield chunk
            except (OSError, ValueError):
                pass
            finally:
                upstream.close()
                slot.release()

        return Response(relay(), mimetype=content_type.split(";")[0], content_type=content_type, direct_passthrough=True)

    @app.post("/api/parking/analyze")
    def parking_analyze():
        image = request.files.get("image")
        camera = request.form.get("camera", "")
        bbox = request.form.get("plate_bbox") or None
        previous = request.form.get("previous_observation_id") or None
        if camera not in parking_proxy.CAMERAS:
            return jsonify(error="camera must be entrance or exit"), 400
        if bbox is not None and not re.fullmatch(r"\d{1,5},\d{1,5},\d{1,5},\d{1,5}", bbox):
            return jsonify(error="plate_bbox must be x1,y1,x2,y2 in pixels"), 400
        if previous is not None and not UUID_RE.fullmatch(previous):
            return jsonify(error="previous_observation_id must be a UUID"), 400
        if image is None:
            return jsonify(error="image is required"), 400
        data = image.read(UPLOAD_LIMIT + 1)
        if not data or len(data) > UPLOAD_LIMIT:
            return jsonify(error="image must be 1 byte–15 MiB"), 413
        image_type = image.mimetype if image.mimetype in ("image/jpeg", "image/png", "image/webp") else "application/octet-stream"
        try:
            return jsonify(parking_proxy.analyze(data, image_type, camera, bbox, previous))
        except parking_proxy.ParkingUnavailable as exc:
            return parking_error(exc)

    @app.post("/api/parking/commit")
    def parking_commit():
        body = request.get_json(silent=True) or {}
        observation_id, request_id = body.get("observation_id"), body.get("request_id")
        if not isinstance(observation_id, str) or not UUID_RE.fullmatch(observation_id):
            return jsonify(error="observation_id must be a UUID"), 400
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            return jsonify(error="request_id must be 1–128 characters"), 400
        try:
            return jsonify(parking_proxy.commit(observation_id, request_id))
        except parking_proxy.ParkingUnavailable as exc:
            return parking_error(exc)

    return app
