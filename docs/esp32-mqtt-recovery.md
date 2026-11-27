# ESP32 MQTT consistency repair

2026-11-27, Bangkok. This addresses the observed simultaneous loss of G3 UNO
and ESP32 environmental telemetry; it does not relax ultrasonic validity rules.

## Actual diagnosis

- Backend MQTT remained connected, but both device feeds stopped. Fifteen
  consecutive API samples showed stale G3. Environmental telemetry had also
  stopped for several minutes.
- ESP32 diagnostics reported repeated `[MQTT] connect failed, state=-2` while
  Wi-Fi reported connected. `UART_DIAG` still counted incoming UNO G3 frames.
  This locates that dropout after UART, on the gateway-to-broker TCP/MQTT path.
- Laptop broker address, listener and scoped firewall rule matched. The gateway
  responded to ping. The underlying hotspot/TCP interruption was not established.
- The owner confirmed USB unplug/replug and COM changes were intentional.
  Neither the dashboard nor MQTT depends on a fixed COM number. Do not label
  that observation a USB/power fault without additional evidence.
- Independently, an ultrasonic no-echo produces a valid fresh G3 message with
  an unknown distance. That is different from stale/missing gateway telemetry.

## Repair

Only `firmware/esp32_gate_sim` changed. Before each MQTT retry the network task
closes its old TCP client. After six consecutive negative PubSubClient transport
errors it disconnects/reassociates Wi-Fi and starts a fresh connection attempt.
Positive broker refusal codes, including bad credentials/authorization, do not
trigger Wi-Fi churn. Successful MQTT connection resets the failure counter.

The existing five-second retry interval, one-second socket timeout, 15-second
keepalive, authenticated broker, enterprise certificate checks, UART task,
environment sampling, non-retained messages, queue TTL/generation protections
and command expiry rules are preserved. The UNO, cameras and server configuration
are unchanged. No gate command, passage confirmation or hold reset was sent.
Servo remains disconnected and compile-disabled on the UNO.

This provides automatic recovery from an associated-but-unusable connection.
It cannot guarantee a continuously available hotspot or turn a missed echo into
valid clearance. Unknown remains the correct display when data is unavailable.

## Build, upload and verification

Existing ESP32 core 4.0.0 and installed Arduino libraries were reused. The first
compile lacked the existing PubSubClient library search path; the corrected
command used the library folder recorded in the prior verified build. No new
dependencies were installed.

```powershell
g++ -std=c++11 -Wall -Wextra -Werror firmware/esp32_gate_sim/tests/mqtt_recovery_test.cpp -o .runtime/mqtt-recovery-test.exe
& ./.runtime/mqtt-recovery-test.exe
& ./.tools/arduino-cli/arduino-cli.exe compile --config-file .runtime/arduino-gate.yaml --fqbn esp32:esp32:esp32 --libraries C:/Users/Hypermom/OneDrive/Documents/Arduino/libraries --library firmware/gate_common --build-path .tools/build-esp32-recovery firmware/esp32_gate_sim
```

Policy assertions passed: no reassociation before the sixth transport failure,
bounded repeat behavior, success resets the counter, and broker refusal resets
the transport-failure streak without reassociation. Compile passed: 1,005,073
bytes program storage (76%), 50,976 bytes global RAM (15%), 276,704 bytes remaining.
The compiled binary was checked for the new recovery diagnostic string.

The gateway was uniquely identified by its CH9102 USB hardware identity at the
time of upload, then detected as COM10. `arduino-cli upload --verify` passed
flash hash verification and restarted only ESP32. COM10 is an observation, not
a deployment requirement. Never select a board solely by an old COM number.

Actual post-upload observation is recorded in
[gateway-mqtt-recovery.json](evidence/gateway-mqtt-recovery.json). It is a short
normal-operation check, not proof of indefinite uptime or a live injected-outage
acceptance test. No full regression, OCR/camera test or parking-session write
was performed for this repair.

## Rollback

The previous verified build was copied to the ignored local directory
`.tools/rollback-esp32-before-reconnect/` before compiling. Keep its binaries
private because firmware embeds local configuration. To roll back, identify the
current gateway COM port again, then use that build directory as `--input-dir`
with the same ESP32 target and `upload --verify`. Do not flash the UNO or cameras.
Source rollback is the prior branch head `5e920f1`; persistent server data and
pending feedback require no reset or migration.
