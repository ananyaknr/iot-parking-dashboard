# Intelligence Parking Lot — Sensor Monitoring

## Sensor and gate integration handoff

Development branch: **`feature/gate-hardware-integration`**, tracked by
[PR #4](https://github.com/ananyaknr/iot-parking-dashboard/pull/4). Sensor cloud
deployment from PR #3 is merged. Gate integration is a **servo-disabled
simulation**; physical end-to-end acceptance and production migration are
separate approval steps. See the [verification ledger](docs/gate-v2-verification.md).

The 2026-11-26 servo-disabled hardware demonstration passed: bidirectional UART,
U1 arrival/U2 passage cycle (counts 1/1), vibration response, CAR/SUPERCAR LCD,
environment readings and actual local/cloud dashboard history. Standalone
operator guidance uses a 120-second cycle window; integrated authorization
remains 20 seconds. See [corrected wiring](docs/wiring.md) for the separate
breadboards and 1 kΩ upper / 2 kΩ lower UART divider. Servo/camera integration,
calibration and long-duration acceptance remain pending; PR #4 is unmerged.

Implemented in this branch:

- UNO U1 arrival and U2 passage sensing, simulated opening/closing with clearance
  checks, KY-002 sampled vibration transitions, and LCD plate/vehicle labels.
- ESP32 UART forwarding, environmental sensing, authenticated MQTT and correlated
  test LCD commands. Gate USB baud is **115200 on both boards**; inter-board UART
  is **19200**.
- Backend schema validation, boot-scoped event IDs/counters, event history,
  freshness reporting and the existing dashboard with six history charts.
- Isolated local `sensor_test` and optional cloud `parking_sensor_test` storage,
  preserving the existing production sensor archive.
- A disabled recognition adapter and [shared interface proposal](docs/integration-v2-proposal.md).
  Capture, recognition, photos, parking sessions and entry/exit matching remain
  teammate-owned. Camera/session records and license plates are excluded from
  sensor cloud storage. U1/U2 counters do not represent bay occupancy/allocation.

### Sync this work

Commit or stash your own local changes first, then:

```powershell
git fetch origin
git switch feature/gate-hardware-integration
git pull --ff-only origin feature/gate-hardware-integration
```

Integrated sketches: `firmware/uno_gate_sim/uno_gate_sim.ino` and
`firmware/esp32_gate_sim/esp32_gate_sim.ino`, using `firmware/gate_common`.
Do not replace running firmware just to sync source.

The separate `scripts/gate_hardware_test/gate_hardware_test.ino` is an optional
standalone UNO bench diagnostic at **9600 baud**. LCD commands are `WAIT`, `READ`,
`LCD|AB1234|car` and `LCD|AB1234|supercar`. It does not provide the integrated
UART/MQTT pipeline. Neither gate sketch drives the servo; D9 remains unused.

[README_ice.md](README_ice.md) contains the teammate's camera/recognition project
notes. Use the v2 proposal for this branch's arrival/passage roles and integration
boundaries.

### Run the isolated gate dashboard

With native services running, `.venv\Scripts\python.exe scripts/run-gate-demo.py`
starts an isolated hardware dashboard at **http://127.0.0.1:5001**, stores only in
local `sensor_test`, and optionally archives to cloud `parking_sensor_test` using
the existing scoped test configuration. It never enables production gate routing.
The normal production backend and `sensor_data` remain independent. Stop the demo
with Ctrl+C or create `.runtime/gate-demo.stop`; deliberately remove that file
before restarting. See [bench procedure](docs/gate-sim-test.md).

Credentials, firmware `secrets.h`, native tools, virtual environments and runtime
history are intentionally not synced. Configure credentials locally using the
existing setup scripts; never commit tokens. Cloud is Free Plan only, with
`parking_sensor_data` and `parking_sensor_test` each retained for 30 days. Keep
test data in test buckets and the servo disconnected. Production migration and
merge require approval.

Native Windows deployment: **UNO → UART → ESP32 → Wi-Fi → authenticated Mosquitto → Python/Flask → InfluxDB OSS 2.x → local dashboard**.

No Docker, WSL, Node.js, React or Grafana is required. Earlier Compose/Grafana files are preserved as inactive reference material. Do not run them for this deployment.

Issue #1 remediation: see the [ownership and rubric ledger](docs/issue-1-status.md),
[proposed team interfaces](docs/integration-v1-proposal.md), [sensor cloud plan](docs/sensor-cloud-plan.md)
and [verification evidence](docs/issue-1-verification.md). Shared interfaces remain proposed;
gate hardware acceptance is separate from the merged sensor cloud deployment. Node.js is optional for browser regression testing only.

## Start and stop

From this project directory in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-native.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop-native.ps1
```

Start is idempotent for recorded, verified project-owned processes. Stop checks executable path and start time before stopping a recorded PID; it does not stop unrelated services. Python receives a stop-file request before the native processes are stopped. InfluxDB keeps its Bolt database and write-ahead log under `.runtime/influxdb` for restart recovery.

- Dashboard: **http://127.0.0.1:5000**. Browser HTTP Basic login uses the generated local credentials in `.env`: `GRAFANA_USERNAME` / `GRAFANA_PASSWORD` from the earlier setup are currently reused. These variable names do not indicate that Grafana is running. `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` can override them.
- InfluxDB: **http://127.0.0.1:8086**, local only. Organization `parking`, bucket `sensor_data`, seven-day retention.
- MQTT: the PC LAN IPv4 in `.env` (`MQTT_BIND_IP`), TCP 1883, username/password required. Never use localhost as the ESP32 broker address.
- Logs: `docs/runtime-logs`; runtime databases/process ledger: `.runtime`; credentials: `.env`, `.secrets`, and `firmware/esp32_gateway/secrets.h`. These paths are ignored by Git.

Keep the PC and ESP32 on the same reachable trusted network. The scoped Windows firewall rule permits only this Mosquitto executable on TCP 1883 from the local subnet. Apply/update it in an Administrator PowerShell when the PC's IP changes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/allow-mqtt-firewall.ps1
```

If changing networks, stop services, update only `MQTT_BIND_IP` in `.env` to the PC's actual LAN IPv4, regenerate local `secrets.h`, update the scoped firewall rule and restart services. Recompile/upload the ESP32 with the new broker address. The UNO does not need to be reuploaded.

## Local dependencies

Python 3.12 is already installed. The project virtual environment contains Flask, Waitress, Paho MQTT 2.x and the InfluxDB Python client; exact tested versions are in `backend/requirements-lock.txt`. Waitress serves Flask locally; the development server/debugger is not used.

Native binaries are project-local:

- Mosquitto 2.0.22 from the [official Windows distribution](https://mosquitto.org/files/binary/win64/).
- InfluxDB OSS 2.10.1 from [InfluxData's official downloads](https://www.influxdata.com/downloads/), with the published SHA-256 verified.
- Chart.js 4.5.1 is saved in `dashboard/static/vendor`, including its license. The dashboard makes no runtime CDN requests.
- A small project-local 7-Zip extraction helper unpacked Mosquitto without running its installer or registering global services.

Persistent data is retained for seven days. Retention is not a hard disk quota. Measure current usage, including retained native archives:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/measure-footprint.ps1
```

## ESP32 configuration

The original working source remains in `scripts/integrated-sensors/integrated-sensors.ino`. The MQTT extension is `firmware/esp32_gateway/esp32_gateway.ino`; the UNO sketch is preserved.

Enter Wi-Fi credentials locally, never in chat or source control. Run either the local PowerShell prompt or the temporary loopback-only browser form:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/configure-wifi.ps1 -Ssid YOUR_HOTSPOT_NAME
.\.venv\Scripts\python.exe scripts/wifi-setup.py
```

The browser form is at http://127.0.0.1:8765, stops after saving/timeout, and defaults to the current demonstration hotspot `jm`. Edit the SSID if needed. It accepts only loopback requests with matching Host, same-origin POST and a CSRF token. Passwords are never returned in responses or logs.

ChulaWiFi uses WPA2-Enterprise (PEAP/MSCHAPv2), not a shared password. An optional `scripts/configure-enterprise.ps1` helper supports an official CA certificate, authentication-server name and locally entered CUNET credentials. Certificate verification is not disabled. A normal 2.4 GHz hotspot is the selected demo route because the university CA was unavailable. No university account password was requested in chat.

The existing Arduino IDE toolchain has `esp32:esp32` 4.0.0, DHT sensor library and PubSubClient 2.8. Reuse it to compile for the confirmed board. Verify the connected board before any approved upload; COM assignments are machine-specific. ESP32 USB debug baud is 115200. The legacy UNO sketch uses 9600 baud; gate v2 uses 115200 USB baud on both boards and 19200 inter-board UART. Do not change wiring merely to sync this branch.

Wi-Fi/MQTT reconnect attempts run in a separate task, so slow network connections do not indefinitely block UART reception. The MQTT buffer is 768 bytes. Incoming UNO messages are published only once, non-retained; offline/expired queued messages are dropped, not replayed as fresh. Environmental readings are generated every 2.5 seconds. Publish failures are reported on USB serial.

## Data behavior and APIs

Topics:

| Topic | Source | Storage measurement |
|---|---|---|
| `parking/node/telemetry` | UNO, forwarded by ESP32 UART | `parking_node` |
| `parking/gateway/telemetry` | ESP32 environment | `parking_gateway` |
| `parking/camera/result` | Teammate camera interface | `parking_camera` |

The original UNO and ESP32 JSON schemas are preserved. See [camera-interface.md](docs/camera-interface.md) for the separate camera contract. Camera values are advisory and do not override A1 or make M1 eligible for allocation.

The backend validates keys, source/topic agreement, JSON types, ranges and nonfinite/duplicate values. Malformed payloads are rejected without stopping the service and immediately invalidate that source's current view. Missing measurements are not written as zero. Freshness uses monotonic receive time with a ten-second timeout. Retained telemetry received on subscription is rejected. UTC receive timestamps are assigned by the backend.

Measurements use `kind=telemetry` for actual received messages and `kind=status` for one-second freshness/current-state projections. `data_origin=hardware` is the normal source; synthetic tests use a separate bucket and `data_origin=synthetic`. Numeric status fields are omitted when missing/stale; validity flags explicitly become false. A1 allocation requires a fresh valid vacant reading. M1 and vibration remain not installed.

Authenticated local APIs:

- `GET /api/latest`: all three source views, validity, freshness, current values, source receive timestamps and broker/database connection state.
- `GET /api/history?source=uno&field=a1_distance_cm&minutes=30`: UTC historical points. Source/field identifiers are allowlisted; range is 1–10080 minutes and results are windowed to approximately 600 points.
- `GET /health`: readiness only; no credentials or telemetry exposed.

The responsive dashboard refreshes live cards every two seconds and history every ten seconds. Missing/stale sources display Unknown. MQ-2 values are raw ADC and explicitly uncalibrated, never ppm.

Broker connection, ingestion, source freshness and local write health are reported separately.
Database writes run in a bounded background worker; `/api/latest` exposes receive/write queue
depth, rejection/discard/drop counters and write failures. Backlogs are volatile and can lose
data at capacity or shutdown. History uses full timestamps on a numeric axis; missing windows
and windows containing invalid status readings display as gaps. Display dates use browser local time.

## Verification

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
.\.venv\Scripts\python.exe scripts/test-native-pipeline.py
```

The smoke test publishes **explicitly synthetic** messages only to `parking/test/*`, starts a separate test backend on localhost:5001, and stores them only in the seven-day `sensor_test` bucket. It tests all three topics, malformed/null inputs, ten-second staleness, recovery, M1 exclusion and history retrieval. It never publishes synthetic data on the real sensor topics.

Actual physical tests and deployment evidence are recorded in [docs/test-results.md](docs/test-results.md). Synthetic results do not establish Wi-Fi connectivity or physical sensor acceptance. MQ-2 conditioning/calibration, M1 and vibration installation remain outstanding.

## Optional sensor cloud archive

Cloud Serverless sync is disabled until `.secrets/cloud.json` is configured. See [cloud setup and acceptance](docs/sensor-cloud-setup.md). Production exports only accepted UNO/ESP32 hardware telemetry; synthetic, camera/session and one-second status records are excluded. The local dashboard and gate integration do not depend on cloud. No paid upgrade is permitted. Cloud history is on demand and aggregates raw received telemetry, unlike local status history.
