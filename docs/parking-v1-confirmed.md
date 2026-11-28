# Confirmed simulation interface and G3 implementation

For the later explicit physical demonstration opt-in, see the exact
[inferred-clearance sender contract](physical-inferred-contract.md).

The opt-in [automatic gate extension](autonomous-gate.md) preserves these five
topic envelopes. A3 identifies autonomous simulation; P3 identifies a physical
build and is rejected by the simulation adapter. Automatic safe close sends
unconfirmed `hold` feedback (controller reason 16), never confirmed completion.
Physical-mode API semantics remain pending agreement; the confirmed simulation
contract below is unchanged.

Owner relayed teammate confirmation on 2026-11-27. This supersedes the earlier
unconfirmed six-topic proposal for the implemented simulation. No teammate
repository changes, session creation or Supabase writes are performed here.

## Final agreement (2026-11-27)

All five interfaces are agreed: arrival, command, command acknowledgement,
gate feedback and feedback acknowledgement. Each message has schema_version=1,
its own event_id, producer_id, occurred_at (UTC), and correlated arrival_id.
Retries preserve exact IDs and payload. The teammate owns recognition,
compatible-bay atomic reservation, sessions, matching and Supabase writes.
This repository contains no allocator or session writer.

Command ACK states are accepted, rejected, failed or unknown. Accepted is sent
only after the UNO's correlated acceptance, never merely after MQTT publish.
Pending duplicate commands wait for that result; completed duplicates return the
stored receipt without another gate cycle. Unknown execution requires review.

## Deployed isolation and ownership

Only isolated mirrors are enabled:

| Confirmed topic | Current isolated deployment |
|---|---|
| `parking/v1/arrival` | `parking/test/v1/arrival` |
| `parking/v1/gate/command` | `parking/test/v1/gate/command` |
| `parking/v1/gate/ack` | `parking/test/v1/gate/ack` |
| `parking/v1/gate/feedback` | `parking/test/v1/gate/feedback` |
| `parking/v1/gate/feedback/ack` | `parking/test/v1/gate/feedback/ack` |

Existing MQTT authentication/ACL already permits `parking/test/#`; production
permissions, credentials and routing are unchanged. Non-retained QoS 1 is used
by the backend. No real parking service is called. Mock acceptance uses a further
unique `parking/test/acceptance/<run>/` namespace with no session or database API
writes. Do not connect these test topics to real session persistence.

The existing :5001 isolated demo opts in with `PARKING_V1_ENABLED=yes`; startup
refuses that setting unless prefix is `parking/test`, bucket is `sensor_test`
and gate routing is isolated. The production :5000 backend remains unchanged.

## Foundation payloads

Arrival retains `schema_version`, `producer_id`, `occurred_at`, `arrival_id`,
`trigger` and `direction`, and includes its own `event_id`:

```json
{"schema_version":1,"event_id":"unique_arrival_message","arrival_id":"r_boot_cycle","producer_id":"sensor-gateway","occurred_at":"2026-11-27T08:00:00+00:00","trigger":"ultrasonic","direction":"entrance"}
```

Arrival IDs use `r_<UNO boot epoch>_<cycle>`. An exit has `direction:"exit"` and
a different cycle. IDs and the original serialized arrival payload persist in a
bounded SQLite test ledger. Retry interval is one second until 20 seconds from
the detector cycle start or an entrance command is recorded. Offline/old cycles
are not invented as new arrivals; current telemetry must be timely. Failure to
publish an exit does not delay the UNO's local exit simulation.

Entrance OPEN retains the existing command fields and adds explicit LCD/type
data. Additional teammate metadata fields are accepted and included in the
command fingerprint; the UNO receives only necessary normalized data.

```json
{
  "schema_version":1,"event_id":"unique_command_message",
  "arrival_id":"r_boot_cycle","command_id":"unique_command",
  "producer_id":"teammate","session_id":"TEST_ONLY_NO_SESSION_WRITE","decision_id":"TEST_DECISION",
  "occurred_at":"2026-11-27T08:00:01+00:00",
  "issued_at":"2026-11-27T08:00:01+00:00",
  "expires_at":"2026-11-27T08:00:06+00:00",
  "action":"OPEN","direction":"entrance",
  "license_plate":"TEST0001","lcd_plate":"TEST0001","vehicle_type":"sportcar"
}
```

Identity strings are 1–96 characters `[A-Za-z0-9:_-]`. UTC timestamps accept
RFC3339 `Z` or zero-offset form. New OPEN commands expire exactly five seconds after issued_at. The Python adapter verifies UTC with a small SNTP check against time.windows.com, refreshes every minute, and fails closed if verification is older than five minutes or the local clock jumps. It applies the measured offset without changing Windows time. Producer retries are one second until acknowledged or expired. Every new command must
match the current fresh entrance authorization wait and announced arrival.
Exit OPEN commands reject. If optional `authorized` is present it must be true.

Original `license_plate` is Unicode, 1–64 characters without controls/surrogates;
`lcd_plate` is separately supplied printable ASCII 0x20–0x7e, 1–16 characters.
No guessed transliteration. `vehicle_type` is car, sportcar or supercar.
Printable delimiters such as `|` are supported by hex encoding across UART.
Original plate text is kept only in the current in-memory dashboard projection;
neither original nor LCD plate is written into sensor Influx/cloud data or the
command ledger. No credentials/real plates belong in committed evidence.

Acknowledgements retain `ack_id`, `command_id`, `occurred_at` and `state`, with
`event_id`, `arrival_id`, `schema_version` and `producer_id`. `status` is an alias
of `state` for the isolated adapter, and `reason`/`physical_movement:false` make
simulation explicit. `accepted` requires the correlated UNO simulated-open/LCD ACK. `rejected` means refused before movement; timeout/restart is `unknown`. These receipts never confirm passage.

The SQLite ledger persists command ID, incoming event ID, arrival ID, canonical
payload fingerprint, wire token and receipt before forwarding. Same ID/content
returns the stored receipt, including after TTL expiry, without another OPEN.
ID/content conflict, reused event ID or a second command for one arrival rejects.
An interrupted pending execution becomes a new unknown receipt after restart;
it is never replayed. Missing UNO ack becomes unknown after five seconds. Each
ledger is bounded at 5,000 entries and fails closed when full; supervised ledger
maintenance is required. Accepted plate/session records are not archived here.

## Internal G3 path, separate from historical G2

UNO remains the existing integrated sketch and GateBench controller. Default
`GATE_ENTRANCE_EXIT_ENABLED=1`; `GATE_MANUAL_SERVO_ENABLED=0`. Building both enabled
is a compile error. SG90 remains disconnected and D9 is never attached.

Handshake is HELLO3 / S3 with a random 128-bit UNO epoch issued by ESP32. G3
telemetry reports epoch, uptime, U1/U2 distance/state, phase, lane, cycle,
vibration, reason, minimum-open and cycle-start time. ESP32 publishes it to the
private `parking/test/gate/v3/telemetry`; backend validates it and stores numeric
sensor fields separately as `parking_gate_v3` in local `sensor_test`. Existing
G2 measurements, historical U2 passages, environmental cloud synchronization
and old history queries retain their original semantics. G3 cloud export is
not silently added to the previously approved cloud schema.

Private backend-to-ESP32 control on `parking/test/gate/v3/control` carries the
matching UNO/gateway epochs, cycle, short wire token, sampled gateway-uptime
deadline, LCD hex and type. ESP32 revalidates epoch, cycle, entrance state,
queue generation and remaining deadline, then sends:

`C3|token|UNO_epoch|cycle|UNO_deadline|LCD_hex|vehicle_type`

UNO validates deadline/correlation/duplicate token, valid sensors and LCD before
simultaneously authorizing the simulated entrance and writing plate/type. It
responds `K3|token|ok`, duplicate or rejected. Private wire acknowledgements use
`parking/test/gate/v3/ack`; they are separate from the agreed passage feedback schema.

UTC expiry is checked on the PC. Gateway/UNO deadlines are calculated from
sampled uptime plus remaining TTL, so telemetry age and transport/queue delay
can only shorten a deadline; they cannot extend it. Each MCU checks modulo-safe
remaining time. Clock verification is required for remote entrance OPEN, while local exit safety remains independent of NTP.
UART retains 19200 baud, newline framing, bounded buffers, oversized-frame drain
and partial-frame timeout. UNO UART frame grows to 128 bytes; no JSON parser or
Unicode plate buffer is placed on the UNO.

GateBench retains one cycle, boot clear dwell, five-second minimum opening,
explicit correlated supervised bench confirmation, explicit CLOSE, obstruction/
unknown/opposite-lane holds and timeout/restart review. Neither timer expiry nor
ack confirms passage. Default sensor thresholds remain 15 cm detection / 18 cm
clearance. G3 publishes while boot/hold so unknown sensors are visible.

USB diagnostics and display-only rotating-nonce MQTT tests remain available;
SPORTCAR is supported. Display-only tests never authorize a cycle. The dashboard
shows a separate entrance/exit panel and correlated in-memory recognition while
preserving and labeling legacy G2 history. Session information is not fabricated.

Rollback: `b86e5eb` restores the prior integrated UNO/ESP32 and local-only bench
source. `8d3b445` is merged PR #4. Rebuild/upload the matching revision with servo
disconnected; source rollback alone does not restore flashed binaries. Set
PARKING_V1_ENABLED off/remove the demo opt-in to stop the adapter. No historical
measurement needs deletion or relabeling.


## Durable passage feedback

Feedback adds command_id (null for local exits), direction, state (opening,
completed, hold or failed), passage_confirmed (Boolean), simulation:true and
nullable reason. Completed is the exact terminal state. Only the existing
controller's R_COMPLETE after supervised CONFIRM, safe CLOSE and closing dwell
can produce completed with passage_confirmed:true; the backend must have observed
the matching same-epoch closing transition. Missing transitions/restart remain
uncertain and never invent passage. Timer expiry and command ACK are insufficient.

Feedback persists before publish in SQLite. Retries occur after 2,4,8,16,30 seconds,
then every 30 seconds, with unchanged event ID/payload. Pending messages survive
restart/reconnect and do not expire with OPEN. Feedback ACK requires the common
fields plus feedback_id equal to the original feedback event_id, matching
arrival_id, and state:"recorded". Only that receipt marks delivery recorded.
Unacknowledged messages remain pending; acknowledged records remain for audit.

Teammate lifecycle: pre-movement rejection cancels its reservation; uncertain
failure retains it for reconciliation. Exit release requires matched identity AND
completed confirmed passage for the same arrival_id, in either arrival order.
Unmatched exits remain in review. This adapter never releases a space itself.
Read-only session projection is not yet supplied and is not fabricated.

G3 reserves a 250 ms UART receive slot after reporting, and finishes partial
frames before triggering sonar. This prevents SoftwareSerial receive interrupts
from hiding ultrasonic echoes. Normal alternating 75 ms triggers resume after
the slot. Invalid measurements still cause immediate hold; no clearance is
inferred from skipped measurements. This scheduling change is local to G3.
