# Minimum joint integration — PR #5

Current readiness: Windows checkout updated to **7638868**, separate .venv and
approved API/OCR dependencies installed, all three OCR models checksum-verified.
The API is running on http://127.0.0.1:8001 with isolated local SQLite storage;
actual PR #5 OpenAPI/storage/simulation preflight passed. The bridge is not
running. Owner deferred shared camera Wi-Fi and left; all three joint tests
remain pending. Earlier Mac-only/uncommitted-update blockers below are historical
and resolved by this Windows setup. No gate tests run unattended.

Continues e88ca05. Inspected teammate main **1058ed1b8c6741266c6430b090f3b2ec7014a74f**:
README, sensor-dashboard-integration.md, app/main.py, parking_api.py,
parking_store.py, parking_recognition.py and the referenced docs/openapi.json.
The running service's OpenAPI is checked again before enabling the adapter.
No teammate files, firmware, wiring or production services were changed.

## Minimum bridge

Run scripts/run-parking-http.py beside the existing isolated gate backend.
It uses existing Python/Paho, SQLite and standard-library HTTP only. Topics stay
parking/test/v1/arrival, gate/command, gate/ack, gate/feedback and gate/feedback/ack.
Only this bridge should consume these events as the parking decision service.
Stop mock responders/recorders during joint tests.

Entrance: fresh GET /camera/snapshot?camera=entrance → multipart POST
/parking/analyze with exactly image and camera → persist observation_id against
arrival_id → POST /parking/commit with exactly observation_id and stable
request_id `joint:<arrival_id>` → approved server decision → existing correlated
five-second OPEN. The bridge does not allocate bays. The service's entry commit
is its admission/reservation ledger and counts the selected bay occupied.

Duplicate arrivals do not recapture/reanalyze/recommit or create another command.
HTTP retries use the persisted observation/request identity; persisted MQTT OPEN
retries keep their original IDs/payload until ACK or expiry. Uncertain entrance
restart is review, never a fresh capture or OPEN. Network/analysis uncertainty
requires operator review; a lost HTTP response must never be retried with new IDs.

Exit: U2 still opens locally without a remote command. The bridge captures and
analyzes exit, persists that observation, and **does not call commit yet**.
Only durable same-arrival exit feedback with state=completed,
passage_confirmed=true, simulation=true and command_id=null enables exit commit.
The teammate's transaction then performs its own plate/session matching and
releases only that matching bay. Unmatched decisions remain review. Feedback may
arrive before analysis; both orders are supported. Stable request IDs make a
lost exit commit response retryable without a second release.

Feedback receipts acknowledge durable storage in .runtime/joint-http-test.sqlite3,
not successful session release. Pending exit commits remain in that ledger and
retry after reconnect/restart. No direct session/database/Supabase writes occur.
Original plates stay in ignored runtime data. ASCII plates up to 16 characters
display directly; Unicode requires an explicit private JSON LCD mapping file,
passed with --lcd-map. No guessed transliteration or truncation is used.

## Same-Windows-laptop run instructions

Prerequisites: teammate checkout with its working OCR update, existing Python
environment/models/Gemini configuration, and both cameras reachable from this
laptop. This task does not install an additional OCR stack or heavyweight models.
The uncommitted Mac exit OCR update must first be supplied by its owner; GitHub
main does not include that change. Keep each repository in its own environment.

In a PowerShell terminal inside the teammate checkout, retain its private .env
and set these process-only overrides before starting its service:

```powershell
$env:PARKING_BACKEND='local'
$env:PARKING_DATABASE_PATH=Join-Path $PWD 'data/runtime/windows-joint-test/parking.sqlite3'
$env:PARKING_STORAGE_PATH=Join-Path $PWD 'data/runtime/windows-joint-test/photos'
$env:PARKING_REQUIRE_FRESH_SENSORS='false'
$env:ESP32_ENTRANCE_CAPTURE_URL='http://172.20.10.4/capture'
$env:ESP32_EXIT_CAPTURE_URL='http://172.20.10.3/capture'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Use a new isolated directory for a new run, but retain it through retries.
Never point at the shared Supabase instance on port 8000. Verify
http://127.0.0.1:8001/parking/status reports storage=local and gate_mode=simulation.
Use only a clearly labeled test vehicle/plate; do not import real sessions.

Inside sensor-monitoring, keep existing native services running. If stopped,
start them with `powershell -File scripts/start-native.ps1`. In a second terminal:

```powershell
.\.venv\Scripts\python.exe scripts/run-gate-demo.py
```

If port 5001 is already serving the isolated backend, reuse it; do not start a
second backend. In a third terminal:

```powershell
.\.venv\Scripts\python.exe scripts/run-parking-http.py --api-url http://127.0.0.1:8001 --test-storage-confirmed --check
.\.venv\Scripts\python.exe scripts/run-parking-http.py --api-url http://127.0.0.1:8001 --test-storage-confirmed
```

For Unicode, add `--lcd-map .secrets/joint-lcd-map.json`, whose keys are original
recognized test plates and values are approved printable ASCII representations.
Keep that mapping private. Ctrl+C stops only the bridge. Keep SG90 disconnected.

## Exactly three joint acceptance tests

1. **Entrance:** start with both zones clear and one test plate in the entrance
   camera. Trigger U1. Save only sanitized arrival/observation/decision IDs,
   capture hash, assigned bay/session, accepted ACK and controller cycle count.
   Verify the server status identifies that same reserved session and one OPEN.
   Confirm LCD visually; then explicitly supervise CONFIRM/CLOSE as previously
   verified. Never synthesize passage feedback to make the test pass.
2. **Duplicate entrance:** republish the exact original MQTT arrival and repeat
   POST /parking/commit using the stored observation_id and the same
   `joint:<arrival_id>` request_id. Verify decision.replayed=true, same
   decision/session/bay, one active session and unchanged controller cycle count.
   Do not take a new snapshot or invent a second request ID.
3. **Matched exit:** present the same test plate to the exit camera and trigger
   U2 while U1 stays clear. Verify local OPEN with no MQTT exit command. Before
   passage confirmation the original session/bay must remain occupied. Explicitly
   confirm passage and close safely. Verify completed confirmed feedback, then
   exit decision matches the original session/bay and status releases that bay.

Results are recorded in evidence/parking-joint-minimum.json. These new tests
are blocked, not substitutes for the earlier e88ca05 firmware/protocol tests.
No regression suite, OCR benchmark, dashboard test or hardware diagnostic was run.

## Exact remaining boundaries

- Mac test URL 127.0.0.1:8001 is Mac-local and cannot be reached by Windows.
  Run the service on the Windows laptop as above, or arrange a reachable private
  tunnel to the Mac test instance. No firewall/public exposure is enabled here.
- Both supplied camera capture URLs timed out from Windows. The owner reports
  Mac cameras unavailable because that Mac is on another network. Uploaded photos
  working on Mac do not satisfy actual-camera acceptance.
- Mac exit OCR changes are uncommitted and unavailable in inspected GitHub main.
- CommitRequest forbids extra fields: there is no read-only exit match endpoint,
  expected_session_id precondition, arrival_id/feedback receipt field, reservation
  cancellation, or passage-finalization endpoint. This minimum bridge enforces
  confirmation-before-exit-commit in its own durable ledger; the server does not
  independently verify passage. Use it as the exclusive client of an isolated test
  instance. Concurrent manual commits/other session writers are outside this
  guarantee; a server-side conditional match/finalize interface is needed for that
  deployment. No imaginary request fields or early exit commits are sent.
- A rejected/uncertain entrance OPEN cannot automatically cancel the teammate
  admission through this API. Retain it for reconciliation; do not edit her DB.
- Existing UNO entrance authorization is 20 seconds. If actual capture/AI/commit
  exceeds that window, no late OPEN is issued; a confirmed reservation stays review.
  The bridge refuses to begin a reservation after 18 seconds. Firmware is unchanged.
