# Gate v2 verification — 2026-11-26

## Completed hardware demonstration, 21:40–22:08 Bangkok

This section supersedes the earlier connectivity blockers below. The owner
manually separated UNO/ESP32 sensor power onto two breadboards, corrected the
UNO D11 → GPIO25 divider to 1 kΩ upper / 2 kΩ lower (three 1 kΩ resistors), and
restored both UART signals. No wiring was changed by the agent. Servo remained
physically disconnected; D9 remains unused and recognition remains disabled.

| Essential check | Actual evidence |
|---|---|
| Port detection | UNO CH340 COM7, VID 1A86/PID 7523; ESP32 CH9102 COM10, VID 1A86/PID 55D4. USB/ROM identification confirmed ESP32-D0WD-V3. Old COM8/COM9 assignments are historical. |
| ESP32 restoration | Existing latest integrated `esp32_gate_sim` image, 996,160 bytes, uploaded at 115200 with **both boards and UART connected**; flash hash verified. No full erase or rewiring. |
| Existing UNO firmware | Integrated G2 startup and I2C address 0x27 observed before changing firmware; existing source/USB behavior confirmed. |
| Guided UNO adjustment | Standalone simulation window extended from 20 to 120 seconds for step-by-step operator guidance. Integrated authorization and core default remain 20 seconds. Missing echo, obstruction and clearance rules remain active. Focused C++ core checks, including the new timeout boundary/unknown/authorization assertions, passed; UNO compile 14,886 bytes flash / 1,386 bytes static RAM, 662 bytes remain. Upload on COM7 exited successfully. |
| Bidirectional UART | ESP32 `LCD_SENT_TEST` → UNO `ACK` → matching ESP32 `LCD_ACK` with `ok|test`: CAR command `d36ca212`; SUPERCAR `939bf3b5`, repeated as `10e6abbd` for visual confirmation. USB 115200, inter-board UART 19200. |
| U1/U2 physical cycle | PASS: the owner moved separate reflectors step by step; actual UNO/ESP32/MQTT state sequence and distances are recorded below. Arrivals 1, completed passages 1. |
| Vibration | Rest diagnostic `VIB_DIAG|1|1|1|0`; after owner tapping `VIB_DIAG|1|0|1|2`. Real sampled transition count rose 0 → 2 and reached local/cloud storage. Response is verified; polarity calibration, per-tap accuracy and missed short pulses remain unaccepted. |
| Physical LCD | Owner visually confirmed `AB1234 / CAR` and, after resend, `XY5678 / SUPERCAR`. I2C device 0x27 and correlated reverse-UART acknowledgements independently observed. |
| ESP32 environment | Fresh DHT22 temperature/humidity and LDR/MQ-2 raw ADC values received. At cloud readback: 23.3 °C, 63.5%, light 1029, gas 553. Gas remains uncalibrated ADC, not ppm. |
| Actual MQTT | Read-only capture 21:48:06–22:08:10 Bangkok contains 1,690 messages, including non-retained actual gate/environment frames and display acknowledgements. No fixture telemetry was published. |
| Local InfluxDB | Isolated `sensor_test` history returned numeric U1/U2, environmental, arrival/completed and vibration values, with completed 1 and vibration 2. Local storage backlog/drops/write failures were zero in the final receipt. |
| Isolated cloud | At 22:07:17 Bangkok, direct readback from `parking_sensor_test` returned the completed hardware cycle under the exact boot ID, `event_seq=8`, `passage_completed`, arrivals/completed 1/1, vibration 2, valid U1/U2 and `servo_enabled=false`. Fresh environmental records also returned. |
| Actual Chrome dashboard | At 22:08:07 Bangkok: fresh UNO gate/ESP32 cards, Closed · simulation, counts 1/1, vibration 2, servo disabled, numeric data in all nine series across six charts from **both local and cloud** storage; no JavaScript errors. Screenshots inspected. |

Completed cycle boot ID: `b3d3741f9f3849a396cd1012ef925eac`.
Passage ID: `v2:b3d3741f9f3849a396cd1012ef925eac:p:1`.
Reviewable artifacts: [sanitized receipt](evidence/gate-demo-20261126/receipt.json),
[local dashboard](evidence/gate-demo-20261126/local-dashboard.png), and
[cloud dashboard](evidence/gate-demo-20261126/cloud-dashboard.png).
These timestamps are actual MQTT receive times in Bangkok:

| Time | Event / state | U1 cm | U2 cm | Arrivals / completed |
|---|---|---:|---:|---:|
| 22:05:34.799 | ready / closed | 37.1 | 35.9 | 0 / 0 |
| 22:05:50.987 | arrival / open_wait | 14.9 | 35.1 | 1 / 0 |
| 22:06:08.623 | passage_detected / passing | 34.6 | 13.1 | 1 / 0 |
| 22:06:15.424 | clearance_confirmed / closing | 34.6 | 32.7 | 1 / 0 |
| 22:06:15.798 | passage_completed / closed | 33.8 | 32.2 | 1 / 1 |

Failures remain evidence: the default Arduino monitor asserted DTR/RTS and
selected download mode on this CH9102 adapter. Reopening with both off and one
owner EN press produced normal boot; Arduino IDE had also reclaimed COM10 and
was closed by the owner. The capture helper now explicitly disables DTR/RTS.
Initial native startup needed a retry after a setup HTTP 503. Initial cloud
HTTPS errors recovered; direct exact-cycle readback and browser history passed
afterward. The final cloud display reported 10 historical retry failures, last
upload acknowledged, 1,863 uploaded records and 4 pending at screenshot time;
this does not certify uninterrupted Internet access or a permanently empty queue.

During target positioning, no echo caused `sensor_unknown` and U2-before-U1
caused `unexpected_passage`; both held for supervised reset. The first arrival
attempt timed out under the original 20-second window before U2 reached the
15 cm detection threshold. It was **not a completed cycle**. The accepted
step-by-step cycle above took about 25 seconds using the explicit 120-second
standalone window. No physical actuation or original-20-second cycle acceptance
is claimed. Two initial capture helpers also exited on local log contention/
command routing; one combined capture then supplied usable matching serial logs.

Raw receipts stay ignored under `.runtime`: `restored-hardware-mqtt.jsonl`,
`restored-hardware-serial.jsonl`, `final-hardware-readback.json`,
`final-hardware-dashboard.json` and `final-hardware-{local,cloud}-dashboard.png`.
No credentials, real license plates or synthetic production data were committed.
The prior 51-test Python, fixture browser, outage and stress suites were not
repeated. Only the changed C++ core, necessary UNO build/upload, actual hardware
readbacks and actual hardware dashboard were checked.

**Remaining limits:** essential servo-disabled hardware demonstration passed.
PR is ready for review and remains unmerged; servo power/actuation and camera/teammate
integration remain deferred. Sensor placement/crosstalk robustness, precise
threshold calibration, vibration semantics and long-duration operation remain
follow-up acceptance work. Lightweight native Windows deployment, production
gate routing off, and isolated gate storage are preserved.

## Hardware recovery update, 18:25 Bangkok

### Follow-up at 18:39 Bangkok

Both COM8 and COM9 were present after the owner's latest reconnect. New real
gate output at 18:35:27 reports U1 6.4 cm and **U2 12.3 cm**, both detected,
boot_wait, counters zero, servo false. U2 is therefore no longer categorically
unreadable; neither zone was clear in this sample. The earlier claim that a
different cable was definitely needed is not established by the available data.

The native ESP32 log records `rst:0x10 (RTCWDT_RTC_RESET)` at 18:35:26 and one
gate frame afterward, followed by no further environmental/gate forwarding.
Backend checks at 18:36 show broker/storage connected but gate/environment stale.
The 16 KiB task stacks **did not establish a fix**; stack exhaustion is still not
proven. Likewise, changing monitor software did not establish a .NET-specific
bug: readers differ in DTR/RTS handling, and opening the UNO monitor produced a
new startup banner even with those lines configured off. Avoid attributing all
corruption to either the cable or the capture library.

Remaining diagnosis: distinguish the ESP32 application stall from electrical
interference/power/reset coupling with the connected UNO. Inspect actual UART
divider, power and ground connections; use bounded stage/reset diagnostics if
the wiring is sound. Do not repeat upload/reconnect cycles without new evidence.
The full gate cycle, vibration and LCD acceptance remain unverified.

This update supersedes the earlier ESP32-upload blocker below.

- ESP32 COM9 upload PASSED at 115200 after disconnecting **UNO USB and both
  UART signals together**, leaving ESP32 sensors connected. Written data passed
  hash verification. Disconnecting only UART while UNO USB remained attached
  did not reliably permit bootloader entry. No full-flash erase or toolchain
  reinstall was performed.
- Actual ESP32 environmental telemetry reached MQTT, backend, local InfluxDB and
  `parking_sensor_test`. Real Chrome cloud-history readback passed at 18:14:47:
  108 numeric points each for temperature, humidity, light and gas; local-history
  recovery passed. No synthetic production writes.
- Actual UNO v2 telemetry also reached the isolated cloud: boot
  `6fbeafadd54c837118a63a095274ee86`, sample at 11:14:30.700355 UTC, U1 26.9 cm,
  U2 null/unknown, state boot_wait, arrival/completed counters zero, servo false.
  This proves receipt of real gate data, not a completed gate cycle or a valid U2.
- The initial .NET SerialPort capture produced unreliable/garbled output. Native
  Arduino monitoring gave usable application output; use
  `powershell -File scripts/capture-gate-hardware.ps1 -Port COM9` (and the actual
  UNO port in another terminal). Commands are newline-delimited; Ctrl+C releases
  a port before upload. Raw logs/receipts remain ignored under `.runtime`.
- Forwarding stopped after two full gate frames in the initial run. A minimal
  task-stack adjustment to 16 KiB for loop/network compiled and uploaded with
  hash verification (996,009 bytes flash, 50,680 bytes static RAM). It is a
  runtime mitigation; the root cause and sustained full-gate behavior remain
  unconfirmed because the UNO USB connection repeatedly disappeared.
- After restoration, ESP32 environmental monitoring remains operational, but
  Windows repeatedly lists COM9 without the UNO CH340/COM8 device. Reseating
  briefly restored COM8 once, then it disappeared again. A different UNO data
  cable/direct USB connection is needed before final physical acceptance.
- U1 arrival/open, U2 passage/clear/close, KY tapping and CAR/SUPERCAR LCD display
  remain **not accepted in this run**. Test LCD input was sent, but no correlated
  acknowledgement was obtained. Servo remains completely disabled; teammate
  recognition delivery remains disabled pending agreement.

No 51-test Python, C++, fixture, outage or stress suite was repeated for this
recovery assignment. Checks were restricted to upload, live serial, actual
cloud readback and the real isolated environmental dashboard.

This is an evidence ledger, not physical acceptance. Historical verification
documents remain intact. U1/U2, KY-002 tapping and LCD diagnostic success were
reported by the owner before this run; they are not independently verified here.

| Check | Actual result |
|---|---|
| UNO final compile, AVR 1.8.8 | PASS: 14,778 / 32,256 flash; 1,382 / 2,048 RAM; 666 bytes remain |
| ESP32 final compile, core 4.0.0 | PASS: 996,005 / 1,310,720 flash; 50,680 / 327,680 RAM |
| Shared C++ firmware core | PASS with g++ -std=c++11 -Wall -Wextra -Werror; safety/state/parser assertions |
| Python regression | PASS: 51 tests, including original regressions and gate/recognition tests |
| Actual Chrome fixture dashboard | PASS: six charts, gaps/timestamps, environment, manual cloud/no polling, failure/local recovery, mobile |
| Actual native dashboards in Chrome | PASS on :5000 and :5001: six charts, authenticated API, broker/database connected, missing sensor data visibly unknown; no physical gate acceptance |
| Real test cloud | PASS at 10:10:23 UTC: parking_sensor_test, synthetic gate fixture; duplicate writes → one logical point; distance/counter history |
| Upload, approved by owner | UNO COM8 PASS after releasing Arduino serial-monitor helper; ESP32 COM9 BLOCKED by repeated 0xF8 bootloader corruption, including manual BOOT and read-only identity check |
| UNO USB diagnostics | PASS: VIB_DIAG raw/min/max = 1/1/1, zero transitions at rest; does not establish polarity |
| UNO I2C startup after reconnect | PASS: I2C_ADDRESS 0x27 and explicit SERVO DISABLED startup banner; LCD text rendering remains visually unverified in this run |
| Real native gate pipeline | PASS: private MQTT/Influx history, servo/schema rejection, legacy separation, environment, retained/restart, original event timestamps, counters, database/broker recovery |
| Actual reverse UART/LCD | BLOCKED pending successful upload and visual check |
| Actual gate cycle/vibration polarity | BLOCKED pending successful upload and grouped physical test |
| Physical servo | BLOCKED: SG90 disconnected, external supply unavailable; no Servo library or D9 output |
| Teammate end-to-end recognition | BLOCKED: shared v2 transport/authorization contract not agreed |
| Production gate transition | NOT APPROVED; gate test data isolated |

Cloud receipt is saved locally in .runtime/gate-cloud-verification.json. This
run sent 1,348 acknowledged bytes over two writes, issued three queries and
received 459 response bytes. These client transfer counters are not provider
billed storage measurements. Free Plan only; no paid services created.

Discovered failures are preserved: initial cloud write HTTP 400 was fixed by
removing a duplicate schema_version field/tag name. Initial native history 503
under compiler memory pressure passed on retry; subsequent gate distance history
exposed integer/float producer inconsistency, corrected by float normalization.
The final native regression passed after also normalizing gate age_seconds to
float: zero age had been encoded as an integer and conflicted with later floats.

Both builds use existing lightweight native toolchains. During compilation free
disk fell below 1 GiB and available RAM was low; compiler concurrency was reduced.
No local production database, old measurement, or owner's diagnostic files were
deleted. Full hardware/cloud/dashboard acceptance is not claimed.

Final disk measurement: 2,440,003,584 bytes free on C:, production local Influx
directory 105,790,593 bytes, isolated gate event ledger 12,288 bytes and isolated
gate cloud outbox 12,288 bytes. These are point-in-time sizes, not 24-hour growth.
Current provider-usage refresh failed. Prior provider receipt (07:30 UTC,
preceding 24 hours) reported 343,752 successful write bytes, 24 queries, 11,981
response bytes and rounded/reported storage zero; it is not a new gate usage meter.

The separate hardware demo starts on loopback :5001 with scoped local sensor_test
credentials. Database and cloud configuration checks passed. The PC initially had
Wi-Fi 10.203.218.185; the owner restored the original 172.20.10.12 hotspot and
the actual broker connection then passed. Both boards were reconnected by USB.
ESP32 upload still failed with the same 0xF8 corruption after cable reconnect;
no ESP32 firmware was written. Reverse UART and fresh gate/environment telemetry
are blocked, not accepted. No network or production credentials were changed.
The production backend was gracefully reloaded using the native process ledger;
broker/database were preserved and production gate routing remains off.
Reproduce the actual native browser check with `node scripts/verify-gate-dashboard.cjs`
while both dashboards are running. This check does not certify fresh sensor or
real cloud chart data. The prior :5000 deployment/history remains available;
fresh telemetry is not available in either dashboard until ESP32 is recovered.
