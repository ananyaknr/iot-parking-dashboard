# Sensor monitoring test results

Date: 2026-11-25 (Asia/Bangkok).

Current status: **Native Windows deployment and actual UNO/ESP32 MQTT → InfluxDB → Flask API verification PASS. Controlled physical acceptance remains incomplete.** Original Phase 1 acceptance is incomplete: three cycles passed, seven skipped by user; vacant-side hysteresis and no-echo/recovery not completed. Later user instructions expanded the scope to ESP32 and server implementation. Historical entries below retain their status at the time of capture.

## Native Windows revision — 2026-11-25

- Native Mosquitto 2.0.22, InfluxDB OSS 2.10.1 and Python 3.12 virtual environment installed locally. Flask/Waitress dashboard and locally served Chart.js replace Grafana. Legacy Docker files are inactive; no new container images were downloaded. No project-owned Docker resources were identified for deletion; unrelated resources were left untouched.
- Authenticated MQTT listens on the PC hotspot address `172.20.10.12:1883`; InfluxDB and dashboard bind to loopback ports 8086 and 5000. The scoped MQTT firewall rule allows the local subnet. Both InfluxDB buckets have seven-day retention.
- Ten backend unit tests passed. Eight isolated synthetic pipeline checks passed, covering three topics, null/invalid values, malformed JSON, stale/recovery behavior, M1 exclusion and historical API retrieval. Synthetic data uses only `parking/test/*` and `sensor_test`, never real telemetry topics. Evidence: [synthetic results](runtime-logs/synthetic-results.json).
- Native service stop/start and dashboard readiness passed. Startup/shutdown verify executable paths and process start times before managing project processes.
- ESP32 personal-hotspot build compiled and uploaded to user-confirmed COM9, with flash hash verification. UNO was not reuploaded. An initial upload was blocked by Arduino IDE's COM9 Serial Monitor; closing it released the port. Evidence: [compile log](runtime-logs/esp32-hotspot-compile.txt), [upload log](runtime-logs/esp32-upload.txt).
- Actual USB output after upload showed valid forwarded UNO and ESP32 sensor JSON, including A1 distance 17.5 cm, temperature 24.4 °C, humidity approximately 60%, and raw light/gas readings. These passive observations do not establish a controlled physical test.
- Two 60-second real-MQTT captures received zero messages: one before successful upload, one after upload while ESP32 Wi-Fi association was failing. **End-to-end hardware test: NOT PASSED.** Evidence: `runtime-logs/hardware-20261125T110055Z` and `runtime-logs/hardware-20261125T110639Z`. Wi-Fi retry correction and diagnostics are in progress.
- Measured at 11:09 UTC: native components including retained download archives occupied 340,262,798 bytes (324.5 MiB); total workspace growth since baseline was 382,313,355 bytes (364.6 MiB). Existing Arduino toolchains are excluded from the additional footprint. Seven-day retention is not a disk quota. Evidence: [footprint report](runtime-logs/footprint.json).
- Camera integration interface is implemented, but no teammate camera hardware messages have been received. M1 and vibration remain not installed. MQ-2 remains unconditioned/uncalibrated; no ppm or gas-safety claim is made.
- Wi-Fi retry correction compiled (978,253 bytes flash, 50,552 bytes RAM) and uploaded with flash hash verification. Retries are now task-owned, disconnect before restarting association, and allow twenty seconds per attempt. Actual USB diagnostics report reason 201 (`WIFI_REASON_NO_AP_FOUND` in the installed Espressif header), while Windows remains connected to `jm` on 2.4 GHz channel 6. Configured and compiled SSID/broker address match. Hotspot visibility remains unresolved; no end-to-end pass is claimed. Evidence: [USB diagnostics](runtime-logs/esp32-wifi-diagnostics.txt).
- Actual anonymous MQTT connection test returned `Not authorized`: PASS. UNO source SHA-256 still matches the previously verified firmware record (`60AE0E360CCF374B9DB0ADB499F9E935596F1137C5F0A0C0D33E3F797BAED43D`). Temporary credential form port 8765 is closed.
- After the user confirmed iPhone Maximize Compatibility ON and kept the hotspot nearby/open, actual messages began arriving using the retry-corrected firmware. The exact cause of the earlier access-point discovery failure is not established. An additional scan build was cancelled before execution because connection had recovered; no scan firmware was uploaded.
- **Actual hardware pipeline PASS:** 60-second capture received 60 UNO and 24 ESP32 non-retained messages, zero validation errors. Both sources were fresh, MQTT/database connected, and historical APIs returned 96 non-null A1 points and 102 each for temperature/light in the five-minute query. No camera messages were received. Evidence: [hardware summary](runtime-logs/hardware-20261125T111540Z/summary.json), [raw messages](runtime-logs/hardware-20261125T111540Z/mqtt-events.jsonl). Earlier failed captures remain recorded. This is a pipeline test, not controlled physical acceptance.
- **Final toy-car occupied check PASS:** user confirmed the car at approximately 10 cm, broad side at transducer height. Ten one-second API checks all showed fresh valid occupied state, with measured A1 distance 9.7–9.8 cm. Both sources remained fresh; M1 remained excluded. Ambient readings were 24.3 °C, 60.7–60.8% RH, light ADC 538–563, gas ADC 369–503 (uncalibrated). Evidence: [car capture](runtime-logs/physical-20261125T111734Z/evidence.json). Removal/vacant half is pending.
- **Final toy-car removal check PASS:** after user confirmed removing the car and positioning a backing surface at approximately 30 cm, all ten API checks showed fresh valid vacant state at 24.3–27.7 cm. This confirms classification, not calibrated 30 cm ranging accuracy. Both sources stayed fresh and M1 stayed excluded. Evidence: [removal capture](runtime-logs/physical-20261125T111845Z/evidence.json). One final occupied/vacant car sequence is complete; this does not complete the previously skipped ten-cycle test. Uncovered LDR baseline during this capture was ADC 576–598.
- **LDR cover/uncover response PASS:** user confirmed covering only the LDR, then uncovering it. Ten API checks while covered returned raw ADC 2147–3344; ten recovery checks returned 573–597, matching the uncovered baseline 576–598. ESP32 remained fresh. This verifies response/recovery of raw light readings, not lux calibration. Evidence: [covered](runtime-logs/physical-20261125T111935Z/evidence.json), [uncovered](runtime-logs/physical-20261125T112015Z/evidence.json).
- During LDR manipulation, six covered-capture A1 checks had invalid distance. All six correctly showed Unknown and allocation disabled. Four valid 16.8 cm distance checks still had Unknown occupancy, so allocation remained disabled. The cause of the temporary ultrasonic invalid readings was not established; this incidental observation is not the pending controlled no-echo/recovery test.
- **Physical UNO disconnection handling PASS:** user unplugged only UNO USB, leaving ESP32 powered. Fifteen API checks all showed UNO stale, A1 Unknown and allocation disabled; ESP32 stayed fresh in all fifteen. M1 remained excluded. Evidence: [disconnection](runtime-logs/physical-20261125T112123Z/evidence.json). Capture began after disconnection; exact ten-second transition latency was not measured in this physical test (threshold behavior is covered by software tests).
- **UART/MQTT recovery PASS; stable ultrasonic recovery initially NOT PASSED:** after confirmed UNO USB reconnection, all ten API checks showed fresh UNO and ESP32 telemetry, but nine had invalid A1 echo/occupancy and only one valid vacant reading at 36.5 cm. Unknown/disabled allocation was preserved for all invalid samples. Evidence: [initial recovery](runtime-logs/physical-20261125T112205Z/evidence.json). A repeat with a broad steady target is pending; no stable ultrasonic recovery pass is inferred from restored communication alone.
- Updated footprint at 11:22 UTC: native components 341,086,653 bytes (325.3 MiB), including archives; total workspace growth 383,417,594 bytes (365.7 MiB). Free C: space was 2,523,062,272 bytes. Seven-day retention remains configured; future data growth is not included in this point-in-time measurement.
- **Steady-target ultrasonic recovery repeat PASS:** after the user repositioned a broad target squarely in front of A1, all ten API checks were fresh and valid, vacancy true and allocation eligible; distance was 22.2–22.3 cm. ESP32 stayed fresh and M1 excluded. Evidence: [repeat recovery](runtime-logs/physical-20261125T112316Z/evidence.json). The target was user-reported approximately 30 cm, so calibrated distance accuracy is not claimed. The earlier unstable recovery attempt remains recorded.
- Physical car occupancy/removal, LDR cover/uncover, UNO stale handling and restored valid telemetry have now been observed through the actual production MQTT/backend/API path. No browser visual acceptance is inferred from API captures. Earlier skipped Phase 1 checks and MQ-2 calibration remain outstanding.
- **Final deployed service checks PASS:** unauthenticated live API returned HTTP 401; authenticated dashboard HTML, CSS, JavaScript and local Chart.js returned HTTP 200 with nonempty bodies. Actual InfluxDB API confirmed 604,800-second retention on both buckets. Persisted hardware records span ESP32 11:14:55–11:24:30 UTC (229 telemetry records) and UNO 11:14:55–11:24:32 UTC (506 telemetry records). This approximately nine-minute observation includes the intentional UNO disconnection; no uninterrupted UNO stream or zero-drop claim is made. Evidence: [final service checks](runtime-logs/final-service-checks.json). Native services remain running for demonstration.

## Original Phase 1 record

## Hardware and configuration

- Arduino UNO / UNO-compatible board confirmed by user on COM8. CLI and Windows enumerate USB VID 1A86 / PID 7523 (CH340). Bootloader responds with ATmega328P signature `1E 95 0F`.
- User confirmed A1 wiring ready, UNO connected, and upload authorized.
- One HC-SR04 available: A1 TRIG D2, ECHO D3, 5V and GND.
- `M1_SENSOR_ENABLED = false`; D4/D5 remain reserved. M1 implementation is retained.
- Vibration not installed or sampled; D6 reserved. D9 servo and A4/A5 LCD remain reserved.
- USB serial and gateway UART remain at 9600 baud; D10/D11 reserved for gateway. External gateway hardware was not tested.

## Software results

| Check | Result | Actual evidence |
|---|---|---|
| Local dependency installation | PASS | User approved; Arduino CLI 1.6.0, AVR Boards 1.8.8 installed in `.tools` |
| UNO port identification | PASS | COM8 appeared after connection; USB CH340; user confirmed board identity |
| Current configuration build | PASS | `arduino:avr:uno`; flash 6410 / 32256 bytes, SRAM 321 / 2048 bytes |
| Future enabled-M1 build | PASS, compile only | Staged copy with flag true; flash 6814 bytes, SRAM 321 bytes; never uploaded |
| Upload | PASS | COM8, 6410 bytes written, exit code 0 |
| Flash readback verification | PASS | Separate avrdude compare: 6410 bytes verified, exit code 0 |
| Capture script syntax | PASS | PowerShell parser check passed |

No sketch compilation errors occurred. `--warnings all` reported unused `tag` parameters in the Arduino core's `new.cpp`; no sketch warnings were reported. Original sketch remains configured with M1 disabled. Source and uploaded HEX SHA256 hashes are in [firmware-hashes.txt](build-logs/firmware-hashes.txt).

Evidence: [core list](build-logs/core-list.txt), [board enumeration](build-logs/board-list.json), [current compile](build-logs/compile.txt), [future M1 compile](build-logs/compile-future-m1.txt), [upload](build-logs/upload.txt), [flash verification](build-logs/flash-verify.txt), [dependency installation](build-logs/dependency-install.txt).

## Actual serial capture: baseline

User-reported setup: empty-slot flat target ready at approximately 30 cm. Target position and wiring were not visually verified by the agent.

Capture: COM8, 9600 baud, 60 seconds, beginning approximately 14:12:36 Bangkok time. Startup buffer was flushed, and one boundary line was discarded and retained in the summary. One trailing incomplete line was retained separately, excluded from complete-message validation.

- 59 complete messages; all 59 passed JSON/schema/type/disabled-field checks; zero complete-line validation errors.
- Mean interval: 1.001336867 seconds.
- Every complete message had null `m1_distance_cm`, `m1_occupied`, `vibration` and `vibration_count`; `vibration_status` was `not_installed`.
- 26 valid A1 distances: minimum 15.5 cm, maximum 20.4 cm, mean 17.0231 cm.
- 33 messages had no valid echo (both A1 fields null).
- Occupancy totals: 25 vacant, 0 occupied, 34 unknown (33 no-echo messages plus one initial valid distance in the hysteresis band).

**Telemetry format/cadence PASS. A1 physical empty-slot acceptance is not established.** Distances did not agree with the stated 30 cm target and later became no-echo. This is an observed discrepancy requiring a controlled repeat, not a confirmed sensor defect. User asked to check wiring, clear nearer reflectors, align the flat target, and report whether it moved during capture. No physical occupancy pass is claimed from this capture.

Evidence: [raw JSON](serial-logs/baseline/20261125-141236-raw.jsonl), [timestamped validation events](serial-logs/baseline/20261125-141236-events.jsonl), [capture summary](serial-logs/baseline/20261125-141236-summary.json).

## Physical acceptance record

| Check | Status | Actual evidence |
|---|---|---|
| A1 empty with target 25–50 cm | PASS on repeat | Exact-30-cm retest: ten valid vacant readings, 27.6–28.9 cm; earlier inconsistent trials retained below |
| A1 occupied: five consecutive valid occupied readings | PASS on repeat | Ten consecutive readings at 12.8 cm, occupied=true; earlier unsuccessful attempt retained below |
| Vacant classification after target moved away | PASS | Nine valid vacant readings; measured 50.8–57.2 cm differs from intended 30 cm; transition not captured |
| Ten occupied/release cycles | INCOMPLETE — remaining cycles skipped by user | 3/10 cycles observed passed; cycles 4–10 skipped at user request |
| A1 hysteresis in both directions | PARTIAL — remaining direction not completed | Occupied-side hold PASS at 16.2 cm; user requested a final car test before completing the vacant-side hold |
| A1 controlled no echo and recovery | Pending | Baseline no-echo was uncontrolled; does not count as this test |
| Disabled M1 null throughout baseline | PASS | 59/59 complete messages |
| Vibration null/null/not_installed throughout baseline | PASS | 59/59 complete messages |
| M1 physical occupancy | Deferred | Second HC-SR04 unavailable |

Acceptance procedure: [phase1.md](phase1.md). Future M1 installation requires wiring with USB disconnected, setting the flag true, rebuilding/uploading and running its deferred physical tests.

## Environment notes

No Git repository was detected. Other subsystem directories were empty at inspection. Arduino CLI was initially absent from PATH and checked common locations; no platform was installed in the project-local data directory. All approved tools, packages and caches are under `.tools`, with no global PATH change. Windows CIM serial enumeration was denied; registry, .NET and CLI enumeration succeeded. Initial CLI download failed under sandbox TLS restrictions; an approved network escalation succeeded. An initial unconfigured CLI version invocation reported a denied global inventory write; all subsequent CLI commands used `.tools/arduino-cli.yaml`.

## A1 retest — toy car reported at 30 cm

User reported placing a toy car 30 cm in front of the sensor. A subsequent 15-second capture on COM8 at 9600 baud produced 14 complete messages, all valid JSON with the expected disabled M1/vibration fields. Mean message interval was 1.00493 seconds. Ten A1 readings were valid, ranging from 58.6 to 88.0 cm, with vacant occupancy; four readings had no echo and null occupancy. The initial boundary line and trailing partial line are recorded separately in the summary.

The readings do not agree with the reported toy-car distance. Physical acceptance remains pending. A small/angled target or the sensor looking above the car may explain this, but the cause has not been established. Next physical step: use a large flat upright book cover or cardboard sheet, square to the sensor at its height, 30 cm from the sensor front face; keep it stationary for a repeat capture. No controlled occupied/release cycles have been performed.

Evidence: [raw JSON](serial-logs/a1-30cm-retest/20261125-141719-raw.jsonl), [timestamped events](serial-logs/a1-30cm-retest/20261125-141719-events.jsonl), [summary](serial-logs/a1-30cm-retest/20261125-141719-summary.json).

## A1 wallet retest / telemetry preview

User replaced the target with a wallet after the request for a 30 cm flat target. The wallet's exact distance, orientation and wiring were not independently observed. A 15-second capture on COM8 at 9600 baud produced 14 complete, valid JSON messages with zero validation errors and a mean interval of 0.9990262 seconds. All 14 A1 distances were 15.8–17.1 cm, with occupied=true. No complete sample had a missing echo. M1 and vibration fields remained correct throughout.

Physical acceptance remains pending: these distances differ from the requested 30 cm setup. Occupied=true at 15.8–17.1 cm is permitted by the existing 15/18 cm hysteresis; it can retain a prior occupied state, so this alone is not evidence of a firmware error. No controlled occupied/release cycle or hysteresis test is claimed. Next diagnostic step is a photo of sensor/target alignment and UNO wiring, or a rigid upright book cover with distance measured from the front faces of the sensor transducers.

Evidence: [raw JSON](serial-logs/a1-wallet-30cm/20261125-142123-raw.jsonl), [timestamped events](serial-logs/a1-wallet-30cm/20261125-142123-events.jsonl), [summary](serial-logs/a1-wallet-30cm/20261125-142123-summary.json).

### Wallet distance correction from user

The user clarified that the wallet was actually placed approximately **16–17 cm** from the sensor, rather than 30 cm. This supersedes the assumed target distance for the wallet retest above. The measured 15.8–17.1 cm readings agree approximately with that user-reported placement. The earlier wallet distance discrepancy is therefore resolved; it is not evidence of a ranging fault. All 14 complete readings retained occupied=true in the 15–18 cm hysteresis band, as allowed by the firmware. This is a useful distance observation, but does not establish the controlled empty, occupied, release or full hysteresis acceptance tests. The earlier toy-car/baseline observations remain unchanged.

Next controlled test: place a flat upright target at 5–12 cm, confirm readiness, then capture at least five consecutive valid occupied readings before moving it to 25–30 cm for the release test.

## Requested occupied test — approximately 10 cm

After the instruction to move the wallet to about 10 cm and hold it still, the user replied 'done'. A 10-second capture on COM8 at 9600 baud produced nine complete messages, all valid JSON, with a mean interval of 0.99591994 seconds. Every measured A1 distance was 34.7–35.5 cm and every occupancy value was false. No complete sample had a missing echo. Disabled M1/vibration fields remained correct. Startup boundary and trailing partial lines were retained in the capture summary.

**Occupied acceptance attempt: NOT PASSED; retest required.** Zero of nine complete messages were occupied. The physical distance/alignment was not independently verified, so the cause is not established. Five consecutive occupied readings were not obtained, and this does not count as a successful occupancy cycle. Next step is to confirm measured distance and alignment, preferably with a photo showing the sensor, target and ruler.

Evidence: [raw JSON](serial-logs/a1-occupied-10cm/20261125-142500-raw.jsonl), [timestamped events](serial-logs/a1-occupied-10cm/20261125-142500-events.jsonl), [summary](serial-logs/a1-occupied-10cm/20261125-142500-summary.json).


## Occupied retest — user moved wallet to approximately 10 cm

User explicitly reported moving the wallet to 10 cm. The subsequent 10-second capture on COM8 at 9600 baud produced **10 consecutive complete messages**, each with `a1_distance_cm: 12.8` and `a1_occupied: true`. All ten passed JSON validation with the expected disabled M1/vibration fields; no no-echo samples occurred. Mean interval was 0.99703338 seconds. There was no trailing partial line; the startup boundary line is recorded in the summary.

**Occupied detection check: PASS** (at least five consecutive valid readings below the 15 cm occupied threshold). This validates occupied classification, not calibrated distance accuracy: user-reported placement was approximately 10 cm, whereas the sensor reported 12.8 cm. The earlier unsuccessful attempt remains part of the record. Release, ten complete cycles, controlled hysteresis, no-echo/recovery and overall acceptance remain pending.

Evidence: [raw JSON](serial-logs/a1-occupied-10cm-repeat/20261125-142715-raw.jsonl), [timestamped events](serial-logs/a1-occupied-10cm-repeat/20261125-142715-events.jsonl), [summary](serial-logs/a1-occupied-10cm-repeat/20261125-142715-summary.json).


## Release check — wallet moved to approximately 30 cm

User confirmed readiness after being instructed to move the wallet from the occupied setup to approximately 30 cm. A 10-second capture on COM8 at 9600 baud produced **nine consecutive valid complete messages**, all `a1_occupied: false`, with A1 distances ranging from **50.8 to 57.2 cm**. No complete sample had a missing echo. All disabled M1/vibration fields remained correct. Mean interval was 0.994148 seconds. The summary preserves the discarded startup boundary line and trailing partial line.

**Vacant classification after moving the target: PASS** (at least five consecutive valid vacant readings). The transition itself occurred between captures and was not observed continuously, so no transition latency or completed repeatability cycle is claimed. The intended 30 cm target still differs substantially from the returned distance; the controlled 25–50 cm empty-target ranging check remains unresolved. A wallet may be too small or angled, but that cause is not established. Next step: use a rigid upright book cover or cardboard sheet with a broad face centered at sensor height, measured 30 cm from the sensor's round front faces, then repeat the empty check before the ten-cycle test.

Evidence: [raw JSON](serial-logs/a1-release-30cm/20261125-142856-raw.jsonl), [timestamped events](serial-logs/a1-release-30cm/20261125-142856-events.jsonl), [summary](serial-logs/a1-release-30cm/20261125-142856-summary.json).


## Empty-target retest — user measured exactly 30 cm

User reported moving the target to exactly 30 cm. The subsequent 10-second capture on COM8 at 9600 baud produced **10 consecutive valid complete messages**, all `a1_occupied: false`, with distances **27.6–28.9 cm** (eight samples at 28.8 cm). No no-echo samples occurred. All disabled M1/vibration fields remained correct, and mean interval was 0.99727601 seconds. No trailing partial line remained; the discarded startup boundary line is retained in the summary.

**Controlled empty-target detection: PASS** against the Phase 1 criterion of at least five consecutive valid vacant readings with a target 25–50 cm away. Distances were close to but below the user-measured 30 cm; this is not a calibrated accuracy certification. Earlier inconsistent trials remain recorded; this successful retest supersedes the pending empty-detection status. Occupied and vacant snapshots have now passed. Ten continuously observed occupied/release cycles, controlled hysteresis and no-echo/recovery are still required before overall Phase 1 acceptance.

Evidence: [raw JSON](serial-logs/a1-exact-30cm/20261125-143218-raw.jsonl), [timestamped events](serial-logs/a1-exact-30cm/20261125-143218-events.jsonl), [summary](serial-logs/a1-exact-30cm/20261125-143218-summary.json).


## Continuous repeatability session in progress

Continuous capture folder: docs/serial-logs/a1-cycles-20261125-144125. Serial remains open between movements. Cycle 1: user confirmed the move to 10 cm, then the return to 30 cm. Observed at least five consecutive occupied readings (approximately 9.4–12.1 cm) followed by at least five consecutive vacant readings (27.0 cm). **1/10 cycles observed passed so far**; final session analysis and remaining cycles are pending. User response times extended the holds beyond ten seconds; no ten-second timing precision is claimed. Prompt timestamps are in actions.jsonl and serial observations are timestamped separately. No further cycle is counted until both states are observed.

Cycle 2 occupied half: user confirmed holding at 10 cm. Continuous log shows more than five consecutive valid occupied readings at 11.1–11.2 cm (including 07:44:00–07:44:07 UTC). Occupied half PASS; return to vacant is pending. Completed count remains 1/10. Recording remains active.

Cycle 2 return: user confirmed holding at 30 cm. Continuous log shows at least ten consecutive valid vacant samples at 28.8–30.2 cm (07:45:01–07:45:10 UTC), following the recorded occupied half. **Cycle 2 PASS; completed count 2/10.** Disabled M1/vibration fields remained correct in those samples. Cycle 3 is awaiting the user move to 10 cm.


Cycle 3 occupied half: user confirmed holding at 10 cm. Continuous capture shows ten consecutive valid occupied samples at 11.7–11.8 cm (07:50:20–07:50:29 UTC), with expected disabled fields. Occupied half PASS; return to vacant pending. Completed count remains 2/10. Capture remained active when checked at 07:50:30 UTC.


## Repeatability session closed at user request

User instructed: 'everything looks fine, skip that test'. Interpreted as skipping the remainder of the current ten-cycle repeatability test. Capture was stopped cleanly and the serial port closed. No additional cycles will be requested as part of this run.

The already-recorded Cycle 3 return was checked before closing the record: five consecutive valid vacant readings at 29.4–29.5 cm occurred at 07:51:52–07:51:56 UTC, following the recorded occupied half. User had confirmed returning the object to 30 cm. **Cycles 1–3 PASS; cycles 4–10 SKIPPED BY USER. The ten-cycle test is incomplete, not passed.**

Continuous capture: 661 complete messages over 661.896 seconds; all 661 passed validation, zero complete-line errors, mean interval 0.9999869 seconds. Startup partial boundary line is preserved in the summary; no trailing partial line remained. Message timing and disabled fields passed. Extended holds reflect user response time; no transition response-time limit is claimed.

Evidence: [raw JSON](serial-logs/a1-cycles-20261125-144125/20261125-144126-raw.jsonl), [timestamped events](serial-logs/a1-cycles-20261125-144125/20261125-144126-events.jsonl), [prompt/action log](serial-logs/a1-cycles-20261125-144125/actions.jsonl), [summary](serial-logs/a1-cycles-20261125-144125/20261125-144126-summary.json).

Overall Phase 1 acceptance remains incomplete. Controlled hysteresis and controlled no-echo/recovery are still pending; M1 physical testing is deferred due to unavailable hardware. Phase 2 has not started.

## Controlled hysteresis session in progress

User confirmed ready with the target at 30 cm. A new continuous serial capture was opened in docs/serial-logs/a1-hysteresis-20261125-145341. The first six complete messages had A1 distances 29.4–29.5 cm and occupancy=false, with correct disabled M1/vibration fields. Vacant baseline established. Next stage: move inward to 16–17 cm without crossing the occupied threshold, then observe at least five valid middle-band readings retaining false. Both directional hysteresis checks remain pending. Serial will remain open through both directions to preserve state.

Hysteresis attempt 1: user reported holding at 16–17 cm. Only two consecutive samples stayed at 16.2 cm with occupied=false (07:56:17–07:56:18 UTC); subsequent readings settled at 14.8–14.9 cm and occupied=true. The 15 cm enter threshold was crossed in measured telemetry, so this attempt does not establish the required five-sample vacant hold in the middle band. No firmware failure is inferred. More than five valid occupied readings at 14.8–14.9 cm now establish the occupied baseline. Direction order adjusted: request moving approximately 2 cm farther away to obtain measured middle-band samples while retaining true; vacant-side check remains pending.

Occupied-side hysteresis PASS: after the valid occupied baseline at 14.8–14.9 cm, user confirmed moving the object about 2 cm farther away. Ten consecutive valid middle-band samples at **16.2 cm** retained occupied=true (07:57:37–07:57:46 UTC), with correct disabled M1/vibration fields. Serial remained open throughout. Next: ask user to mark this physical position, move to 30 cm to establish vacant again, then return to the marked position without going closer. Vacant-side hysteresis remains pending.



## Scope update: final car test, then another sensor

User requested one final car test, then moving to another sensor. The hysteresis capture was stopped cleanly. Occupied-side middle-band retention passed; the full vacant-side middle-band hold was not completed. After user confirmed moving back to 30 cm, the last six readings before stop were valid vacant readings at 57.1–57.5 cm; no return to the marked middle-band position was requested or recorded.

Hysteresis-session serial summary: 366 complete messages, 366 valid, 0 errors, 366.5207929 seconds, mean interval 0.99994397013698622 seconds. Evidence folder: docs/serial-logs/a1-hysteresis-20261125-145341 (raw JSON, timestamped events, actions and summary). Original pending controlled no-echo/recovery checks remain uncompleted. The ten-cycle test remains incomplete with three cycles passed and seven skipped at user request. Overall Phase 1 full acceptance is not claimed; Phase 2 has not started. No new sensor implementation or vibration behavior change has been authorized by a specific sensor selection yet.

Final car test planned: place the toy car so its front or broad side faces the sensor at approximately 10 cm and is at the same height as the transducers; keep a rigid backing surface approximately 30 cm behind the viewing path. Verify occupied samples, then remove the car to verify valid vacant readings from the backing surface. Do not count no echo as vacancy.
