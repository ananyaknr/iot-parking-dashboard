# Autonomous gate software verification — 2026-11-27

Base: main `f92ef31`. Branch: `feature/autonomous-gate`.
All test inputs are synthetic in-memory or temporary SQLite data. No parking
API writes, live MQTT test messages, uploads or physical movements were used.

| Focused check | Actual result |
|---|---|
| Native `gate_automatic_test.cpp` | PASS: correlated authorization/expiry, entrance duplicate/serialization, local exit, 5000 ms minimum, 2000 ms clearance, obstruction, invalid input/recovery, timeout, actuator restart/duplicate transitions, no false passage after CONFIRM, millis wrap |
| Existing native `gate_bench_test.cpp` | PASS: preserved supervised simulation behavior |
| Native `gate_wire3_test.cpp` | PASS: G3 compatibility, A3/P3 mode distinction, reason 16, ASCII/sportcar, deadlines, invalid readings |
| `python -m unittest discover -s backend/tests -p test_parking_v1.py` | PASS: 12 tests, including automatic unconfirmed review, physical-mode rejection, durable command restart/duplicate checks, expiry and feedback receipts |
| Default UNO compile | PASS: flash 22,312 / 32,256 bytes; static SRAM 1,503 / 2,048; 545 bytes remaining |
| A3 automatic simulation compile | PASS: flash 22,314 / 32,256 bytes; static SRAM 1,503 / 2,048; 545 bytes remaining |
| P3 prepared physical compile | PASS: flash 22,568 / 32,256 bytes; static SRAM 1,505 / 2,048; 543 bytes remaining |
| ESP32 forwarding compile | PASS: flash 1,005,205 / 1,310,720 bytes; static RAM 50,976 / 327,680; 276,704 bytes remaining |

UNO: Arduino AVR core 1.8.8, Servo 1.3.0. ESP32 core 4.0.0.
Native checks: MinGW g++, C++11.
The initial new MQTT test fixture wrongly described a detected U1 during closing;
the existing safety validator rejected it. Corrected the fixture to valid clear
input; the final focused suite above passes. The new wire-mode fixture initially
used integer distance strings; corrected to the existing one-decimal wire format.

Timer1/Timer2/Timer0 assignments are separate by source inspection. Interrupt
latency, SoftwareSerial/Servo jitter, stack high-water mark, supply stability,
actual position, obstruction response latency and live recognition are **not
physically verified**. SRAM figures are static allocation, not proof of adequate
worst-case stack. No end-to-end hardware acceptance or joint parking test is
reported as passed. See [the hardware acceptance procedure](../autonomous-gate.md).
