# Gate simulation bench test (servo disabled)

U1 D2/D3, U2 D4/D5, KY-002 D6 and I2C LCD A4/A5 are connected. The 2026-11-26 guided integrated demonstration verified both UART directions, CAR/SUPERCAR display, vibration response and one completed U1/U2 cycle through local/cloud history. GPIO26 → UNO D10, UNO D11 → corrected divider → GPIO25 and common ground remain connected. SG90 remains disconnected. See the timestamped [verification ledger](gate-v2-verification.md) for limits and the earlier failed attempts.

## Upload

After the owner separated sensor power onto two breadboards and corrected the
UART divider (1 kΩ upper / 2 kΩ lower, three 1 kΩ resistors), integrated ESP32
upload on COM10 passed hash verification with both boards and UART connected.
UNO is now COM7. Detect ports each time; do not apply old COM8/COM9 assumptions.
Keep wiring intact and servo disconnected. See [wiring.md](wiring.md).

The following earlier recovery procedure is historical, **not required for the
corrected setup**: close native serial monitors, unplug
UNO USB and disconnect BOTH UART signal paths at ESP32 GPIO25/26. Leave ESP32
USB/sensors connected; upload at 115200. Wait for hash verification before
restoring the two signal paths and UNO USB. Partial isolation was unreliable.
No full erase or toolchain reinstall was necessary. Current acceptance is in
[gate-v2-verification.md](gate-v2-verification.md).

Keep original firmware intact. Use local ignored secrets.h in firmware/esp32_gate_sim/ (never commit). Select the existing ESP32 board and its detected port before uploading firmware/esp32_gate_sim/esp32_gate_sim.ino. Verify the existing UNO firmware before deciding whether it needs an upload. Close serial monitors before uploads. Do not attach servo. Both USB ports power their respective boards. For the current CH9102 ESP32 adapter, open the monitor with `--config baudrate=115200,dtr=off,rts=off`; the default asserted control lines selected download mode in this run. If it prints `waiting for download`, release those lines and briefly press EN with BOOT released.

## Test
USB serial is 115200 on BOTH boards; inter-board UART is 19200; newline. Put a fixed reflector beyond 18 cm (within valid range) at each sensor to establish clear zones. Thresholds 15/18 cm are provisional. Allow boot dwell, approach U1 within 15 cm while U2 remains clear, then hold a target in U2, clear both zones beyond 18 cm, wait for simulated closing. U2 detection alone never closes. No echo is unknown; timeout/missing echo during open holds for review. With both zones clear, send RESET via UNO USB serial to recover HOLD. Counters reset on reboot; random boot-scoped v2 IDs distinguish events across reboots.

Standalone simulation now allows **120 seconds** from arrival for a supervised,
step-by-step bench demonstration. The original 20-second attempt timed out while
the operator positioned U2. The shared core default and integrated authorization
deadline remain 20 seconds; the UNO selects 120 seconds only in standalone mode.
This does not relax missing-echo, obstruction, second-vehicle or clearance checks.
Keep separate reflectors in both beams: a target or hand crossing U2 before U1
causes `unexpected_passage`; removing the only reflector can cause `sensor_unknown`.

On ESP32 USB send LCD|AB1234|car then LCD|XY5678|supercar. Expect LCD_SENT_TEST|id then LCD_ACK|id|ok|test (or duplicate). Confirm the physical LCD separately. Commands retry with the same ID and a bounded timeout; an ACK timeout is a failed test. Display override lasts 15 s. Only synthetic ASCII test plates; no actual recognition integration yet. UNO USB VIB? reports raw/min/max/sampled transitions; tapping is needed to establish polarity and debounce behavior.

Gate simulation publishes parking/test/gate/telemetry. Test MQTT LCD commands use a fresh per-connection random topic announced non-retained at parking/test/gate/lcd/ready; see the v2 contract. Existing gateway environment telemetry stays on its production topic. Start the separate local demo with `.venv\Scripts\python.exe scripts/run-gate-demo.py`; use http://127.0.0.1:5001. Local sensor_test and cloud parking_sensor_test are the only gate destinations. No gate simulation enters production local/cloud storage. The production legacy UNO source becomes stale after migration; old A1/M1 records are preserved. Existing shared MQTT ACL is unchanged. Test commands cannot move a servo; no Servo library or D9 output exists.

Vibration is a Timer2 nominal 1 kHz sampled transition counter with 50 ms filtering, not calibrated event count; short pulses may be missed, including during interrupt masking. Physical polarity is unverified. Both firmware builds and software checks passed; actual upload/UART/cycle evidence is recorded separately in gate-v2-verification.md. SG90 power and teammate contract remain blockers; no physical actuation or camera authorization is claimed.
