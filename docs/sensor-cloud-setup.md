# Sensor cloud setup and acceptance

Approved design: InfluxDB Cloud Serverless Free Plan only (zero paid spend), 30-day cloud retention, existing seven-day local storage, no Docker/WSL or firmware changes. No teammate camera/session data is exported. Implementation is optional and local-first.

## 1. Account and bucket setup (user workstation)
Sign in at https://cloud2.influxdata.com/ or follow the official [Free Plan signup](https://docs.influxdata.com/influxdb3/cloud-serverless/sign-up/). Choose the nearest available free region and verify the Billing page still says Free Plan. Do not upgrade or add paid resources. Free accounts allow two buckets (excluding system buckets); if there is an existing bucket, do not delete data to make room. Use an appropriate free organization/account with capacity, or stop and report the blocker.

Create buckets **parking_sensor_data** and **parking_sensor_test**, both with 30-day retention. Use separate bucket-scoped read-only and write-only API tokens for each. For InfluxQL HTTP reads, create a default DBRP mapping for each bucket with database name equal to bucket name (and a default retention policy, e.g. autogen). Follow the official [DBRP guide](https://docs.influxdata.com/influxdb3/cloud-serverless/query-data/execute-queries/v1-http/) and its linked mapping instructions. The HTTP API is not Flux-compatible.

For local resource setup, run `.\.venv\Scripts\python.exe scripts/configure-cloud-resources.py` in an interactive terminal. It accepts an official regional HTTPS URL and a temporary bucket/DBRP management token without echoing or saving the token. It creates only the two approved buckets, sets 30-day retention, creates default DBRP mappings, and reads them back. It refuses insufficient Free Plan capacity or mappings targeting unrelated buckets. It never deletes a bucket or upgrades a plan. A new account's default bucket may occupy one of the two slots: preserve it, resolve capacity/name reuse in the provider UI, and rerun. Revoke the temporary setup token after provisioning. Backend credentials remain separate bucket-scoped read/write tokens entered with the commands below.

Do not paste tokens into chat, commit them, include them in screenshots, or use command-line arguments containing tokens. Run in project PowerShell after the approved native environment is installed:

    .\.venv\Scripts\python.exe scripts/configure-cloud.py --test
    .\.venv\Scripts\python.exe scripts/test-cloud-pipeline.py
    .\.venv\Scripts\python.exe scripts/configure-cloud.py

The first two commands configure and verify ONLY the isolated test bucket. Run the final command only once the test passes. Credential files are in ignored .secrets; the script enforces restricted Windows permissions before writing credentials and requires an interactive terminal. Tokens must never be piped or passed on the command line. The production config is loaded on the next backend restart. Confirm your real free-plan account and bucket retention in the provider UI; the local confirmation flag is not a billing API assertion.

The helper checks that the read token can enumerate exactly its intended bucket, refusing wrong/all-bucket access before saving. Use `--replace-read` or `--replace-write` to replace only one role while preserving the other; include `--test` for isolated credentials. A provider/network failure preserves the existing file. Revoke accidentally broad and temporary setup tokens in the provider UI.

Restart the existing native stack through its stop/start scripts (no flash/wiring changes):

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stop-native.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-native.ps1

For configuration reload with broker/database retained, use `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/restart-native-backend.ps1`. It verifies executable/start identity before stopping the owned backend and starts it through the existing native script.

Open http://127.0.0.1:5000, authenticate with existing local credentials. Cloud panel shows last acknowledged write, durable pending, volatile staging, dropped/error counts. Choose Cloud in history and request 5 minutes; use Refresh for updated archive. There is no periodic cloud query. A write acknowledgement is not proof of query visibility; verify actual cloud history.

## 2. Data and durability
Only accepted hardware UNO and ESP32 records under production local bucket/topic prefix are exported, starting after activation; no implicit backfill. Original backend UTC receive time (not sensor acquisition or upload time), fixed measurement/source tags and field types are retained. Missing numeric and boolean fields are omitted, with explicit validity fields. No camera/plate/photo/session data or redundant status snapshots.

Bounded 1,000-record RAM staging hands off to a separate persistence thread; only committed SQLite rows are durable across restart. SQLite rollback-journal mode and 15 MiB database page cap reserve room for its journal within the approved 32 MiB target. Count cap 50,000; actual capacity may be lower. Drop newest on full; expired records or irrecoverably rejected points are counted. Queue/file failures do not stop local ingestion. Counters reset on process restart. An abrupt kill before SQLite commit can lose RAM staging. Do not claim lossless sync or guaranteed physical disk quota without measuring database/journal and filesystem allocation.

The upload thread sends up to 200 points/100 kB every ten seconds. Retries preserve the same point identity (measurement, tag set, original timestamp), with capped exponential backoff/jitter and Retry-After support. Cloud Serverless partial-write errors may require record isolation; test provider semantics before asserting production idempotency. 401/403/404 back off and preserve the queue. Retention-expired pending rows are removed. Provider quotas are shared at organization level; the Free Plan documented data-in allowance is 5 MB per five minutes. Check the actual plan; no automatic upgrade.

Cloud history uses bounded InfluxQL aggregation (approximately 600 windows, up to 30 days), one concurrent query, no automatic polling. Empty/invalid/low-coverage windows are gaps. Aggregates cannot identify every internal outage; never use archive history for live allocation. Source label distinguishes cloud raw telemetry from local status projections. All network calls use HTTPS certificate verification and server-side credentials.

`/api/latest` includes process-local cloud transfer counters: attempted/acknowledged write bytes, response bytes, write/query request counts. They reset at backend restart and are not the provider's normalized ingestion meter or organization-wide billing usage. Compare a timed measurement against the provider Usage page; account for other clients and query traffic. `scripts/measure-cloud-outbox.py` measures the actual SQLite cap and sampled allocated database/journal bytes using temporary synthetic local-only rows, then removes its own temporary files. It never sends data to cloud or MQTT.

## 3. Required acceptance evidence

- Run the existing Python suite and new cloud unit tests: from backend, ..\.venv\Scripts\python.exe -m unittest discover -s tests -v
- Run node --check dashboard/static/app.js and the existing Chrome dashboard runner. Extend browser verification to cloud selector, on-demand refresh, 30-day query, errors and local recovery.
- Run real-provider test above and verify one synthetic logical point after duplicate writes. No synthetic production writes.
- Connect actual hardware; observe cloud acknowledgements, query actual sensor timestamps/values and display Cloud history on dashboard. Record sanitized results without tokens.
- Disconnect internet without disconnecting local MQTT LAN, observe live local data and durable queue growth, restart backend while offline, confirm retained rows; restore internet, confirm backlog drains and timestamps remain unchanged.
- Verify bad test credentials, 429/5xx/timeouts, queue cap and partial record errors using isolated fixtures. Check local responsiveness and gap semantics throughout.
- Measure .runtime/cloud-outbox.sqlite3 plus journal and total footprint during sustained load; measure cloud bytes/quota usage. Document actual results, not estimates.

Actual execution status is recorded in [sensor-cloud-verification.md](sensor-cloud-verification.md). Passing local regression tests does not establish provider deployment, physical telemetry or internet-outage acceptance. Keep PR #3 draft until the real applicable acceptance tests pass. No paid upgrade, firmware or teammate change is authorized by this workflow.

Use `scripts/verify-cloud-production.py` for read-only exact timestamp/value and history API acceptance, then `node scripts/verify-cloud-dashboard.cjs` for actual Chrome rendering. `scripts/verify-cloud-outage.py` records baseline, offline-before-restart, offline-after-restart and recovered phases. Keep the PC and ESP32 on the original hotspot LAN throughout; switch only its upstream internet. The offline checks require both external HTTPS probes to fail while actual hardware and local history remain fresh. The restart check compares hashes of committed rows. Recovery requires those rows acknowledged and absent from the outbox, checks representative first/last original source timestamps in cloud, and deliberately retries one **existing hardware identity** to verify one logical point. It never invents production telemetry. Receipts and sensor-only evidence stay under ignored `.runtime`; stage failure is not acceptance.

If physical internet isolation cannot preserve the LAN, mark that acceptance blocked. The separate `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-cloud-transport.ps1` uses a temporary closed-loopback HTTPS proxy only in the restarted backend's environment, preserves local HTTP/MQTT, checks committed buffering across another restart and restores normal transport in `finally` before checking recovery. It requires actual fresh hardware and existing private production configuration. It does not change saved credentials, firewall or routes. Its `--controlled-https-failure` receipts explicitly identify fault injection; never label them physical internet-disconnection results.

Run `.\.venv\Scripts\python.exe scripts/measure-cloud-usage.py` to read organization-wide provider metrics with the existing restricted production read token. The endpoint accepts a relative `start=-24h` and returns annotated CSV. The receipt reports successful write-request bytes, query count, response bytes including errors, latest storage gauges and actual period/meter timestamps, excluding organization IDs. Aggregated/late or zero storage readings do not prove zero physical bytes; compare with the Usage UI and a timed backend counter interval. It does not upgrade a plan or grant additional permissions.
