# Automatic gate operation — hardware acceptance pending

The later [physical inferred-clearance extension](physical-inferred-contract.md)
supersedes the P3 rejection/API-pending description below only when both explicit
policy opt-ins are enabled. The original default G3/A3 behavior remains unchanged.

Extends the integrated UNO `GateBench` controller from main `f92ef31`.
No upload or physical movement was performed. Existing private configuration,
environments, OCR models, sensor storage and teammate source are unchanged.
The previous joint-test worker was stopped, preventing old automatic commands.
An unrelated existing camera CSS edit is excluded from this feature commit.

## Build modes

| Compiler definitions | Behavior | UART prefix / telemetry mode |
|---|---|---|
| none | Preserved supervised simulation; explicit confirmation and close | G3 / entrance_exit_sim |
| GATE_AUTOMATIC_ENABLED=1 | Autonomous simulated movement; D9 detached | A3 / entrance_exit_auto_sim |
| GATE_AUTOMATIC_ENABLED=1, GATE_PHYSICAL_ENABLED=1 | Prepared physical actuator; acceptance required before upload | P3 / entrance_exit_auto_physical |

`GATE_PHYSICAL_ENABLED` defaults to zero. Physical mode cannot be enabled by MQTT
or a runtime ARM command. `GATE_OPEN_ANGLE` defaults to 80 and
`GATE_CLOSED_ANGLE` to 10 degrees; both must be different and within 5–175.
The driver retains the verified 1000–2000 microsecond pulse mapping.
Existing `ANGLES|closed|open`, `MINIMUM|milliseconds`, `STATUS`, `SENSORS?`,
`STOP`, `RESET`, manual `OPEN`, `CONFIRM|cycle` and `CLOSE` diagnostics remain.
Normal automatic cycles need none of these commands. Fault holds require inspection.

Compile only, using the existing Arduino installation (PowerShell, repository root):

```powershell
$Cli = '.tools/arduino-cli/arduino-cli.exe'
$Common = @('compile', '--config-file', '.runtime/arduino-gate.yaml',
  '--fqbn', 'arduino:avr:uno', '--libraries',
  'C:/Users/Hypermom/OneDrive/Documents/Arduino/libraries',
  '--library', 'firmware/gate_common')
& $Cli @Common --build-path .tools/build-uno-auto-sim --build-property 'compiler.cpp.extra_flags=-DGATE_AUTOMATIC_ENABLED=1' firmware/uno_gate_sim
& $Cli @Common --build-path .tools/build-uno-auto-physical --build-property 'compiler.cpp.extra_flags=-DGATE_AUTOMATIC_ENABLED=1 -DGATE_PHYSICAL_ENABLED=1' firmware/uno_gate_sim
& $Cli compile --config-file .runtime/arduino-gate.yaml --fqbn esp32:esp32:esp32 --libraries C:/Users/Hypermom/OneDrive/Documents/Arduino/libraries --library firmware/gate_common --build-path .tools/build-esp32-autonomous firmware/esp32_gate_sim
```

The private/local CLI config points to the existing installed AVR and ESP32 cores.
Use the existing CLI configuration on another laptop; no new dependencies are needed.
Do not publish ESP32 binaries: they contain private configuration.

## Cycle and actuator safety

U1 D2/D3 enters AUTH; existing correlated C3 authorization must match the boot,
cycle and deadline and contain printable LCD text and car/sportcar/supercar.
The Python adapter retains UTC, direction, identity and durable duplicate checks.
The teammate worker owns recognition and reservation; no allocator is added here.
U2 D4/D5 starts local OPEN and publishes its correlated exit arrival without
waiting for an MQTT OPEN. Only one cycle runs on the shared barrier.

Automatic CLOSE requires at least 5,000 ms from opening **and** both readings
valid and continuously clear (at least 18 cm) for 2,000 ms. Any blocked or invalid
sample resets clearance. An invalid reading while OPEN prevents closing and can
recover; the existing 120-second cycle timeout still holds the controller.
An opposite-lane detection holds the cycle; simultaneous idle detections conflict.
During CLOSING, obstruction or invalid input commands reopening and a fault hold.
Closing is a 500 ms commanded movement interval, not measured arrival at an angle.

The physical actuator preloads its open pulse before first attaching D9, only on
a new OPEN transition. Boot/reset never attaches the servo or commands a close.
Repeated phase reports/commands do not repeat motion. STOP detaches D9 and holds;
position remains unknown. On a closing fault, reopening is commanded only if
already attached. A restart cannot restore or replay an old authorization.
Loss of communications cannot authorize entrance; an already open gate can
close locally only after its safety conditions. No SG90 position is measured.

Timer allocation: Servo uses Timer1; KY-002 D6 remains on Timer2 sampling;
`millis()` uses Timer0. SoftwareSerial D10/D11 retains its pin-change ISR and
19200 baud framing. Timers do not overlap, but SoftwareSerial disables interrupts
temporarily and can jitter servo pulses or delay vibration samples. Existing
bounded ultrasonic measurement/receive scheduling is preserved. Simultaneous
hardware operation must verify these effects before acceptance; compilation
alone cannot establish pulse quality or power stability.

## Passage and API boundary

U1/U2 are assigned entrance/exit approach zones, not a verified pair straddling
the barrier. A U1→U2 sequence could be an opposing vehicle and currently invokes
conflict protection. No documented geometry establishes direction through a
single barrier. Clearance, OCR, command acceptance, and elapsed time provide no
proof that a vehicle passed. This implementation makes **no passage inference**.

Automatic closure emits reason 16 (`R_UNVERIFIED`). The unchanged five-topic
`parking/test/v1/...` envelope sends `state:hold`, `passage_confirmed:false`,
`simulation:true`, reason `passage_unverified_safe_close`, and the original
arrival correlation. Exit feedback still has a null remote command ID.
The logical controller can be CLOSED while its parking outcome needs review.
Automatic mode cannot emit confirmed completion, even after diagnostic CONFIRM.
Legacy supervised simulation retains its previous confirmed-completion semantics.

At teammate `3046eb2`, unconfirmed entrance feedback retains the reservation and
marks the arrival for review. Unconfirmed exit feedback retains the active
session and occupied bay; its API does not automatically mark exit arrivals as
review, so inspect the saved feedback/pending exit for reconciliation. No active
entrance visit is created and no exit bay is released by automatic closure.
Repeated vehicles therefore cannot yield fully automatic parking accounting
with the available passage evidence. Human reconciliation is outside normal gate
motion and remains necessary for uncertain parking records.

P3 is forwarded with `servo_enabled:true` (physical build capability, not measured
motion). The current Python simulation adapter deliberately rejects it. The
teammate API requires `simulation:true`: physical service integration needs an
explicit agreement for physical-mode arrivals/ACKs/feedback, truthful
`simulation:false`, unverified outcomes and exit-review state, plus an accepted
passage-evidence policy. Do not relabel physical events as simulation or promote
inferred clearance to `passage_confirmed`. No teammate code was changed.

## Final hardware acceptance — do not merge before completion

1. Keep SG90 disconnected. Restore sensor wiring and corrected UART divider;
   use a suitable regulated external servo supply with common ground when ready.
   Check D2/D3, D4/D5, D6, D9, D10/D11 and LCD A4/A5 against the existing mapping.
2. With the owner present, upload the A3 simulation build and updated ESP32
   forwarder only after wiring is stable. Run the isolated sensor services and
   teammate passage API with local SQLite, legacy commit disabled, one worker,
   verified UTC and fresh cameras. Follow the teammate's
   `docs/passage-joint-test.md`, using `--sensor-repo C:\CEDT\Iot\sensor-monitoring`.
   Use test plate data and `parking/test/v1`; never shared Supabase writes.
3. Verify U1 authorization, LCD recognition, U2 local opening, no competing cycles,
   5-second minimum and 2-second sustained valid clearance without manual CLOSE.
   Block either sensor and remove its echo: neither may be treated as clearance.
   Interrupt closing: expect reopen/hold. Test duplicate delivery and restart;
   neither may recreate an entrance opening. Check live vibration, environment,
   UART and LCD alongside these cycles.
4. Verify unconfirmed feedback retains the entrance reservation / exit session
   and exact occupied bay. Confirm no automatic visit creation or release occurs.
   Reconcile isolated records through the agreed review procedure afterwards.
5. Before any P3 upload, obtain owner approval for power/wiring/supervision and
   agreement on the physical API boundary above. With linkage unloaded, calibrate
   conservative angles and verify boot/reset/STOP produce no pulse-induced motion.
   Test commanded open/close and obstruction recovery under supervision, checking
   supply stability, UART reception, servo jitter and UNO stack margin. Do not
   describe the commanded angle as measured position.
6. Attach the barrier only after unloaded acceptance. Repeat obstruction and
   restart safety under supervision, record actual results, then consider merge.
   Roll back by rebuilding the unchanged default mode or restoring main f92ef31
   integrated firmware; never restore the temporary standalone diagnostic sketch.
