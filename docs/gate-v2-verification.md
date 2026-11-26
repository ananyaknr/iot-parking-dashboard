# Gate v2 verification — 2026-11-26

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
| Real test cloud | PASS at 10:10:23 UTC: parking_sensor_test, synthetic gate fixture; duplicate writes → one logical point; distance/counter history |
| Upload, approved by owner | UNO COM8 PASS after releasing Arduino serial-monitor helper; ESP32 COM9 BLOCKED by repeated 0xF8 bootloader corruption, including manual BOOT and read-only identity check |
| UNO USB diagnostics | PASS: VIB_DIAG raw/min/max = 1/1/1, zero transitions at rest; does not establish polarity |
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
credentials. Database connection passed; broker connection is blocked because
the PC currently has Wi-Fi 10.203.218.185 while configured demo LAN is
172.20.10.12. No network or production credentials were changed. ESP32 USB
reconnection and original hotspot restoration were requested from the owner.
