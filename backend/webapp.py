"""Local-only authenticated dashboard; tokens never leave this process."""
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, Response, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[1]
HISTORY = {
    "uno": ("parking_node", {"a1_distance_cm"}),
    "esp32": ("parking_gateway", {"temperature_c", "humidity_pct", "light_raw", "gas_raw"}),
    "camera": ("parking_camera", {"confidence"}),
}

def create_app(latest, query_api, bucket, org):
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
        query = f'''from(bucket: "{bucket}")
          |> range(start: -{minutes}m)
          |> filter(fn: (r) => r._measurement == "{measurement}" and r.kind == "status")
          |> filter(fn: (r) => r._field == "{field}" or r._field == "{field}_valid")
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> filter(fn: (r) => r.{field}_valid and exists r.{field})
          |> keep(columns: ["_time", "_start", "_stop", "{field}"])
          |> rename(columns: {{"{field}": "_value"}})
          |> aggregateWindow(every: {every}s, fn: mean, createEmpty: true)'''
        try:
            records = [record for table in query_api.query(query, org=org) for record in table.records]
            points = [{"time": r.get_time().isoformat(), "value": r.get_value()} for r in records]
            return jsonify(source=source, field=field, minutes=minutes, interval_seconds=every, points=points)
        except Exception:
            app.logger.warning("History query unavailable", exc_info=False)
            return jsonify(error="Historical storage is temporarily unavailable", points=[]), 503

    return app
