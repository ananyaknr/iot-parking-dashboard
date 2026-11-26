# Gate simulation bench test (servo disabled)

User reports successful standalone U1 D2/D3, U2 D4/D5, KY-002 D6 and I2C LCD A4/A5 tests, including mock CAR/SUPERCAR display. GPIO26 → UNO D10 has been connected; existing UNO D11 → divider → GPIO25 and common ground remain. Reverse UART not yet verified. SG90 remains disconnected.

## Upload
Keep original firmware intact. Copy local ignored secrets.h from firmware/esp32_gateway/ into firmware/esp32_gate_sim/ (never commit). Open firmware/esp32_gate_sim/esp32_gate_sim.ino, select existing ESP32 board and verify COM9 before uploading. Then open firmware/uno_gate_sim/uno_gate_sim.ino, verify UNO COM8, compile/upload with the same LiquidCrystal_I2C library as the successful diagnostic. Close serial monitors before uploads. Do not attach servo. Both USB ports power existing boards.

## Test
UNO serial 9600; ESP32 serial 115200; newline. Put a fixed reflector beyond 18 cm (within valid range) at each sensor to establish clear zones. Thresholds 15/18 cm are provisional. Allow boot dwell, approach U1 within 15 cm while U2 remains clear, then hold a target in U2, clear both zones beyond 18 cm, wait for simulated closing. No echo is unknown; timeout/missing echo during open holds for review. With both zones clear, send RESET via UNO USB serial to recover HOLD. Counters reset on reboot; they are not globally unique event IDs.

On ESP32 USB Serial Monitor send LCD|AB1234|car then LCD|XY5678|supercar. Expect UNO LCD and ESP32 ACK|LCD|OK. Because UNO SoftwareSerial transmission can interrupt reception, a missed ACK requires repeating the test, not claiming success. Display override lasts 15 s. Only synthetic ASCII test plates; no actual recognition integration yet.

Gate simulation publishes parking/test/gate/telemetry; test display input parking/test/gate/lcd is display-only (never use retained messages). Existing gateway environment telemetry stays on production topic. No gate simulation enters production local/cloud storage. Existing production dashboard UNO will become stale until separate v2 backend migration. Do not relabel historical A1/M1 records. Existing shared MQTT ACL unchanged. Test topic is not a secure production recognition channel; no commands can move a servo. No Servo library or D9 output in test sketch.

Vibration is a preliminary polled transition counter, not calibrated event count; short pulses may be missed. No physical servo actuation, camera authorization, backend migration or firmware compilation verified in this implementation session. Record actual results separately.
