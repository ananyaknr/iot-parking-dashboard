# Issue 1 implementation and ownership ledger

Date: 2026-11-26, Asia/Bangkok. Baseline: `4abb83b`.
This is a partial remediation of [issue 1](https://github.com/ananyaknr/iot-parking-dashboard/issues/1), not completion of physical or joint acceptance.

## Boundaries

Our repository owns UNO, ESP32 DevKit, occupancy/environment/vibration sensing, arrival events, servo execution, MQTT, sensor validation/storage and unified dashboard. The teammate owns ESP32-CAM, capture, Gemini, OpenCV/EasyOCR, recognition evaluation, photo/session persistence and entry/exit matching. No teammate files or repository were changed.

Decision orchestration by the teammate is a **proposal awaiting agreement**. This change contains no bay selection, reservation engine, camera/session persistence or gate execution. Proposed shared contracts are in [integration-v1-proposal.md](integration-v1-proposal.md). Coordination was posted on the issue; posting is not agreement. The old camera interface remains compatible pending migration.

## Course traceability

Source: supplied `IoT_Project___Metric_2026_1_07_11_2026-1047532-17943832258827.pdf`, page 1, “Term Project Criteria”, 25 points. These are rubric requirements, separately from engineering tasks in the issue. Historical evidence is [test-results.md](test-results.md); its failures and incomplete tests remain intact. Teammate status is reported by the supplied local README, not independently validated implementation.

| Rubric item | Owner | Implementation/evidence | Status / missing evidence |
| --- | --- | --- | --- |
| 1: at least 5 different sensor types | Ours, camera shared | HC-SR04, DHT22, LDR, MQ-2 in firmware and prior native evidence | Partial: four installed sensor types evidenced here; vibration uninstalled, camera teammate-dependent; do not count temperature/humidity as two types |
| 2: at least 1 I2C | Ours | A4/A5 reserved for LCD, wiring documentation | Hardware-blocked: reservation is not implemented I2C evidence |
| 3: at least 2 sensors from Sensor Node platforms | Ours | A1 HC-SR04; M1/vibration disabled in UNO sketch | Partial / hardware-blocked |
| 4: at least 2 sensors from Gateway platform | Ours | DHT22/LDR/MQ-2; prior ESP32 MQTT results | Implemented, prior runtime evidence; calibration/physical acceptance limits remain |
| 5: at least 1 actuator | Ours | Servo pin reserved only | Hardware-blocked: wiring, safe behavior and user-approved movement required |
| 6: camera capture | Teammate | Supplied README reports ESP32-CAM preview/capture | Pending independent/joint evidence |
| 7.1: image processing / pretrained method | Teammate | README reports OpenCV/EasyOCR | Pending teammate evaluation evidence |
| 7.2: AI service | Teammate | README reports Gemini | Pending teammate evidence |
| 8: image processing affects system behavior | Shared | Gate workflow proposal | Team/hardware-blocked |
| 9.1: quantitative fps and accuracy | Teammate | Evaluation reported as planned | Pending real frame evaluation; sensor tests do not substitute for this |
| 9.2: successful and unsuccessful cases | Teammate | Recognition evaluation | Pending teammate evidence |
| 10: queue, at least 3 topics from different sources, explain purposes | Ours/shared | `parking/node/telemetry`: UNO occupancy; `parking/gateway/telemetry`: environment; legacy `parking/camera/result`: advisory camera | Partial: 3 topics software-tested; only two physical sources evidenced here; third-source contract migration requires teammate |
| 11: on-premise/cloud queue-processing server | Ours | Native Python/Mosquitto, prior runtime evidence | Implemented locally; rubric says on-premise/cloud, not mandatory paid cloud |
| 12: time-series storage and retrieval | Ours | InfluxDB OSS 2.x; history fix and regressions | Implemented locally; new tests are synthetic software evidence |
| 13: real-time and historical UI | Ours | Flask/Chart.js; actual Chromium acceptance | Implemented, with separate physical acceptance limits |
| 14.1: objectives and 2–3 SDGs | Team | No slide artifact inspected | Pending |
| 14.2: architecture explanation/discussion | Team | README plus architecture/proposal docs | Partial; presentation pending |
| 14.3: I/O explanation | Team | Wiring/README/contracts | Partial; presentation pending |
| 14.4: strengths/limitations | Team | Evidence and blocker ledger | Partial; presentation pending |
| 14.5: commercial comparison | Team | No comparison artifact inspected | Pending |
| 15.1/15.2: approximately 5-minute overall video, content and quality | Team | No video artifact inspected | Pending |

The rubric states slides and video are due **December 2, 2026 at 09:00**. It does not specify a timezone in the PDF. No rubric points or overall acceptance are claimed by this ledger.

## Engineering task disposition

| Issue work | Status after this change | Dependency / next action |
| --- | --- | --- |
| History timestamps, axes, alignment, gaps, midnight/multiday/7-day | Implemented; software tests | Numeric UTC epoch positions, local full-date labels/tooltips, independent datasets. A window with any invalid snapshot is a gap; absent windows are filled explicitly. Conservative aggregation can hide valid samples in a mixed window. |
| Broker/database/freshness/ingestion separation | Implemented | API counters and independent UI indicators; storage worker cannot block ingestion. `/health` remains infrastructure readiness, not physical acceptance. |
| Bounded queues and retries | Implemented locally, volatile | 1000 receive messages; 2000 queued write points plus up to 100 in-flight/retry points. Drop newest on full write queue, expose counts. No disk durability on backend exit; counters reset on restart. |
| Delayed/duplicate/out-of-order | Partial | Expired receive queue entries, older local receive times, prior connection generations and MQTT DUP discarded. No producer clock/sequence: upstream replay or fresh-published duplicates cannot be recognized. Identical legitimate sensor readings are allowed. Versioned firmware contract needed before strengthening. |
| Fail-closed occupancy consistency | Implemented | Reject vacancy below 14.95 cm or occupied above 18.05 cm; middle band permits either state. Mirrors 15/18 cm firmware thresholds with half a 0.1 cm display unit allowance. Threshold changes require synchronized backend changes. |
| Least-privilege MQTT | Candidate ACL and isolated tests only | `acl.proposed` is not activated. Deployed `acl` and all credentials preserved. Migration requires approved identity/password rollout to gateway/backend/teammate/test clients together. |
| Seven A1 cycles, vacant-side hysteresis, no-echo/recovery, distance error and latency | Hardware-blocked | Requires user-controlled measured target and connected hardware. Three prior cycles remain passed; seven skipped remain incomplete. Preserve failed ranging trials. |
| M1, vibration, I2C and servo | Hardware-blocked | Hardware availability, wiring and explicit upload/movement approval required. M1 remains uninstalled/ineligible. |
| Arrival, bidirectional UART, gate IDs/acks, availability consumption | Team/hardware-blocked | Agree contracts and safe behavior first. Existing read-only `/api/latest` exposes freshness/eligibility; it is not a reservation API or gate authorization. |
| Camera/session dashboard and legacy contract migration | Team-blocked | Agree session projection and private photo access; no second persistence/decision system. No original review per-slot refactor. |
| Cloud sync/retrieval/visualization | Real deployment, controlled HTTPS-failure recovery and quota measurement passed; physical internet outage blocked | Both 30-day buckets/default DBRP and scoped reads verified. Actual UNO/ESP32 timestamp/values matched cloud; real Chrome passed again after recovery with both sources Receiving. Controlled process-only HTTPS failure: 31 committed rows survived restart and recovered automatically; original timestamps/identical hardware retry count 1, zero drops, local operation continued. Actual outbox 225,280 bytes; 337.327-second interval acknowledged 109,206 bytes/428 rows. Provider 24h aggregates: 343,752 successful write bytes, 24 queries, 11,981 response bytes; storage gauge reports 0 with delayed granularity. User phone cannot retain LAN without internet; physical WAN-only test remains blocked, and proxy fault injection does not substitute. PR #3 stays draft. See [cloud verification](sensor-cloud-verification.md). |
| Joint entry/exit/full bay/unreadable plate/duplicate command/gate timeout/cloud outage | Team/hardware-blocked | Proposed acceptance table in integration document; isolated sensor mocks do not establish joint acceptance. |
| 24-hour growth/resource measurement | Pending elapsed measurement | Use existing footprint script at start/end of an actual 24-hour run; no fabricated extrapolation. Keep 1-second status persistence until gap semantics are preserved by a tested replacement. |
| Clean-machine setup | Partial / pending | Existing native deployment retained; test tooling commands documented in evidence. No clean-machine validation performed. Legacy Compose/Grafana untouched and inactive. |

## Runtime and deployment notes

Storage writes use a separate bounded worker. Original point timestamps survive retries, so Influx retries address the same measurement/tag/timestamp. Queue overflow and process termination can still lose data. Receive queue overflow invalidates that source immediately and prevents older queued entries from reviving it. Successful status writes do not imply fresh sensors. MQTT disconnect invalidates source payloads immediately; a new valid message is required after reconnect. Cached timestamps identify the last accepted message even while payload validity is false. Shutdown waits for the current bounded-time write and abandons remaining volatile backlog.

The local dashboard remains loopback-only with existing Basic authentication. Production MQTT remains authenticated plaintext on a trusted LAN: credentials and payloads are visible to on-path observers, ACLs do not provide encryption, and this port must not be exposed publicly. TLS/remote access needs a separate deployment plan.

Apply this branch by normal review/merge and restart the backend/dashboard through the existing native scripts. No firmware upload, wiring, credentials, broker configuration or cloud provisioning is part of this change. Review [issue-1-verification.md](issue-1-verification.md) for exact commands and limitations.
