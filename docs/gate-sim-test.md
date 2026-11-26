# Gate simulation bench test (servo disabled)

User reports successful standalone U1 D2/D3, U2 D4/D5, KY-002 D6 and I2C LCD A4/A5 tests, including mock CAR/SUPERCAR display. GPIO26 → UNO D10 has been connected; existing UNO D11 → divider → GPIO25 and common ground remain. Reverse UART not yet verified. SG90 remains disconnected.

## Upload

Recovery procedure verified on 2026-11-26: close native serial monitors, unplug
UNO USB and disconnect BOTH UART signal paths at ESP32 GPIO25/26. Leave ESP32
USB/sensors connected; upload at 115200. Wait for hash verification before
restoring the two signal paths and UNO USB. Partial isolation was unreliable.
No full erase or toolchain reinstall is necessary. Current acceptance is in
[gate-v2-verification.md](gate-v2-verification.md); UNO USB instability remains
the final-session blocker.

Keep original firmware intact. Copy local ignored secrets.h from firmware/esp32_gateway/ into firmware/esp32_gate_sim/ (never commit). Open firmware/esp32_gate_sim/esp32_gate_sim.ino, select existing ESP32 board and verify COM9 before uploading. Then open firmware/uno_gate_sim/uno_gate_sim.ino, verify UNO COM8, compile/upload with the same LiquidCrystal_I2C library as the successful diagnostic. Close serial monitors before uploads. Do not attach servo. Both USB ports power existing boards.

## Test
USB serial is 115200 on BOTH boards; inter-board UART is 19200; newline. Put a fixed reflector beyond 18 cm (within valid range) at each sensor to establish clear zones. Thresholds 15/18 cm are provisional. Allow boot dwell, approach U1 within 15 cm while U2 remains clear, then hold a target in U2, clear both zones beyond 18 cm, wait for simulated closing. U2 detection alone never closes. No echo is unknown; timeout/missing echo during open holds for review. With both zones clear, send RESET via UNO USB serial to recover HOLD. Counters reset on reboot; random boot-scoped v2 IDs distinguish events across reboots.

On ESP32 USB send LCD|AB1234|car then LCD|XY5678|supercar. Expect LCD_SENT_TEST|id then LCD_ACK|id|ok|test (or duplicate). Confirm the physical LCD separately. Commands retry with the same ID and a bounded timeout; an ACK timeout is a failed test. Display override lasts 15 s. Only synthetic ASCII test plates; no actual recognition integration yet. UNO USB VIB? reports raw/min/max/sampled transitions; tapping is needed to establish polarity and debounce behavior.

Gate simulation publishes parking/test/gate/telemetry. Test MQTT LCD commands use a fresh per-connection random topic announced non-retained at parking/test/gate/lcd/ready; see the v2 contract. Existing gateway environment telemetry stays on its production topic. Start the separate local demo with `.venv\Scripts\python.exe scripts/run-gate-demo.py`; use http://127.0.0.1:5001. Local sensor_test and cloud parking_sensor_test are the only gate destinations. No gate simulation enters production local/cloud storage. The production legacy UNO source becomes stale after migration; old A1/M1 records are preserved. Existing shared MQTT ACL is unchanged. Test commands cannot move a servo; no Servo library or D9 output exists.

Vibration is a Timer2 nominal 1 kHz sampled transition counter with 50 ms filtering, not calibrated event count; short pulses may be missed, including during interrupt masking. Physical polarity is unverified. Both firmware builds and software checks passed; actual upload/UART/cycle evidence is recorded separately in gate-v2-verification.md. SG90 power and teammate contract remain blockers; no physical actuation or camera authorization is claimed.
