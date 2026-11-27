# Windows dashboard migration handoff

Updated 2026-11-27 (Bangkok): `feature/dashboard-webapp` at `046e1da` is combined
with `feature/parking-full-integration` from `fbad74a`, against camera repository
`7638868`. This is a feature-branch integration, not a merge into main or PR #5 approval.

Open **http://127.0.0.1:8081/#/dashboard**, or **http://127.0.0.1:8081/#/gate**
for both cameras, capture/upload, crop correction and Gemini/PaddleOCR analysis.
The session registration button is disabled. Sensor history is on
`#/admin/vehicles`; devices and G3 telemetry remain live.

## Which plan applies

The supplied `parking-integration-plan.md` and
`two-repo-dashboard-migration.md` are design inputs, not instructions to
re-enable their older workflows. Keep the newer owner-confirmed behavior:

- U1 D2/D3 is entrance; U2 D4/D5 starts local simulated exit. Historical G2 U2
  passage data keeps its original meaning. New G3 state is separate.
- The confirmed five `parking/v1/*` topics are mirrored on `parking/test/v1/*`.
  Do not introduce the older `parking/gate/*`, arrival ACK or A1 availability topics.
- No sensor-based allocator: the camera service owns compatibility, bays,
  reservation, session matching and all parking persistence.
- Exit plate location now uses the teammate's released Gemini update, followed
  by PaddleOCR. The older EasyOCR / no-Gemini exit description is superseded.
- Use the existing isolated SQLite ledger on port 8001. Supabase staging
  migrations and production cutover belong to the teammate and remain pending.
- SG90 stays disconnected and disabled; confirmed passage requires the
  controller's ordinary completed feedback, never a dashboard action that
  directly marks a session left.

## Start, stop and rollback

Both checkouts retain their existing `.env` files and separate `.venv` folders.
The gateway uses the **already installed** FastAPI/httpx/uvicorn/python-dotenv
packages in the camera venv; it imports no recognition pipeline or OCR model.
No new package, container, firmware or wiring change is required.

From `C:\CEDT\Iot\sensor-monitoring`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-unified-dashboard.ps1
```

| Service | Address | Ownership and data |
|---|---|---|
| Unified browser entry | `http://127.0.0.1:8081` | Async gateway; combined dashboard, read projections and same-origin analysis |
| Original sensor backend | `http://127.0.0.1:5000` | Existing production sensor telemetry/history/cloud configuration |
| G3 sensor backend | `http://127.0.0.1:5001` | Existing isolated hardware simulation, `sensor_test`, existing durable G3 ledger |
| Camera/parking API | `http://127.0.0.1:8001` | Local simulation; `data/runtime/windows-joint-test/` in camera checkout |
| InfluxDB | `http://127.0.0.1:8086` | Existing storage, seven-day retention retained |
| MQTT | Saved laptop Wi-Fi address, TCP 1883 | Existing authenticated broker and ACLs |

8080 is occupied by another application on this laptop. Use `-Port` to choose
another free gateway port; no unrelated service is stopped. The launcher reuses
an already running local simulation API, starts missing services, and records
only processes it starts in `.runtime/unified-processes.json`. Logs are in
`.runtime/unified-*.{stdout,stderr}.log`; native logs keep their previous paths.
The launcher excludes localhost from system HTTP proxies.

Inspect connections without OCR or parking commits:

```powershell
& C:\CEDT\Iot\intelligence-parking-lot\.venv\Scripts\python.exe scripts/check-unified-dashboard.py
```

Stop only launcher-owned migration processes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop-unified-dashboard.ps1
```

Previously running services, databases, pending feedback, photos, native sensor
services and the separately started camera API remain intact. Rollback is to
stop this gateway and use the original 5000/5001 and 8001 URLs. No database or
firmware downgrade is needed. An intentional `gate-demo.stop` prevents automatic
restart until its cause is inspected. Do not clear safety holds automatically.

## Routes used by the combined web version

Use relative same-origin paths in the new sensor dashboard assets. Continue
shipping its HTML and JS in `dashboard/templates` and `dashboard/static`.
The two UI conflicts were resolved using the dashboard branch's G3-aware files.
The integration adds API aliases, permits `blob:` images for capture/crops,
corrects exit Gemini timing/model display and G3 device freshness, and replaces
automatic sample parking records with Unknown/offline projections.

| Browser GET path | Source / UI guidance |
|---|---|
| `/`, `/static/*` | Existing Flask page and assets |
| `/api/latest` | Isolated sensor view including `sources.esp32` and `parking3`; honor freshness |
| `/api/history`, `/api/cloud/history`, `/api/gate/events` | Existing sensor APIs; G2 remains historically labeled |
| `/camera/stream?camera=entrance` or `exit` | Direct async MJPEG relay; no Flask worker is held |
| `/camera/snapshot?camera=entrance` or `exit` | Fresh role-specific JPEG; previews are not recognition captures |
| `/parking/status` | Teammate's unchanged capacity/spaces projection; label local simulation |
| `/parking/history?limit=30` | Teammate's unchanged history projection |
| `/parking/media/{uuid}` | Teammate's photo route; keep its UUID rather than filesystem/Storage URLs |
| `/api/integration/readiness` | Sanitized service/freshness/isolation status, no capture or AI work |
| `/api/camera/stream?camera=entrance` or `exit` | Combined UI alias for async stream; accepts its `t` cache-buster and `probe=1` |
| `/api/camera/frame?camera=entrance` or `exit` | Combined UI alias for fresh snapshot |
| `/api/parking/status`, `/api/parking/history`, `/api/parking/media/{uuid}` | Combined UI aliases for authoritative reads |

Readiness separates fresh telemetry from `gate_cycle_ready`. A latched hold can
report fresh sensor data while `gate_cycle_ready:false`; `gate_phase_code` and
`gate_reason_code` identify its existing controller state.

Each lane preview needs independent loaded/error/reconnect indicators. Stop its
`img` stream when hidden; reconnect after a short delay when the stream ends.
The relay has a 15-second upstream read timeout; it never replays a cached frame.
Maintain separate availability/error states for parking and sensors. Display UTC
parking timestamps in `Asia/Bangkok`, plate text through text nodes, and historical
G2 separately from G3. Do not derive availability from U1/U2.

The current `parking3` object exposes `enabled`, `fresh`, `telemetry`,
`recognition`, `command_outcome`, `pending_feedback`, `clock_verified` and
`session_release`. Its telemetry has `schema_version:3`,
`mode:"entrance_exit_sim"`, numeric `phase` and `lane`, `cycle`, sensor states,
`minimum_open_ms`, and `servo_enabled:false`. Existing dashboard code already
maps these enums. A missing or stale value is Unknown, not a zero or a free bay.

All routes share the existing dashboard Basic authentication configuration.
The current owner-configured `DASHBOARD_AUTH_REQUIRED=no` remains loopback-only;
setting it to `yes` also protects streams and photos. Credentials are read only
server-side. Upstreams are fixed loopback addresses; user-supplied proxy URLs,
redirects and remote clients are rejected. No CORS relaxation is needed.

**Only POST `/api/parking/analyze` is enabled**, with a matching Origin,
same-origin fetch check, shared authentication and bounded upload. It forwards
to the existing Flask multipart/schema validation before the camera API. This
saves an observation in isolated test storage; it does not command a gate or
change a session. Both `/parking/commit` and `/api/parking/commit`, sensor
mutation, raw `/parking/analyze` and synthetic recognition remain blocked.
`PARKING_SIMULATOR_COMMIT=no` is also the Flask default and local configuration.
Future operator session/reconciliation actions still need the agreed API. The
standalone 8001 diagnostics page retains its existing behavior; do not use its
instant registration button as passage evidence.

## MQTT and session workflow boundary

The existing G3 backend already receives hardware, publishes correlated arrival
and feedback, validates authorized entrance commands and persists retries.
Use [the confirmed interface](parking-v1-confirmed.md), including its exact
IDs, Unicode/ASCII LCD fields, expiry and dedup behavior. A machine-readable
synthetic example set is [parking-v1-migration.json](fixtures/parking-v1-migration.json).
Examples are documentation, not live messages; refresh IDs/times for an approved
isolated test. No application arrival ACK is added.

The historical `scripts/run-parking-http.py` remains an **explicit isolated
bench tool**. The new launcher never starts it. Its legacy `/parking/commit`
admission occurs before passage and cannot implement the migration's full
reservation lifecycle. Do not turn it into the new deployment writer.

Before enabling the teammate's new worker, obtain its published OpenAPI and
shared fixtures for these missing lifecycle capabilities; route names and
request fields are deliberately not invented here:

1. Durable arrival/observation identity and atomic compatible-bay reservation
   with an authorized command outbox. Confirmed entrance passage creates the visit.
2. Durable exit match bound to the **specific session active at that arrival**.
   Finalization verifies that exact session is still active and joins the same
   arrival's `completed` / `passage_confirmed:true` evidence. Either input may
   arrive first. OCR or exit arrival alone must never release a bay.
3. Durable feedback storage before recorded ACK, replay/conflicting-ID handling,
   reservation cancellation only with known no-passage, and reconciliation for
   uncertain movement/restarts. The server must enforce this independently of
   the browser and of other HTTP clients.

The current CommitRequest accepts only `observation_id` and `request_id`; it
has no expected-session precondition or passage-aware finalization. Its immediate
allocator/releaser cannot be exposed as the migrated workflow. No teammate code,
schema, session rows or Supabase state was modified during this preparation.

## Actual verification

Current [combined UI connection receipt](evidence/combined-dashboard-readiness.json):
merged page with registration disabled, both aliased MJPEG streams, both fresh
lane-correct snapshots, live sensors/history and parking reads all passed.
The same-origin analysis endpoint rejected a missing image with 400, confirming
its validation path without an OCR call. Session write attempts returned 405.
Four focused gateway tests and 17 affected Flask web/proxy tests passed;
JavaScript syntax and rendered element references were checked. No automated
browser run or new real-image OCR/gate-cycle test was performed in this merge.

The earlier connection preparation below is retained as a separate checkpoint.

[Sanitized connection receipt](evidence/dashboard-migration-readiness.json):

- Both proxied streams returned MJPEG with JPEG data, and both fresh snapshots
  returned JPEG with the correct lane header.
- With both streams open, page, live sensors, local history, parking status,
  parking history and readiness returned HTTP 200. Fresh environment and G3
  telemetry, connected MQTT/storage, verified clock, zero pending feedback.
- Three focused gateway checks passed: shared authentication/write blocking,
  correct stream/sensor routing, and explicit offline/fixed-upstream behavior.
- Launcher stop/restart passed; only its recorded process trees were stopped.
  An observed Windows startup race (`Process.Path` briefly null) was fixed by
  recording the launched executable's full path, retaining exact start-time checks.
- No parking commits, MQTT gate commands, new sessions, firmware uploads or
  OCR requests. The API may warm existing OCR on snapshot as designed. Test lot
  remained empty. No plates, images or credentials are in Git evidence.

An initial native startup failed during localhost InfluxDB bootstrap; retry with
`NO_PROXY=127.0.0.1,localhost` passed. The first concurrent connection check failed
with an upstream HTTP error; individual routes and the next concurrent check
passed. This is a short connection check, not a sustained multi-tab load test.

The UNO currently reports a latched `hold` / `sensor_unknown` from an earlier
reading, while both sensors now read clear. No reset or movement was sent. A
supervised reset and three joint entrance/duplicate/exit tests remain for the
approved passage-aware worker. Earlier firmware evidence is
reused; no hardware diagnostics or full regression suite was rerun.

To run only the new gateway tests, using the camera service's existing packages:

```powershell
& C:\CEDT\Iot\intelligence-parking-lot\.venv\Scripts\python.exe -m unittest discover -s tests/integration -p test_unified_gateway.py -v
```
