# Sensor cloud verification ledger

Date: 2026-11-26, Asia/Bangkok. Branch: `feature/sensor-cloud-storage`, PR #3.
**Real cloud deployment is not yet accepted. PR #3 remains draft.** No paid resources or upgrades have been requested. Existing sensor-only implementation was reviewed and patched; it was not replaced.

## Executed software checks

| Check | Actual result |
| --- | --- |
| Original Python suite on feature branch | PASS: 24 tests, 0.542 s |
| Expanded Python suite | PASS: 39 tests, 2.310 s at 07:27 UTC, including single-role token replacement preserving the other credential, rejection of wrong/all-bucket read scope, HTTP 200 authorization-denial handling, approved empty-bucket rename, cloud API isolation, disk errors and authentication/server/network retry retention. Provider usage parser checks added afterward; final result below |
| Final complete Python suite | PASS: **41 tests, 2.172 s at 07:32 UTC**, including provider CSV header changes, write-vs-query/error byte separation, latest storage gauge semantics and rejection of invalid/nonfinite usage |
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

Provider quota consumption was initially unavailable; the later actual measurement is recorded below. Local `attempted_write_bytes` and `acknowledged_write_bytes` are process-local transport counters, not normalized cloud ingestion or organization-wide usage. Do not report zero organization usage from an unconfigured backend or rounded display.

At **07:06:52 UTC**, the actual production outbox measured **225,280 logical and allocated bytes**, with no journal/WAL/SHM file present at that instant. Retained production local Influx files measured 73,841,451 logical bytes; drive free space was 9,058,607,104 bytes. Sanitized receipt: `.runtime/cloud-production-disk.json`. No database was deleted or compacted; free-space change includes unrelated workstation activity and is not attributed to cloud storage.

## Real deployment / hardware status

| Acceptance item | Current evidence/status |
| --- | --- |
| Free Plan account | User reports being at a Cloud Serverless Free Plan organization dashboard; account UI not independently inspected |
| Two buckets, 30-day retention and default DBRP mappings | PASS: local resource helper API readback at 2026-11-26 06:32:43 UTC confirmed `parking_sensor_data` and `parking_sensor_test`, both 30-day retention and default DBRP mappings. Sanitized receipt: `.runtime/cloud-resources.json`. User-approved empty `iot_parking` reuse; no bucket deletion |
| Bucket-scoped runtime credentials | Corrected read tokens API-verified: production can enumerate only `parking_sensor_data`, test only `parking_sensor_test`. Test read/write roles separately verified; production write acknowledgement confirmed. Values remain private |
| Real isolated cloud write/read/duplicate and token-role verification | PASS again at 2026-11-26 06:58:31 UTC after narrowing read scope: exact synthetic timestamp read back as one logical point with value 27.5; read token denied write, write token denied query |
| Production cloud writes from actual UNO/ESP32 | PASS at 06:58:54 UTC: exact original hardware receive timestamps, source/origin, validity flags and numeric values matched in production. 48 actual rows acknowledged by this backend process, zero drops, no current error |
| Existing dashboard displays actual cloud history | PASS: production history API at 06:58:54 UTC and actual Chrome rendering at 07:06:35 UTC. All four charts contain actual cloud readings; local history recovery passed, zero JS errors. Hardware cards correctly showed stale feeds during the browser run; fresh local operation during WAN outage remains unverified |
| Physical internet disconnection while hardware LAN remains up | BLOCKED: user reports the phone cannot keep its hotspot LAN active without internet; process lacks Windows administrator rights for firewall isolation. No physical outage PASS claimed |
| Controlled HTTPS failure, durable buffering, backend restart, recovery/duplicate handling and local operation | PASS with actual hardware: 31 committed rows survived restart, were acknowledged automatically after transport restoration, and representative original timestamps plus a deliberate identical hardware retry each queried as one logical point. This is process-scoped proxy fault injection, not physical WAN loss |
| Actual cloud quota and disk measurement | PASS with limits: provider usage API and user UI reading, timed 337.327-second backend interval, actual production outbox allocation and isolated SQLite cap test. Provider metrics are organization-wide and delayed; storage zero is not physical-byte evidence |

Native start was attempted. Existing local InfluxDB became healthy; the authenticated dashboard API responded with `storage_connected=true`, `mqtt_connected=false`, and both UNO/ESP32 stale with no receive timestamp. Cloud was disabled. Start readiness correctly failed. Broker configuration uses `172.20.10.12`, but current PC Wi-Fi was observed as `10.203.218.185`. User was asked to reconnect PC and ESP32 to the original demo hotspot to preserve compiled firmware configuration. No firmware, wiring, firewall or network changes were made by this work. No synthetic data was published to production topics or cloud buckets.

Update at **2026-11-26 06:22:57 UTC (13:22 Bangkok)**: user reconnected the original hotspot; the PC again reported `172.20.10.12`. Native start succeeded. Authenticated API reported `mqtt_connected=true`, `storage_connected=true`, and both UNO/ESP32 `fresh=true`, `payload_valid=true`, with actual receive timestamps 06:22:57 UTC and 06:22:55 UTC respectively. This resolves the local network/hardware ingestion blocker. It does not establish any cloud writes or cloud acceptance; credentials remain pending.

User subsequently supplied the US East regional URL, identified `iot_parking`, confirmed it is empty and approved its rename to `parking_sensor_data`. The first local setup attempt returned HTTP 400; its exact request was not captured, so no rename/resource success is inferred. Review found missing organization IDs in create/DBRP requests. Setup now derives the organization from bucket metadata (or an unambiguous organization lookup), includes it explicitly, and reports/saves only the failing method, endpoint and HTTP status without tokens or response bodies. All 35 Python tests passed after this correction (0.787 s), including the approved rename preserving the bucket ID and organization-scoped create payloads. A corrected local prompt was opened for retry; real provider readback is still required.

The corrected retry **succeeded at 06:32:43 UTC (13:32 Bangkok)**. Its sanitized resource receipt confirms both required buckets, 30-day retention and default DBRP mappings. No setup token was saved. Test-bucket read/write token entry was opened next with the verified regional URL prefilled; production remains disabled pending isolated cloud acceptance. User was instructed to revoke the temporary management token after setup.

After private test-token entry, the first real verifier run incorrectly reported that the write token could query. Inspection of classification flags only (no token/response body output) showed that InfluxQL returned an authorization error in an HTTP 200 JSON response. The verifier was corrected to recognize explicit authorization denials without treating syntax errors or any data-bearing response as a denial. The corrected real test passed at **06:39:27 UTC (13:39 Bangkok)**. Two writes of the same synthetic timestamp yielded one point, value 27.5, in `parking_sensor_test`; permission probes confirmed read-only/write-only roles. The run measured 3 attempted write requests (390 bytes), 260 acknowledged write bytes, 2 query requests and 255 response bytes. One attempted write was an expected read-token denial; these counters are not the provider's normalized quota meter. No production writes were involved. Sanitized receipt: `.runtime/cloud-test-verification.json`. Production token entry was opened after this PASS.

After private production-token entry, only the verified backend process was restarted; broker/local InfluxDB were retained. Cloud became enabled, but its initial write was rejected HTTP 403. A sanitized diagnostic retried one existing buffered **actual hardware** point at its original timestamp and classified the reason as permission-related, not quota/retention/expired-token text; no raw response or token was printed. At that observation local MQTT/storage and both source freshness flags were true; cloud had 54 durable pending rows, zero drops and zero acknowledged writes. Production readback therefore did not pass. A private write-token replacement prompt was opened, preserving the read token, with a regression checking atomic preservation on invalid replacement. The read-only `scripts/verify-cloud-production.py` now waits for an upload acknowledgement before checking exact real sensor timestamps/values and dashboard history. Actual internet-disconnection and production recovery acceptance remain pending; the credential failure is not a substitute for those tests.

The replacement production write token restored uploads: at **06:48:12 UTC**, 375 actual hardware records had been acknowledged, 100,934 write bytes, pending 8, staging 0, dropped 0, error null. Buffered records drained across backend restart. Readback then exposed a separate configuration mistake: the production read token could read the test bucket, while the test read token could read both buckets. Both were replaced privately. API metadata readback subsequently returned **exactly the intended single bucket for each read token**; the configuration helper now refuses wrong/all-bucket read scope before replacing the saved file. The isolated real cloud test passed again at **06:58:31 UTC**, with the same 390 attempted/260 acknowledged byte totals and one logical synthetic point. No synthetic production record was introduced.

At **06:58:54 UTC**, `scripts/verify-cloud-production.py` passed read-only acceptance: UNO receive timestamp `2026-11-26T06:58:37.349356+00:00` and ESP32 `2026-11-26T06:58:35.654095+00:00` matched original production cloud identities, all checked validity flags and available numeric values. Both had valid numeric measurements during this run. The existing cloud history API returned actual non-null readings. Backend had 48 acknowledged rows, 12,475 acknowledged bytes, pending 11, dropped 0, error null. The verifier performed zero writes, four read requests and received 676 response bytes. Sanitized receipt: `.runtime/cloud-production-verification.json`. This establishes archival transport/value identity, not physical distance accuracy or calibration.

The following real Chrome run did **not** pass acceptance. The hardware feeds stopped around 06:59:27/06:59:21 UTC; PC address subsequently read `10.203.218.185`, rather than required hotspot address `172.20.10.12`. Actual cloud history APIs still returned non-null stored readings (55 UNO and 94 light windows in five minutes), but fresh hardware cards could not be accepted. User was asked to restore the original LAN. This was not a controlled internet-only outage and is not recorded as outage acceptance. Chrome fixture regressions passed again after this failure. `scripts/verify-cloud-dashboard.cjs` and staged `scripts/verify-cloud-outage.py` provide reproducible actual acceptance, with no success claimed until executed stages pass.

The browser acceptance was then separated from the outage test's fresh-hardware requirement: archived history must render even while current sources are stale, and cards must state that accurately. At **07:06:35 UTC**, actual installed Chrome passed the 30-minute production cloud view: distance 56 numeric windows, temperature/humidity 355 each, light 355, gas 355; all four charts rendered, no JavaScript errors, local-history recovery passed. UNO/ESP32 cards displayed `Stale / Unknown`; storage remained connected. Screenshot `.runtime/cloud-dashboard-chrome.png` was visually inspected and contains only the sensor dashboard, with no tokens/plates/photos. Sanitized receipt: `.runtime/cloud-dashboard-verification.json`. This accepts actual archived cloud visualization, **not** fresh hardware operation during an internet outage. The latter remains blocked pending restoration of the original hotspot LAN and controlled upstream-only disconnection. Provider Usage/Billing figures were requested from the user; none have been supplied yet.

User reported restoring the hotspot, but the PC was still on the campus WLAN. Reconnecting its saved original hotspot profile restored actual feeds without firmware changes. The **online outage baseline passed at 07:15:37 UTC**: both external HTTPS endpoints reachable, MQTT/local storage healthy, both hardware sources fresh with valid payloads, local light history non-null, cloud uploaded 543 rows in this process, pending 18, dropped 0, error null, outbox 225,280 bytes. UNO distance was currently invalid/unknown; no numeric value was invented. Receipt: `.runtime/cloud-outage-baseline.json`. Initial baseline attempts exposed two verifier issues: a Microsoft endpoint was inaccessible (another endpoint had TLS verification failure), and the PowerShell process ledger includes a UTF-8 BOM. The verifier now uses independently confirmed reachable GitHub HTTPS, treats HTTP error responses as connectivity, refuses to classify TLS validation failure as internet loss, and reads the ledger with `utf-8-sig`. A later offline-stage attempt correctly refused acceptance because both external endpoints remained reachable. Upstream-only disconnection is requested; offline restart/recovery has not run.

The user supplied **limits**, not usage: reads 300 MB/5 min, writes 5 MB/5 min, two buckets and 30-day retention (plus dashboard/task/check/notification limits). These do not establish actual quota consumption or independently confirm the billing label. A read-only attempt of the [documented usage API](https://docs.influxdata.com/influxdb3/cloud-serverless/api/usage/) with the restricted production read token returned HTTP 400; no response body or token was printed and no usage PASS is inferred. Actual figures remain pending from organization dropdown → Usage, with its selected time range, as described in the [provider guide](https://docs.influxdata.com/influxdb3/cloud-serverless/admin/billing/data-usage/).

## Controlled real-hardware transport failure and recovery

The user subsequently reported that the phone **cannot retain the hotspot LAN without internet**. Physical upstream-disconnection acceptance is therefore **blocked**, rather than silently replaced by a different test. The current Windows process is not an administrator, so firewall-based isolation was unavailable. No firewall, route, firmware or wiring changes were made.

An explicitly separate actual-hardware test used a temporary **process-only `HTTPS_PROXY=http://127.0.0.1:9`**, after checking that local port is closed. Local HTTP InfluxDB/dashboard and MQTT remained accessible. Normal proxy environment was restored in a PowerShell `finally` block and the verified native backend alone was restarted; the broker and existing database were retained. `--controlled-https-failure` writes distinct `cloud-transport-*` receipts, never the physical-outage receipts.

| Stage | Actual evidence |
| --- | --- |
| Online baseline, 07:21:14 UTC | Both actual sources fresh, local history non-null, external HTTPS reachable, 971 acknowledged rows in the existing process, no current cloud error |
| HTTPS unavailable, 07:22:19 UTC | Uploader `network_error`, zero acknowledged uploads in that process, **31 committed pending rows**, staging 0 and drops 0. Both sources fresh and local history PASS |
| Restart under same failure, 07:22:46 UTC | Backend start identity changed. **All 31 captured committed row hashes survived**; total pending 39, staging 0, drops 0, uploader still `network_error`, local MQTT/storage/history and source freshness passed |
| Normal transport restored, recovery 07:23:22 UTC | Captured hashes absent from pending queue, uploader acknowledged 39 rows/9,981 bytes, error null, drops 0. Pending 9 newer ongoing records is not undrained captured backlog. Both actual sources fresh; local history PASS |
| Original identity and retry | First/last captured UNO and ESP32 timestamps queried as **one logical point each**. Retried one existing actual UNO hardware line at its original timestamp, then still count 1. Verifier: one 240-byte acknowledged retry and four queries/534 response bytes; no synthetic production data |
| Actual Chrome after recovery, 07:25:32 UTC | Both hardware cards Receiving, all four cloud charts rendered (distance 20 numeric windows, temperature/humidity 354 each, light 357, gas 356), zero JavaScript errors, return to local history PASS |

Freshness was temporarily unavailable immediately after restart; verifier retries refused acceptance until new hardware messages arrived. Initial failed stages remain failures, not successes inferred from the final run. Current normal HTTPS is restored and acknowledged writes resumed. Original source timestamps checked: UNO `1795677708396537000` / `1795677739387355000` ns; ESP32 `1795677710630699000` / `1795677738147217000` ns.

Receipts: `.runtime/cloud-transport-baseline.json`, `cloud-transport-offline-before-restart.json`, `cloud-transport-offline-after-restart.json`, `cloud-transport-recovered.json`. The exercised local launcher is represented by `scripts/test-cloud-transport.ps1` and safe identity-checked `scripts/restart-native-backend.ps1`; the committed portable wrappers were PowerShell syntax-checked. The transport test establishes actual hardware buffering/restart/recovery during HTTPS failure; it does **not** establish physical hotspot internet-disconnection acceptance. PR remains draft.

## Actual transport interval and provider usage

Two snapshots of the **same backend process** at `07:15:37.065803` and `07:21:14.392879` UTC give **337.327076 seconds**, **428 acknowledged hardware rows**, **109,206 attempted and acknowledged write bytes**, **28 write requests**, zero extra cloud failures and zero backend query/response bytes in that interval. Receipt: `.runtime/cloud-transport-interval.json`. This is an actual interval measurement, not extrapolation to five minutes or 24 hours; it excludes other clients and provider normalization.

The user then found Usage and reported **0.34 MB Data In, 24 queries, displayed 0 GB Storage and Data Out**. Past 24h had been requested, but the user's reply did not explicitly restate its selector. These are user-reported UI values; rounded GB values are not exact zero bytes.

Independent API readback subsequently succeeded with `start=-24h`, `raw=false`, existing bucket-scoped read token and annotated CSV parsing. The documented integer start format had returned HTTP 400 (invalid start timestamp/duration classification); Bearer syntax returned 401, while the existing `Token` authorization and relative duration succeeded. No permissions were broadened and no token or raw response body was logged. `scripts/measure-cloud-usage.py` saves a sanitized receipt and excludes organization/bucket IDs. Returned period:

```text
2026-11-25T07:30:28.809113503Z to 2026-11-26T07:30:28.809113503Z
successful /api/v2/write request bytes (2xx): 343752
query_count: 24
HTTP response bytes including errors: 11981
latest reported storage gauge bytes, summed across bucket series: 0
meter timestamps: 2026-11-26T06:00:00Z, 2026-11-26T07:00:00Z
```

Receipt: `.runtime/cloud-provider-usage-verification.json`. These are **organization-wide aggregated/possibly delayed provider values**, not the current uploader's counters or an exact rolling five-minute saturation test. The response total includes failed-request traffic; an earlier detailed read separated 11,646 successful query-response bytes and 335 failed-write response bytes. Storage reporting zero despite verified stored telemetry cannot establish physical zero usage. The readback is consistent with the user's rounded 0.34 MB/24-query UI report. No rate-limit saturation, paid upgrade or expenditure was attempted. Free Plan status remains user-confirmed, not independently inspected Billing UI.

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
.\.venv\Scripts\python.exe scripts/verify-cloud-production.py
node scripts/verify-cloud-dashboard.cjs
# Keep hotspot LAN connected; user toggles only internet between stages:
.\.venv\Scripts\python.exe scripts/verify-cloud-outage.py baseline
.\.venv\Scripts\python.exe scripts/verify-cloud-outage.py offline-before-restart
# Restart backend while still offline, preserving broker/local database.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/restart-native-backend.ps1
.\.venv\Scripts\python.exe scripts/verify-cloud-outage.py offline-after-restart
# Restore internet; wait for automatic backlog recovery.
.\.venv\Scripts\python.exe scripts/verify-cloud-outage.py recovered
# Separate fault injection when physical WAN isolation is blocked (not equivalent acceptance):
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-cloud-transport.ps1
.\.venv\Scripts\python.exe scripts/measure-cloud-usage.py
```

The resource helper saves only a sanitized receipt at `.runtime/cloud-resources.json`. The real test script saves a sanitized result at `.runtime/cloud-test-verification.json`, including logical point count, synthetic timestamp and byte counters. Runtime credentials remain ignored and server-side. Browser/Computer Use tools failed initialization with `failed to write kernel assets: The system cannot find the path specified`; account sign-in, token creation and local entry are therefore guided user actions. No screenshot or public evidence may contain tokens, plates or photos.
# Gate schema v2 addendum — 2026-11-26

The accepted PR #3 deployment below remains historical production evidence.
Separate gate-v2 synthetic verification passed against `parking_sensor_test`
at 10:10:23 UTC: duplicate identical writes count once; distance and cumulative
counter history are readable. Transfer: 1,348 acknowledged write bytes across
two requests, three queries, 459 response bytes. No synthetic production writes.
The cloud encoder now avoids a duplicate schema_version field/tag name; numeric
counters use last value rather than mean. Physical gate cloud data remains
pending successful ESP32 upload and real telemetry verification. See
[gate evidence](gate-v2-verification.md). No paid resources were created.
