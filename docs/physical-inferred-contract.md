# Physical inferred-clearance demonstration — sender contract

2026-11-28, `feature/autonomous-gate`, continuing `2ff87fd`.
Sender-side implementation only. No teammate source changes, uploads, servo
movement, live API writes or physical acceptance were performed.

## Explicit configuration

Both opt-ins are required for inferred completion:

1. Compile UNO with `GATE_AUTOMATIC_ENABLED=1`, `GATE_PHYSICAL_ENABLED=1` and
   `GATE_INFERRED_CLEARANCE_ENABLED=1`. The third definition defaults to **0**.
   P3 without the third definition retains unconfirmed review outcomes.
2. Set `PARKING_V1_PHYSICAL_INFERRED=yes` in the **isolated** sensor backend.
   Default/unset means G3/A3 simulation only and rejects P3. When enabled, the
   backend rejects G3/A3 and requires P3 `servo_enabled:true`. This is a build
   capability flag; neither it nor an angle indicates measured position.

Compile only, from `C:\CEDT\Iot\sensor-monitoring` using existing tools:

```powershell
& .tools/arduino-cli/arduino-cli.exe compile --config-file .runtime/arduino-gate.yaml --fqbn arduino:avr:uno --libraries C:/Users/Hypermom/OneDrive/Documents/Arduino/libraries --library firmware/gate_common --build-path .tools/build-uno-auto-physical-inferred --build-property 'compiler.cpp.extra_flags=-DGATE_AUTOMATIC_ENABLED=1 -DGATE_PHYSICAL_ENABLED=1 -DGATE_INFERRED_CLEARANCE_ENABLED=1' firmware/uno_gate_sim
& .tools/arduino-cli/arduino-cli.exe compile --config-file .runtime/arduino-gate.yaml --fqbn esp32:esp32:esp32 --libraries C:/Users/Hypermom/OneDrive/Documents/Arduino/libraries --library firmware/gate_common --build-path .tools/build-esp32-autonomous firmware/esp32_gate_sim
```

After hardware and receiver readiness, stop the previous isolated backend and
all old mock/HTTP command publishers. Start exactly one isolated sender:

```powershell
$env:PARKING_V1_PHYSICAL_INFERRED='yes'
& .venv/Scripts/python.exe scripts/run-gate-demo.py
```

The existing demo launcher loads private native configuration without displaying
credentials, restricts Influx to `sensor_test`, uses `parking/test`, port 5001,
and disables test-cloud writes in this physical demonstration. It leaves the
separate production environmental/history services unchanged. The legacy sensor
origin tag remains `hardware_gate_sim` for routing compatibility; physical G3
history is additionally tagged `gate_mode=entrance_exit_auto_physical`.
The local sender SQLite ledger is always
`.runtime/parking-v1-physical-inferred-test.sqlite3`, separate from simulation.
A durable mode binding refuses reuse across physical and simulation modes.
Direct `backend/main.py` startup must also use `PARKING_V1_ENABLED=yes`,
`GATE_SCHEMA_ROUTING=isolated`, `MQTT_TOPIC_PREFIX=parking/test`,
`INFLUX_BUCKET=sensor_test`, and an existing allowed isolated data origin.

The teammate receiver/worker must independently enable this exact contract,
use separate local test SQLite/photos and accept physical commands. Do not use
the shared Supabase instance. This change neither starts nor alters that service.
The old simulation-only API is not a compatible receiver for physical feedback.

To return to supervised simulation, stop the physical sender, remove the backend
opt-in and build with no extra flags. A3 uses only `GATE_AUTOMATIC_ENABLED=1`.
Use the existing simulation ledger; do not delete or relabel the physical ledger.

## Clean-cycle evidence

The controller starts entrance eligibility only on a valid boot/cycle-correlated,
unexpired entrance authorization. A safety-checked local U2 opening starts exit
eligibility without any remote exit OPEN. Manual OPEN is ineligible.
Normal presence in the detected lane before clearance begins is expected.
Reoccupation after clearance begins is an unexpected obstruction. Invalid input,
that obstruction, opposite/simultaneous detection, closing obstruction, timeout,
STOP, hold or reset latches disqualification for the current cycle. Recovering
clear readings, CONFIRM, duplicate authorization or RESET cannot requalify it.
Only a genuinely new cycle can start a new eligibility assessment.

Reason 17 (`R_INFERRED`) is emitted only after an eligible automatic cycle has
opened for at least 5000 ms, both ultrasonic inputs have remained valid and clear
for 2000 ms, and the 500 ms commanded closing interval finishes safely. Invalid
or blocked inputs reset clearance. Reason 16 remains the safe-close review result
for an ineligible cycle or a build without the policy. UART remains 15 fields:
P3 uses the existing reason field; no G2 history is reinterpreted.

The backend additionally requires a newly observed arrival, an uninterrupted
boot/gateway/cycle trace, and observed CLOSING→CLOSED with at least 500 ms from
the first closing report. Invalid input, hold, mode mismatch, MQTT disconnect,
or a telemetry gap exceeding two seconds invalidates its trace. It cannot rebuild
eligibility from a persisted arrival after restarting. A missed closing report
therefore conservatively produces review rather than inferred completion.

This is an explicitly enabled demonstration policy, **not proof of passage**.
Both sensors still detect approach lanes; no spatial directional-passage proof
is claimed. Commanded closing is not a measured SG90 position. Parking allocation
and the choice to finalize a reservation/session from this inference belong
solely to the teammate receiver; the sensor sender never writes parking sessions.

## Exact MQTT extension

Keep the five existing `parking/test/v1/` topics and all existing identity,
timestamp, direction and correlation fields. Retries preserve exact payloads
and event IDs. No production topic override is supported in physical inferred mode.

| Topic suffix | Physical sender/receiver requirement |
|---|---|
| `arrival` | Existing arrival fields plus `simulation:false`; U1 entrance/U2 exit, trigger ultrasonic |
| `gate/command` | Existing correlated entrance OPEN fields plus mandatory `simulation:false`; missing/true/non-boolean rejected. No exit OPEN |
| `gate/ack` | All physical ACK outcomes, including rejection/timeout/restart, contain `simulation:false`. Accepted means open was commanded, not measured. Physical ACK omits the old simulation-only `physical_movement:false` field |
| `gate/feedback` | Always `simulation:false`, `passage_confirmed:false`. Eligible terminal result adds `state:completed`, `passage_basis:inferred_clearance` |
| `gate/feedback/ack` | Existing recorded receipt fields and correlation remain unchanged. If an optional simulation field is present, it must match false |

Example eligible exit feedback (illustrative IDs; never publish as test proof):

```json
{
  "schema_version": 1,
  "event_id": "example_feedback",
  "producer_id": "sensor-gateway",
  "occurred_at": "2026-11-28T00:00:00+00:00",
  "arrival_id": "r_example_boot_1",
  "command_id": null,
  "direction": "exit",
  "state": "completed",
  "simulation": false,
  "passage_confirmed": false,
  "passage_basis": "inferred_clearance",
  "reason": null
}
```

Entrance feedback has the original entrance `command_id`. Ineligible results
are `state:hold`, have no `passage_basis`, and retain existing review reasons.
Durable deduplication, original expiry checks, application feedback receipts and
2/4/8/16/30-second retry backoff remain active. G3 supervised payloads/confirmed
simulation and A3 unconfirmed automatic simulation are unchanged.

## Remaining hardware acceptance

1. With SG90 disconnected, verify reorganized wiring, valid U1/U2 readings,
   common ground and corrected UART divider. Confirm stable external servo power
   and safe unloaded linkage before approving any physical build upload.
2. Confirm the teammate receiver and single worker support this contract on local
   test SQLite, the clocks are verified and both cameras provide fresh images.
   No live receiver acceptance is claimed by the sender software tests.
3. Under supervision, upload the reviewed UNO/ESP32 variants, calibrate conservative
   angles and verify no motion on boot/reset, duplicate/stale commands or restart.
4. Exercise clean authorized entrance and local exit without manual close; observe
   5-second minimum, 2-second clearance and commanded closing. Check LCD, UART,
   environment/vibration sampling, pulse jitter and supply/stack stability together.
5. Inject invalid echoes, reoccupation, opposite-lane detection, closing obstruction,
   STOP, communication loss and recovery. Confirm no inferred outcome survives the
   fault. Verify inference is visibly distinct from verified physical passage.
6. Save actual sender/receiver and supervised movement evidence before considering
   merge. Keep the default simulation firmware as rollback; never use the standalone
   servo diagnostic sketch as the integrated baseline.
