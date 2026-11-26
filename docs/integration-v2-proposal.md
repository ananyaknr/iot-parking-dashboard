# Gate v2 shared interface proposal — awaiting teammate agreement

Supersedes the bay-allocation assumptions of the historical v1 proposal for this
gate assignment. Our subsystem owns sensing, the UNO gate simulation, UART,
MQTT, sensor validation/storage and the existing dashboard. The teammate owns
capture, recognition, photos, parking sessions and entry/exit matching.
No teammate implementation or shared production interface has been changed.

The proposed path is U1 arrival → UNO → ESP32 → MQTT → backend → teammate
recognition → backend → ESP32 → UNO LCD. Recognition never allocates a bay here.
Production request/result topics, authentication, timeout/retry and authorization
ownership require agreement before enabling delivery. Camera/session records
and license plates never enter either sensor cloud bucket.

## Correlation and display

Gate telemetry uses schema_version 2, mode gate_sim, servo_enabled false and a
random 128-bit boot_id. IDs are `v2:<boot>:a:<arrival_count>`,
`v2:<boot>:p:<completed_count>` and `v2:<boot>:e:<event_seq>`.
Counters are boot-scoped cumulative values, not occupancy or free-space counts.
Local parking_gate_v2 and parking_gate_events_v2 preserve old measurements.
The bounded event ledger preserves the first receipt timestamp across retry and
backend restart. Exhaustion/error is visible; it never silently deletes history.

The disabled-by-default mock endpoint POST /api/integration/recognition accepts
only an isolated synthetic result, with these exact keys:
schema_version, result_id, arrival_id, occurred_at, license_plate, lcd_plate,
vehicle_type, status, authorized, origin, session_id, photo_ref.
Schema is 2; origin synthetic; session_id/photo_ref must be null pending contract.
The arrival must currently be active and fresh; results expire after five seconds
in transit. Duplicate IDs cannot carry different content. Type is car, supercar
or unknown. Unknown/failed results cannot authorize. Successful acceptance is
explicitly not delivery or gate authorization.

license_plate retains original Unicode/Thai text for the dashboard. lcd_plate is
a separately supplied ASCII string (1–16 characters); unsupported originals
require an explicit fallback, never silent stripping/transliteration. The mock
display expires after 30 seconds or a new arrival. No photo/session archive exists.

## UART and isolation

USB baud is 115200 on both boards; inter-board SoftwareSerial/UART is 19200.
Bounded newline frames reject overflows, embedded controls and invalid fields.
HELLO2 / S2 boot negotiation precedes the compact 15-field G2 telemetry frame.
T2 is test display only; K2 acknowledgements correlate an eight-hex-digit command
ID and report ok, duplicate or rejected. Retries reuse the exact command ID.
Prepared L2/A2 frames require current boot/arrival correlation. Integrated mode
is disabled; no real recognition result transport is enabled.

ESP32 USB `LCD|AB1234|car` tests the reverse UART. MQTT test display subscriptions
use a random per-connection suffix announced non-retained on
parking/test/gate/lcd/ready. Stale queued generations expire; an old retained
command cannot match a later connection's random topic. This is a test facility,
not an agreed production authorization channel.

Gate routing defaults off. Isolated routing requires parking/test, sensor_test
and origin hardware_gate_sim or synthetic. Cloud uses parking_sensor_test only.
Production transition additionally requires explicit owner approval; it has not
been approved. Existing production environmental telemetry remains separate.
