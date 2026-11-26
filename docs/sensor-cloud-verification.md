# Sensor cloud verification ledger

Date: 2026-11-26, Asia/Bangkok. Branch: `feature/sensor-cloud-storage`, PR #3.
**Real cloud deployment is not yet accepted. PR #3 remains draft.** No paid resources or upgrades have been requested. Existing sensor-only implementation was reviewed and patched; it was not replaced.

## Executed software checks

| Check | Actual result |
| --- | --- |
| Original Python suite on feature branch | PASS: 24 tests, 0.542 s |
| Final expanded Python suite | PASS: 35 tests, 0.480 s, including approved empty-bucket rename, cloud API isolation, disk errors and authentication/server/network retry retention |
| JavaScript syntax | PASS: dashboard app and Chrome runner |
| Real Chrome dashboard, isolated HTTP fixtures | PASS: original local charts/health/failures/recovery/mobile checks plus cloud selector, 30-day query, on-demand refresh, no automatic cloud polling over 10.5 s, cloud errors with live cards continuing and return to local history |
| Isolated real Mosquitto/InfluxDB/Flask pipeline | PASS: ACL publish/read allow/deny, real Flux 5m/24h/7d and gaps, retained messages/restart, inconsistent occupancy, freshness, database outage/restart with continued ingestion/backlog recovery, broker reconnect fail-closed |
| Windows credential file protection | PASS: created a dummy file, restricted its ACL through the configuration helper, read/wrote/removed it successfully; no real token involved |
| Real SQLite disk-cap exercise | PASS: reached SQLITE_FULL at 25,800 committed synthetic rows; committed rows reopened successfully; zero network requests |

Cloud unit checks cover durable SQLite reopen, identical retries, permanent-record isolation, expiry, duplicate handling at capacity, stop without consuming unsent records, 429 HTTP-date Retry-After and truncated HTTP response handling. Resource setup checks refuse Free Plan capacity overflow and foreign DBRP remapping, and leave already-correct resources unchanged.

Resolved defects: configuration did not enforce Windows file permissions; duplicates at full capacity falsely counted as drops; truncated HTTP responses could terminate the upload thread; HTTP-date Retry-After was ignored; recursive split retries could continue after stop; local outbox failures did not increment the failure counter. Added actual transfer counters for timed measurements. No token or HTTP error response body is logged.

## Actual disk observations

`scripts/measure-cloud-outbox.py` used temporary synthetic SQLite rows only and made **zero network requests**. It reported:

```json
{"committed_rows":25800,"database_bytes":15708160,"sampled_peak_database_plus_journal_bytes":15708160,"sampled_peak_allocated_bytes":15708160,"capacity_error":"SQLITE_FULL","elapsed_seconds":4.0,"reopen":"PASS"}
```

Its temporary files were removed on normal exit. The journal was sampled every 2 ms; these are observed peaks, not proof of every transient filesystem allocation. Capacity depends on row size; 50,000 is a count ceiling, not guaranteed usable capacity. The configured database page cap remains 15 MiB and the target combined database/journal budget is 32 MiB.

At **2026-11-26 05:23:00 UTC (12:23 Bangkok)** the existing footprint script reported native total 546,590,028 bytes, `.runtime` 273,668,826 bytes and free drive 11,424,210,944 bytes. The production local Influx directory measured 70,853,256 logical file bytes. `.runtime` includes retained isolated native-test databases, so it is not a measure of production growth. No production cloud outbox existed at this observation. These are point-in-time measurements, not a 24-hour growth rate.

Provider quota consumption has **not** been measured yet. Local `attempted_write_bytes` and `acknowledged_write_bytes` are process-local transport counters, not normalized cloud ingestion or organization-wide usage. Real acceptance must record a timed interval and the provider Usage page alongside counters, including restarts and retry traffic. Do not report zero organization usage just because this backend is unconfigured.

## Real deployment / hardware status

| Acceptance item | Current evidence/status |
| --- | --- |
| Free Plan account | User reports being at a Cloud Serverless Free Plan organization dashboard; account UI not independently inspected |
| Two buckets, 30-day retention and default DBRP mappings | Regional URL supplied: `https://us-east-1-1.aws.cloud2.influxdata.com`. User confirmed `iot_parking` is empty and explicitly approved renaming it to `parking_sensor_data`. Approved rename, test bucket and DBRP setup prepared; actual provider readback pending local setup-token entry |
| Bucket-scoped runtime credentials | Pending user entry via local interactive script; `.secrets/cloud.json` and `cloud-test.json` absent at initial inspection |
| Real isolated cloud write/read/duplicate and token-role verification | Attempted; stopped at missing local test configuration with `Cloud verification configuration/response unavailable; no PASS claimed.` No provider requests or real-provider PASS |
| Production cloud writes from actual UNO/ESP32 | Pending cloud configuration; fresh hardware telemetry restored as recorded below |
| Existing dashboard displays actual cloud history | Pending actual writes/readback; fixture browser tests are not this acceptance |
| Real internet disconnection, durable buffering, backend restart, recovery/duplicate handling and local operation | Pending real provider/hardware baseline; unit/native outage results do not substitute |

Native start was attempted. Existing local InfluxDB became healthy; the authenticated dashboard API responded with `storage_connected=true`, `mqtt_connected=false`, and both UNO/ESP32 stale with no receive timestamp. Cloud was disabled. Start readiness correctly failed. Broker configuration uses `172.20.10.12`, but current PC Wi-Fi was observed as `10.203.218.185`. User was asked to reconnect PC and ESP32 to the original demo hotspot to preserve compiled firmware configuration. No firmware, wiring, firewall or network changes were made by this work. No synthetic data was published to production topics or cloud buckets.

Update at **2026-11-26 06:22:57 UTC (13:22 Bangkok)**: user reconnected the original hotspot; the PC again reported `172.20.10.12`. Native start succeeded. Authenticated API reported `mqtt_connected=true`, `storage_connected=true`, and both UNO/ESP32 `fresh=true`, `payload_valid=true`, with actual receive timestamps 06:22:57 UTC and 06:22:55 UTC respectively. This resolves the local network/hardware ingestion blocker. It does not establish any cloud writes or cloud acceptance; credentials remain pending.

User subsequently supplied the US East regional URL, identified `iot_parking`, confirmed it is empty and approved its rename to `parking_sensor_data`. The first local setup attempt returned HTTP 400; its exact request was not captured, so no rename/resource success is inferred. Review found missing organization IDs in create/DBRP requests. Setup now derives the organization from bucket metadata (or an unambiguous organization lookup), includes it explicitly, and reports/saves only the failing method, endpoint and HTTP status without tokens or response bodies. All 35 Python tests passed after this correction (0.787 s), including the approved rename preserving the bucket ID and organization-scoped create payloads. A corrected local prompt was opened for retry; real provider readback is still required.

## Reproduce / continue

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
node --check dashboard/static/app.js
node --check scripts/test-dashboard.cjs
node scripts/test-dashboard.cjs
.\.venv\Scripts\python.exe scripts/test-isolated-native.py
.\.venv\Scripts\python.exe scripts/measure-cloud-outbox.py

# Interactive user-only entry, never pipe tokens:
.\.venv\Scripts\python.exe scripts/configure-cloud-resources.py
.\.venv\Scripts\python.exe scripts/configure-cloud.py --test
.\.venv\Scripts\python.exe scripts/test-cloud-pipeline.py
# Only after isolated cloud acceptance:
.\.venv\Scripts\python.exe scripts/configure-cloud.py
```

The resource helper saves only a sanitized receipt at `.runtime/cloud-resources.json`. The real test script saves a sanitized result at `.runtime/cloud-test-verification.json`, including logical point count, synthetic timestamp and byte counters. Runtime credentials remain ignored and server-side. Browser/Computer Use tools failed initialization with `failed to write kernel assets: The system cannot find the path specified`; account sign-in, token creation and local entry are therefore guided user actions. No screenshot or public evidence may contain tokens, plates or photos.
