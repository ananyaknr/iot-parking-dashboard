# Issue 1 verification evidence

Executed 2026-11-26, Asia/Bangkok, on the existing Windows workstation. All new fixtures are **synthetic software tests**. No physical sensor, servo, camera recognition, paid cloud or joint-team acceptance is claimed. Prior physical evidence, including failures, remains unchanged in [test-results.md](test-results.md).

## Results

| Check | Actual result |
| --- | --- |
| Python unit suite | PASS: 16 tests, including all 7 original model regressions; final run 16 tests in 0.102 s |
| Real Chromium + actual bundled Chart.js | PASS: midnight/multiday/7-day numeric axes, independently timed series, null gaps, independent health display, history/live HTTP failure and recovery, reload, 390 px layout, no page JavaScript errors |
| Isolated native candidate ACL | PASS: gateway/teammate/test publisher allowed writes; unauthorized camera/node/test-backend writes denied. Backend/test-backend reads allowed; gateway reads and test-backend access to non-test telemetry denied |
| Real InfluxDB OSS Flux history | PASS: 5-minute, 24-hour, 7-day queries return seeded valid values and explicit empty gaps, at most 601 windows; internal gaps over 10 seconds invalidate a coarse window |
| Actual test backend restart | PASS: retained telemetry delivered on subscription rejected; inconsistent occupancy rejected; valid recovery and 10-second staleness observed |
| Real database outage/restart | PASS: local live ingestion continued, write failure/backlog visible, backlog drained after database restart |
| Real broker outage/reconnect | PASS: allocation eligibility invalidated on disconnect, remained false after reconnect until new non-retained valid telemetry |
| Slow database/bounded retries | PASS unit tests: blocked write does not hold ingestion or queue submission; queue overflow counted, identical batch reused after failed write |

Native runner stdout from the final successful execution (exit 0):

```text
PASS isolated candidate ACL publish allow/deny matrix
PASS isolated candidate ACL read allow/deny matrix
PASS real Influx Flux history: 5m/24h/7d, values and empty gaps
PASS inconsistent telemetry, retained on restart, recovery and 10s freshness
PASS real database outage/restart: ingestion remains live, backlog drains
PASS real broker outage/reconnect: fail closed until new telemetry
```

Browser runner stdout (exit 0):

```text
PASS real Chromium: midnight/multiday/7-day axes, independent series, null gaps, health, HTTP failures, recovery, refresh, mobile width
```

## Reproduce

Use the existing native Mosquitto and InfluxDB binaries at `.tools/native`, Python 3.12 and locked backend dependencies. No Docker/WSL or global service setup. This machine's restricted execution context could not resolve the virtual environment's base Python; tests ran with execution permission outside that context. This does not establish clean-machine install reproducibility.

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
Pop-Location
.\.venv\Scripts\python.exe scripts/test-isolated-native.py

# Optional development-only dependency, not required to run the dashboard:
npm install --prefix .tools/browser-check --no-audit --no-fund playwright@1.65.1
node scripts/test-dashboard.cjs
node --check dashboard/static/app.js
git diff --check
```

The browser runner uses installed Google Chrome (`channel: chrome`) in headless mode and a temporary loopback HTTP fixture server. It loads the real dashboard HTML, CSS, app JS and bundled Chart.js, while intercepting nothing in the production browser. It checks actual chart instances/render sizes and JavaScript failures, rather than only HTTP asset availability. Its synthetic screenshot is written under ignored `.tools/browser-check/dashboard.png` for inspection.

The native runner refuses occupied ports 18884/18086/15001, starts only its own processes with hidden windows, and terminates only those processes. It never reads `.env`. It uses a fresh ignored `.runtime/issue1-*` folder, a new `sensor_test` bucket, test-only credentials and **only `issue1/parking/*` topics**. The candidate ACL is copied with that namespace prefix, so allowed/denied production-shaped routes are tested without publishing to production MQTT topics. It seeds synthetic history snapshots one hour and three days earlier directly into the isolated test database. Those are fixtures, not measurements. No production broker, database, credentials, firmware or firewall rule is changed. Test logs/data remain in ignored folders; sanitized results above are reviewable in Git.

## Failures encountered and resolved

- First history regression exposed a duplicate endpoint when the requested stop was exactly on a window boundary. The endpoint calculation was corrected and the regression passed.
- First browser health test exposed a missed JS replacement; the health display was corrected. The mobile test then exposed a canvas min-content overflow; chart cards now permit shrinking, with canvas width bounded. Browser recovery/reload checks passed afterward.
- Windows `mosquitto_passwd` generated files with an unusable domain-only ACL; the isolated runner now restores inheritance only on its freshly generated synthetic credential files. It does not reset deployed credential ACLs.
- MQTT v5 authorization denial can appear in stderr with a zero CLI exit status, and a denied subscription can wait past the requested timeout. The runner checks denial reason text and bounds denied subscriptions itself.
- The first long-range native history assertion expected a valid point in a startup window that also contained an invalid snapshot. Under the intentional conservative gap policy that window is null. The test now seeds independent historical valid windows; both valid data and gaps are checked against the real database.

## Limits and outstanding acceptance

Cloud export/retrieval, physical A1 completion, M1/vibration, I2C/servo, arrival/gate commands, shared decision/session contracts and joint acceptance remain blocked/pending as detailed in [issue-1-status.md](issue-1-status.md). Candidate ACL rollout is not deployed or approved. The full identity/topic wildcard matrix, concurrent MQTT publisher stress, sustained overload, abrupt process-kill durability and a measured 24-hour disk/resource run are still pending. Existing schema lacks producer sequence/time, so local ordering tests do not prove detection of upstream replays. Write buffering is bounded RAM, not durable cloud sync. Coarse history windows containing any invalid status or an internal sampling gap over 10 seconds are intentionally all gaps. Outages shorter than a window at its edges, or shorter than the freshness timeout, may not be represented; an isolated stored snapshot does not establish continuous acquisition throughout that window. A prior deployment's invalid status cannot be retroactively recovered if it never wrote it.
