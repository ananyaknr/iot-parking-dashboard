"""Optional sensor-only Cloud Serverless archive; no local gate or live dependency."""
import json
import logging
import math
import queue
import random
import sqlite3
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from model import RANGES
from gate_model import validate_gate

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("parking.cloud")
MEASUREMENTS = {"uno": "parking_node", "esp32": "parking_gateway"}
CLOUD_MEASUREMENTS = dict(MEASUREMENTS,gate='parking_gate_v2')
PRODUCTION = "parking_sensor_data"
TEST = "parking_sensor_test"
RETENTION_SECONDS = 30 * 86400
MAX_RECORDS = 50_000
# Rollback-journal mode: reserve roughly half the 32 MiB physical budget
# for the journal. The database is hard-capped by SQLite page count.
MAX_DB_BYTES = 15 * 1024 * 1024
BATCH_SIZE = 200
MAX_BATCH_BYTES = 100_000
INTERVAL = 10


def serverless_url(url):
    host = urlsplit(url)
    if (host.scheme != "https" or not host.hostname
            or not (host.hostname == "cloud2.influxdata.com"
                    or host.hostname.endswith(".cloud2.influxdata.com"))
            or host.username or host.password or host.port not in (None, 443)
            or host.path not in ("", "/") or host.query or host.fragment):
        raise ValueError("Expected an official HTTPS Cloud Serverless regional URL")
    return f"https://{host.hostname}"


def load_config(path=ROOT / ".secrets" / "cloud.json", *, testing=False):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    url = serverless_url(config["url"])
    bucket = TEST if testing else PRODUCTION
    if config.get("bucket") != bucket:
        raise ValueError("Unexpected cloud bucket for this environment")
    if config.get("free_plan_confirmed") is not True:
        raise ValueError("Free Plan confirmation required")
    for key in ("read_token", "write_token"):
        token = config.get(key)
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError("Missing or invalid cloud token")
    if config["read_token"] == config["write_token"]:
        raise ValueError("Use separate read and write tokens")
    return dict(config, url=url)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CloudError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(str(code))
        self.code = code
        self.retry_after = retry_after


class CloudClient:
    def __init__(self, config):
        self.config = config
        self.opener = build_opener(NoRedirect())
        self.metrics_lock = threading.Lock()
        self.metrics = {"write_requests": 0, "query_requests": 0,
                        "attempted_write_bytes": 0, "acknowledged_write_bytes": 0,
                        "response_bytes": 0}

    def usage(self):
        with self.metrics_lock:
            return dict(self.metrics)

    def request(self, path, params, token, body=None):
        headers = {"Authorization": "Token " + self.config[token],
                   "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "text/plain; charset=utf-8"
        req = Request(self.config["url"] + path + "?" + urlencode(params),
                      data=body, headers=headers)
        is_write = path == "/api/v2/write"
        with self.metrics_lock:
            self.metrics["write_requests" if is_write else "query_requests"] += 1
            if is_write:
                self.metrics["attempted_write_bytes"] += len(body or b"")
        try:
            with self.opener.open(req, timeout=5) as response:
                result = response.read(1024 * 1024 + 1)
                if len(result) > 1024 * 1024:
                    raise CloudError("response_too_large")
                with self.metrics_lock:
                    self.metrics["response_bytes"] += len(result)
                    if is_write:
                        self.metrics["acknowledged_write_bytes"] += len(body or b"")
                return result
        except HTTPError as exc:
            try:
                retry = exc.headers.get("Retry-After", "0")
                try:
                    delay = int(retry)
                except ValueError:
                    delay = math.ceil(parsedate_to_datetime(retry).timestamp() - time.time())
                delay = min(3600, max(0, delay))
            except (ValueError, TypeError):
                delay = 0
            exc.close()
            raise CloudError(exc.code, delay) from None
        except (OSError, TimeoutError, HTTPException):
            raise CloudError("network_error") from None

    def write(self, lines):
        body = ("\n".join(lines) + "\n").encode("utf-8")
        self.request("/api/v2/write", {"bucket": self.config["bucket"], "precision": "ns"},
                     "write_token", body)

    def history(self, source, field, minutes, *, stop=None):
        if source not in CLOUD_MEASUREMENTS or field not in RANGES[source] or not 1 <= minutes <= 43200:
            raise ValueError("Unsupported cloud history request")
        stop = stop or datetime.now(timezone.utc)
        end = int(stop.timestamp())
        start = end - minutes * 60
        every = max(1, math.ceil(minutes * 60 / 600))
        # Identifiers are static/allowlisted. Use a bounded aggregation query;
        # absence of telemetry is not equivalent to a zero measurement.
        aggregate = 'last' if source=='gate' and field not in ('u1_distance_cm','u2_distance_cm') else 'mean'
        statement = (f'SELECT {aggregate}("{field}") AS value, count("{field}") AS valid_samples, '
                     f'count("sample_present") AS samples FROM "{CLOUD_MEASUREMENTS[source]}" '
                     f'WHERE time >= {start}s AND time < {end}s '
                     f'GROUP BY time({every}s) fill(none)')
        try:
            result = json.loads(self.request("/query", {"db": self.config["bucket"], "epoch": "s",
                                                        "q": statement}, "read_token"))
            windows = {}
            if result.get("error"):
                raise CloudError("query_error")
            for item in result["results"]:
                if item.get("error"):
                    raise CloudError("query_error")
                for series in item.get("series", []):
                    for row in series["values"]:
                        record = dict(zip(series["columns"], row))
                        timestamp = int(record["time"])
                        value = record.get("value")
                        count = record.get("samples") or 0
                        valid = record.get("valid_samples") or 0
                        overlap = max(0, min(timestamp + every, end) - max(timestamp, start))
                        cadence = 1 if source in ("uno",'gate') else 2.5
                        # Require reasonable coverage and no explicitly missing values.
                        # Aggregates cannot prove continuity within a coarse window.
                        minimum = max(1, math.floor(0.8 * overlap / cadence))
                        if (count >= minimum and valid == count and type(value) in (int, float)
                                and math.isfinite(value)):
                            windows[timestamp] = value
            points = [{"time": datetime.fromtimestamp(min(t + every, end), timezone.utc).isoformat(),
                       "value": windows.get(t)}
                      for t in range(start // every * every, end, every)]
            return {"source": source, "field": field, "minutes": minutes,
                    "interval_seconds": every, "points": points, "history_origin": "cloud"}
        except (ValueError, TypeError, KeyError, OverflowError):
            raise CloudError("invalid_query_response") from None


def telemetry_line(source, message, stamp, *, data_origin='hardware'):
    """Encode only sensor fields; fixed measurement, tag set and timestamp."""
    if source not in CLOUD_MEASUREMENTS:
        return None
    if source=='gate':
        if data_origin not in ('hardware_gate_sim','synthetic'):return None
        validate_gate(message)
    fields = ["sample_present=1i"]
    for name in RANGES[source]:
        value = message.get(name)
        fields.append(f"{name}_valid={'true' if value is not None else 'false'}")
        if value is not None:
            fields.append(f"{name}={int(value)}i" if name.endswith("_raw") or (source=='gate' and not name.endswith('_cm'))
                          else f"{name}={float(value)!r}")
    if source == 'gate':
        for name in ('event_seq','uptime_ms'):
            fields.append(f'{name}={message[name]}i')
        fields.extend(['servo_enabled=false','simulation=true'])
        for name in ('u1_state','u2_state','gate_sim_state','last_event','control_mode','event_id'):
            fields.append(name+'="'+message[name]+'"')
    elif source == "uno":
        for slot in ("a1", "m1"):
            name = slot + "_occupied"
            value = message.get(name)
            fields.append(f"{name}_valid={'true' if value is not None else 'false'}")
            if value is not None:
                fields.append(f"{name}={'true' if value else 'false'}")
        value = message.get("vibration")
        fields.append(f"vibration_valid={'true' if value is not None else 'false'}")
        if value is not None:
            fields.append(f"vibration={'true' if value else 'false'}")
        if message.get("vibration_count") is not None:
            fields.append(f"vibration_count={int(message['vibration_count'])}i")
        fields.append('vibration_status="not_installed"')
    else:
        fields.append('gas_status="unconditioned_or_uncalibrated"')
    # datetime has microsecond precision. Avoid float rounding of epoch ns.
    delta = stamp - datetime(1970, 1, 1, tzinfo=timezone.utc)
    ns = (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    origin = data_origin if data_origin in ('synthetic','hardware_gate_sim') else 'hardware'
    extra = ',schema_version=2,actuation=disabled,boot_id='+message['boot_id'] if source=='gate' else ''
    return f"{CLOUD_MEASUREMENTS[source]},source={source},data_origin={origin}{extra} {','.join(fields)} {ns}"


class Outbox:
    """One SQLite database, one short transaction per batch, stable retry identities."""
    def __init__(self, path, max_records=MAX_RECORDS, max_db_bytes=MAX_DB_BYTES):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.max_records = max_records
        self.db = sqlite3.connect(self.path, timeout=1, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        self.db.execute(f"PRAGMA max_page_count={max_db_bytes // page_size}")
        if self.db.execute("PRAGMA page_count").fetchone()[0] * page_size > max_db_bytes:
            self.db.close()
            raise ValueError("Existing cloud outbox exceeds approved budget")
        self.db.execute("CREATE TABLE IF NOT EXISTS pending (id INTEGER PRIMARY KEY, line TEXT UNIQUE NOT NULL, created REAL NOT NULL)")
        self.db.commit()

    def put(self, rows):
        with self.lock, self.db:
            count = self.db.execute("SELECT count(*) FROM pending").fetchone()[0]
            dropped = 0
            for line, created in rows:
                if self.db.execute("SELECT 1 FROM pending WHERE line=?", (line,)).fetchone():
                    continue
                if count >= self.max_records:
                    dropped += 1
                    continue
                cursor = self.db.execute("INSERT OR IGNORE INTO pending(line, created) VALUES (?, ?)", (line, created))
                count += cursor.rowcount
            return dropped

    def batch(self):
        with self.lock:
            rows = self.db.execute("SELECT id,line,created FROM pending ORDER BY id LIMIT ?", (BATCH_SIZE,)).fetchall()
        size = 0
        result = []
        for row in rows:
            size += len(row[1].encode("utf-8")) + 1
            if size > MAX_BATCH_BYTES:
                break
            result.append(row)
        return result

    def ack(self, rows):
        with self.lock, self.db:
            self.db.executemany("DELETE FROM pending WHERE id=?", [(r[0],) for r in rows])

    def expire(self, cutoff):
        with self.lock, self.db:
            return self.db.execute("DELETE FROM pending WHERE created < ?", (cutoff,)).rowcount

    def depth(self):
        with self.lock:
            return self.db.execute("SELECT count(*) FROM pending").fetchone()[0]

    def close(self):
        with self.lock:
            self.db.close()


class CloudSync:
    """Bounded nonblocking handoff -> durable outbox -> independent HTTPS worker."""
    def __init__(self, client, outbox, *, data_origin='hardware'):
        self.client, self.outbox = client, outbox
        self.data_origin=data_origin
        self.stage = queue.Queue(maxsize=1000)
        self.lock = threading.Lock()
        self.dropped = 0
        self.uploaded = 0
        self.failures = 0
        self.last_success = None
        self.error = None
        self.pending = outbox.depth()
        self.stop = threading.Event()
        self.threads = []

    def start(self):
        self.threads = [threading.Thread(target=fn, daemon=True)
                        for fn in (self.persist, self.upload)]
        for thread in self.threads:
            thread.start()

    def submit(self, source, message, stamp):
        line = telemetry_line(source, message, stamp,data_origin=self.data_origin)
        if line is None:
            return
        try:
            self.stage.put_nowait((line, stamp.timestamp()))
        except queue.Full:
            with self.lock:
                self.dropped += 1

    def persist_batch(self, rows):
        try:
            dropped = self.outbox.put(rows)
            depth = self.outbox.depth()
            with self.lock:
                self.dropped += dropped
                self.pending = depth
        except sqlite3.Error:
            # SQLite transaction rolls back on failure. Count entire batch as lost.
            with self.lock:
                self.dropped += len(rows)
                self.failures += 1
                self.error = "local_outbox_error"

    def persist(self):
        while not self.stop.is_set() or not self.stage.empty():
            try:
                first = self.stage.get(timeout=0.2)
            except queue.Empty:
                continue
            rows = [first]
            for _ in range(99):
                try:
                    rows.append(self.stage.get_nowait())
                except queue.Empty:
                    break
            self.persist_batch(rows)

    def send(self, rows):
        if not rows or self.stop.is_set():
            return
        try:
            self.client.write([r[1] for r in rows])
        except CloudError as exc:
            # A partial 400/422 response may have written some points.
            # Split until a single bad point can be isolated; successful retry
            # retains the exact original primary key, never an upload timestamp.
            if exc.code in (400, 413, 422):
                if len(rows) > 1:
                    middle = len(rows) // 2
                    self.send(rows[:middle])
                    self.send(rows[middle:])
                    return
                self.outbox.ack(rows)
                with self.lock:
                    self.dropped += len(rows)
                    self.error = "permanent_record_rejected"
                return
            raise
        self.outbox.ack(rows)
        with self.lock:
            self.uploaded += len(rows)
            self.last_success = datetime.now(timezone.utc).isoformat()

    def upload(self):
        delay = INTERVAL
        while not self.stop.wait(delay):
            try:
                expired = self.outbox.expire(time.time() - RETENTION_SECONDS)
                rows = self.outbox.batch()
                if expired:
                    with self.lock:
                        self.dropped += expired
                if rows:
                    with self.lock:
                        self.error = None
                    self.send(rows)
                delay = INTERVAL
            except CloudError as exc:
                with self.lock:
                    self.failures += 1
                    self.error = str(exc.code)
                delay = max(exc.retry_after, min(300, delay * 2 + random.uniform(0, 3)))
                if exc.code in (401, 403, 404):
                    delay = max(delay, 300)
            except sqlite3.Error:
                with self.lock:
                    self.failures += 1
                    self.error = "local_outbox_error"
                delay = 30
            try:
                depth = self.outbox.depth()
                with self.lock:
                    self.pending = depth
            except sqlite3.Error:
                pass

    def snapshot(self):
        with self.lock:
            return {"enabled": True, "pending": self.pending,
                    "staging": self.stage.qsize(), "uploaded": self.uploaded,
                    "dropped": self.dropped, "failures": self.failures,
                    "last_success_utc": self.last_success, "error": self.error,
                    "transfer": self.client.usage() if hasattr(self.client, "usage") else {},
                    "retention_days": 30}

    def close(self):
        self.stop.set()
        # Allow in-flight I/O to finish; committed pending records survive.
        for thread in self.threads:
            thread.join(timeout=12)
        if all(not thread.is_alive() for thread in self.threads):
            self.outbox.close()


def start_optional_cloud(origin, prefix, local_bucket, *, gate_production_approved=False):
    """Never load production credentials from a synthetic backend."""
    legacy=(origin,prefix,local_bucket)==('hardware','parking','sensor_data')
    gate=gate_production_approved and (origin,prefix,local_bucket)==('hardware_gate_sim','parking','sensor_data')
    if not (legacy or gate):
        return None, None
    path = ROOT / ".secrets" / "cloud.json"
    if not path.exists():
        return None, None
    try:
        service = CloudSync(CloudClient(load_config(path)), Outbox(ROOT / ".runtime" / "cloud-outbox.sqlite3"),data_origin=origin)
        service.start()
        return service, None
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        LOG.warning("Cloud configuration/outbox unavailable; local monitoring continues")
        return None, "configuration_or_outbox_error"


def start_gate_test_cloud(origin,prefix,local_bucket):
    """Explicit isolated gate verification; never loads the production token pair."""
    if origin not in ('synthetic','hardware_gate_sim') or prefix!='parking/test' or local_bucket!='sensor_test':
        raise ValueError('Gate test cloud requires isolated routing')
    try:
        service=CloudSync(CloudClient(load_config(ROOT/'.secrets/cloud-test.json',testing=True)),
                          Outbox(ROOT/'.runtime/gate-test-cloud-outbox.sqlite3'),data_origin=origin)
        service.start();return service,None
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        LOG.warning('Isolated gate cloud unavailable; local monitoring continues')
        return None,'test_cloud_configuration_or_outbox_error'
