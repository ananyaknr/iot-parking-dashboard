# Physical inferred sender verification — 2026-11-28

Base `2ff87fd`, existing `feature/autonomous-gate` branch. Tests used temporary
local SQLite and synthetic data only. No live MQTT/API writes, firmware uploads,
servo movement or teammate source changes were performed.

`PYTHONPATH=backend;backend/tests`, existing `.venv` Python:
`python -m unittest test_parking_inferred.InferredTests` — **6 tests passed**.

| Required case | Actual result |
|---|---|
| Clean entrance | Inferred completed, simulation false, passage confirmed false, original command correlation |
| Clean exit | Inferred completed, null command ID; no remote OPEN |
| Fault then recovery | Invalid input, HOLD, disconnect and stale-telemetry subcases all retained hold; no passage basis |
| Duplicate/restart | One control dispatch; restarted sender cannot reconstruct eligibility; terminal feedback remains identical through retry/restart and recorded receipts work |
| Mode mismatch | Wrong telemetry/command mode and incompatible ledger rejected; isolated-storage opt-in required; rejection ACK identifies physical mode |
| Supervised simulation | Existing G3 completed/confirmed simulation payload retained, without inferred passage basis |

MinGW C++11 `gate_inferred_test.cpp` — **PASS**: clean entrance/exit,
initial own-lane presence, permanent invalid/obstruction disqualification,
STOP/reset/opposite detection, closing fault, duplicate/restart, policy off.
Existing `gate_bench_test.cpp` — **PASS**: supervised controller behavior.
Python startup modules compiled successfully (`py_compile`).

Arduino CLI compile only, existing AVR 1.8.8 / Servo 1.3.0 / ESP32 4.0.0:

| Build | Flash bytes | Static RAM bytes | Remaining RAM bytes |
|---|---:|---:|---:|
| G3 supervised UNO | 22,614 / 32,256 | 1,507 / 2,048 | 541 |
| A3 automatic simulation UNO | 22,616 / 32,256 | 1,507 / 2,048 | 541 |
| P3 inferred-policy UNO | 22,850 / 32,256 | 1,509 / 2,048 | 539 |
| P3 policy-off UNO | 22,850 / 32,256 | 1,509 / 2,048 | 539 |
| ESP32 forwarder | 1,005,597 / 1,310,720 | 50,976 / 327,680 | 276,704 |

No timer allocation changed: Servo Timer1, vibration Timer2, millis Timer0,
SoftwareSerial pin-change interrupts. Static RAM remaining is not a runtime
stack-margin measurement. UART/servo interrupt jitter, power, sensor geometry,
physical closing position and safety latency require hardware acceptance.
Receiver acceptance of the proposed physical payloads has not been tested here.
See [exact configuration, contract and acceptance](../physical-inferred-contract.md).
