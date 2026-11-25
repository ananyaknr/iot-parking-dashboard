# Phase 1 — Arduino UNO R3 + one HC-SR04

Status: A1 firmware compiled, uploaded to user-confirmed UNO on COM8 and flash-verified. Baseline JSON validation and occupied/vacant snapshot tests passed. Repeatability, controlled hysteresis and no-echo/recovery acceptance remain pending. Phase 2 is blocked until the current one-sensor acceptance tests pass. M1 physical tests are deferred until a second sensor is available.

## Wiring (disconnect USB before changing wires)

| HC-SR04 pin | Installed A1 | Future M1 (not connected today) |
|---|---|---|
| VCC | UNO 5V | UNO 5V |
| GND | UNO GND | UNO GND |
| TRIG | D2 | D4 |
| ECHO | D3 | D5 |

Check the sensor's printed pin labels. Use common ground. Only A1 is installed today. Leave D4/D5 disconnected and reserved. D6 is reserved for future KY-002 vibration sensing; no vibration sensor is installed or sampled. D9 is reserved for a servo, D10/D11 for gateway UART (RX/TX), and A4/A5 for an I2C LCD. No ESP32 is attached in Phase 1.

## Configuration and telemetry

`M1_SENSOR_ENABLED = false` in `firmware/uno_sensor_node/uno_sensor_node.ino` disables M1 pin setup, triggering and sampling. `m1_distance_cm` and `m1_occupied` remain JSON null. Install M1 with USB disconnected, then change only this flag to true and rebuild/upload to enable the retained M1 implementation.

USB serial and SoftwareSerial gateway UART both transmit the same newline-delimited JSON at 9600 baud, approximately once per second. Vibration is always `null`, `vibration_count` is always `null`, and `vibration_status` is always `"not_installed"`.

Example only, not a measurement:
```json
{"node":"uno","a1_distance_cm":10.2,"m1_distance_cm":null,"a1_occupied":true,"m1_occupied":null,"vibration":null,"vibration_count":null,"vibration_status":"not_installed"}
```

A1 uses three samples with at least two valid echoes, a median of three or mean of two, and provisional hysteresis thresholds: <=15 cm occupied, >=18 cm vacant, between these distances retain the previous state. No valid echo gives null distance and null occupancy, never automatic vacancy. Initial readings in the hysteresis band may have null occupancy. Calibrate thresholds to the actual mounting geometry later.

## Compile and upload

Arduino CLI and the `arduino:avr` board package are required. Install missing dependencies only with the user's approval, following the [official Arduino CLI installation instructions](https://docs.arduino.cc/arduino-cli/installation). SoftwareSerial is included in the AVR package; no third-party libraries are needed.

```powershell
$cli = Join-Path $PWD '.tools/arduino-cli/arduino-cli.exe'
$cliConfig = Join-Path $PWD '.tools/arduino-cli.yaml'
& $cli --config-file $cliConfig core update-index
& $cli --config-file $cliConfig core install arduino:avr
& $cli --config-file $cliConfig board list
& $cli --config-file $cliConfig compile --fqbn arduino:avr:uno firmware/uno_sensor_node
# After user confirms wiring and the detected UNO port:
& $cli --config-file $cliConfig upload --fqbn arduino:avr:uno --port COMx --verify firmware/uno_sensor_node
& $cli --config-file $cliConfig monitor --port COMx --config baudrate=9600
```

Replace COMx with the confirmed UNO port, never a Bluetooth serial port. Close all other serial monitors before upload/capture. Opening serial may reset the UNO; discard only an incomplete startup line, and record it. Record build, upload and captured serial evidence in `docs/test-results.md`.

## Current one-sensor physical acceptance

Use a flat target facing the sensor, at least 2 cm away. Keep a flat backing surface 25–50 cm away for a valid empty reading; removing all reflecting surfaces tests unknown, not vacancy. Allow up to three telemetry messages after moving the target to settle.

1. Confirm A1 wiring with USB unplugged, connect UNO by USB, identify its COM port and confirm wiring ready before uploading.
2. Capture 60 seconds at 9600 baud. Require at least 55 complete JSON messages, no malformed complete lines, exact schema and valid types. Require null M1 and vibration fields and `not_installed` status in every message. Record received count, cadence, errors and actual samples.
3. Empty A1: backing surface 25–50 cm away. Require five consecutive valid distances and `a1_occupied: false`.
4. Occupied A1: flat target 5–12 cm away. Require five consecutive valid distances and `a1_occupied: true`.
5. Remove the target back to the backing surface. Require five consecutive vacant readings. Repeat ten occupied/empty cycles and record actual success counts for both transitions.
6. Hysteresis: from occupied, move target to 16–17 cm and check it stays true for five readings; from vacant, move to 16–17 cm and check it stays false for five readings. Measure target distance and record actual sensor readings.
7. Controlled no echo: unplug USB, disconnect A1 ECHO from D3 and connect D3 to GND (never short the sensor's ECHO output to GND), then reconnect USB. Require five consecutive null A1 distances/occupancies while all disabled fields remain correct. Unplug USB, remove the D3-to-GND jumper and restore ECHO to D3; reconnect and confirm recovery with five valid vacant readings. This wiring change requires user action.
8. M1 disabled check: inspect configuration and confirm D4/D5 remain disconnected; verify null M1 fields throughout all tests. No M1 physical occupancy pass is claimed today.

Record only observed results, with logs and user-reported target positions identified separately. Any failed/pending required test keeps Phase 1 incomplete. Do not proceed to Phase 2 without an explicit physical acceptance pass.

## Future two-sensor acceptance (deferred)

After installing M1 and setting the flag true, repeat valid-empty, occupied, release, ten cycles, hysteresis, no-echo and recovery tests for M1. Test empty/empty, A1-only occupied, M1-only occupied and both occupied, expecting false/false, true/false, false/true and true/true. Check both sensors for interference and calibrate each slot separately. M1 tests remain deferred today.

For an automated capture from the confirmed UNO port:
```powershell
powershell -NoProfile -File scripts/capture-telemetry.ps1 -Port COMx -Seconds 60
```
The script saves raw lines, timestamped validation events and a summary under `docs/serial-logs`. It validates the current disabled-M1 schema and A1 value types; it does not establish physical occupancy acceptance. Startup buffer and one boundary line are discarded, with that line recorded in the summary. A trailing partial line is recorded separately. Occupancy threshold checks exclude rounded boundary values (15.0 and 18.0 cm).



