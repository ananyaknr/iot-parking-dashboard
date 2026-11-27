# Entrance/exit integration — proposed v1 extensions

Status: **awaiting teammate confirmation; not an enabled interface**.
Prepared 2026-11-27 for `feature/parking-full-integration`, based on merged
PR #4 (`8d3b445`). This document proposes exact payloads for review; it does
not claim to reproduce an existing agreed teammate contract.

## Readiness and ownership

The owner superseded U1-arrival/U2-passage with U1-entrance/U2-exit. Historical
schema 2, G2 frames, arrival/passage IDs, Influx measurements and evidence retain
their original meaning. Proposed new telemetry uses schema 3,
`mode=entrance_exit_sim`, G3 framing and distinct measurements/IDs. The shared
MQTT envelope remains v1 with an explicit contract revision. Do not feed G3 into
the G2 validator or relabel stored U2 passage points as exits.

Read-only inspection of teammate repository
[`1058ed1b8c6741266c6430b090f3b2ec7014a74f`](https://github.com/vvryw/intelligence-parking-lot/tree/1058ed1b8c6741266c6430b090f3b2ec7014a74f)
found only `main`, no issues, HTTP camera/parking simulation and an A1/M1 sensor
bridge. Its [integration document](https://github.com/vvryw/intelligence-parking-lot/blob/1058ed1b8c6741266c6430b090f3b2ec7014a74f/docs/sensor-dashboard-integration.md)
calls gate MQTT a future interface. No six-topic `parking/gate/*` payload
implementation or agreement was found. Its simulated commit currently releases
an exit session before physical passage feedback; a teammate-side change is
needed for the requested workflow. We must not modify that persistence here.

Teammate owns recognition, typed availability, atomic reservations, sessions,
matching, Supabase and photos. No A1/M1 availability feed is an integration
requirement. Preserve historical sensor APIs, but do not send gate readings to
the teammate's old bay mapping script.

Owner agreed supervised bench passage confirmation and simulated movement in
this sprint. External servo power/wiring/movement confirmation is absent. Keep
D9 unused, Servo unattached, existing separate breadboards and corrected
1 kΩ upper / 2 kΩ lower UART divider intact. No new clearance sensor is assumed.
Both approach detectors becoming clear does not prove passage through a barrier.

## Proposed exact MQTT revision for agreement

All examples are synthetic; `TEST0001` is a fixture. Use authenticated exact-topic
permissions, UTF-8 JSON, non-retained messages, maximum 2048 bytes. Reject retained,
duplicate JSON keys, nonfinite values, unsupported versions and invalid types.
Every payload has `schema_version:1`, `contract_revision:"entrance-exit-1"`,
`event_id`, `lane` (`entrance` or `exit`) and `occurred_at` (UTC RFC3339).
Event identity is `v3:<128-bit-boot-hex>:<lane>:<counter>`, stable for all retries.
Transport retries are allowed; one logical detector event causes one capture.
Production topics below become `parking/test/gate/*` and
`parking/test/camera/result` during tests. Synthetic data never uses production
topics, buckets, sessions or Supabase records.

| Topic | Producer → consumer | Additional required fields |
|---|---|---|
| `parking/gate/arrival` | Gateway → teammate | `detector` (`U1` for entrance, `U2` for exit), `expires_at`, `simulation:true` |
| `parking/gate/arrival_ack` | Teammate → gateway | `status` (`accepted`, `duplicate`, `rejected`), `reason` (bounded code) |
| `parking/gate/command` | Teammate → gateway | `command_id`, `action:"OPEN"`, `authorized:true`, `issued_at`, `expires_at`, `license_plate`, `lcd_plate`, `vehicle_type`, `session_id` |
| `parking/gate/feedback` | Gateway → teammate | `feedback_id`, nullable `command_id`, `status`, `reason`, `passage_confirmed`, `confirmation_source`, `simulation:true`, `physical_movement:false` |
| `parking/gate/feedback_ack` | Teammate → gateway | `feedback_id`, `status` (`accepted`, `duplicate`, `rejected`) |
| `parking/camera/result` | Teammate → dashboard backend | `result_id`, `license_plate`, nullable `lcd_plate`, `vehicle_type`, `status` (`recognized`, `review`, `failed`), nullable `session` |

Command IDs and feedback/result IDs are unique bounded ASCII identifiers, 1–64
characters `[A-Za-z0-9_-]`. Entrance commands require `lane:"entrance"` and a
currently waiting matching event. Exit commands are rejected: U2 opens the local
simulated exit cycle without camera authorization. Exit feedback has
`command_id:null`; do not invent a remote command ID.

Example entrance OPEN (timestamps are fixtures, never replay these):

```json
{
  "schema_version": 1, "contract_revision": "entrance-exit-1",
  "event_id": "v3:0123456789abcdef0123456789abcdef:entrance:1",
  "lane": "entrance", "occurred_at": "2026-11-27T07:00:01Z",
  "command_id": "test_cmd_1", "action": "OPEN", "authorized": true,
  "issued_at": "2026-11-27T07:00:01Z", "expires_at": "2026-11-27T07:00:06Z",
  "license_plate": "TEST0001", "lcd_plate": "TEST0001",
  "vehicle_type": "car", "session_id": "test_session_1"
}
```

`license_plate` preserves original Unicode (1–64 characters, no controls).
`lcd_plate` is a separately supplied ASCII fallback, 1–16 printable characters
from `[A-Za-z0-9 -]`. No guessed transliteration. Require both on an entrance
OPEN; deliver LCD plate and type atomically with local authorization. Vehicle
types are `car`, `sportcar`, `supercar`, `unknown`; unknown never authorizes.
The previous firmware's omission of `sportcar` must be addressed explicitly.
Never put real plates in committed logs or sensor cloud measurements.

## Local execution and reliability proposal

One shared barrier has one active cycle. Simultaneous detections or an opposite
lane detection during an active cycle produce a busy/review outcome; no second
OPEN or silent queued movement. After recovery require clear detectors and a new
debounced edge, so a vehicle held in a detection zone cannot generate repeated
cycles. Teammate must handle busy outcomes without treating them as passage.

Entrance waits up to 20 seconds for a matching valid OPEN. Exit starts locally
and publishes its event in parallel; network failure cannot make it wait for OCR.
Opening starts a configurable minimum-open timer (proposed default 5000 ms),
using unsigned millis differences, without blocking environmental/UART work.
Closing requires both minimum duration and an event-correlated operator
`CONFIRM_PASSAGE` for this supervised simulation, followed by valid sustained
clearance (proposed 800 ms). Confirmation before opening is rejected. Neither
minimum-open expiry, detector clearance, MQTT ack nor UART ack establishes
passage. Unknown echoes, obstruction, cycle timeout or restart enter hold/review
with no automatic forced close. Proposed cycle timeout is 120 seconds for bench
movement. Closing obstruction cancels closing; successful close remains labeled
simulated, never a measured physical position.

Feedback statuses: `accepted`, `opening`, `awaiting_passage`, `completed`,
`rejected`, `hold`, `unknown`. Only `completed` may contain
`passage_confirmed:true`, `confirmation_source:"supervised_bench"` in this
simulation. All others use false/null. On exit, teammate releases only its
matched session after terminal confirmed feedback. Uncertain OCR/matching stays
review, even when passage is confirmed. Gate completion itself cannot choose a
space or session. Teammate must explicitly agree that bench confirmation can
complete **isolated simulation** sessions; it is not real vehicle evidence.

Commands require trusted UTC, `issued_at <= now+1s`, `now < expires_at`, and a
maximum proposed TTL of 5 seconds. No trusted clock means no entrance OPEN.
Carry only the remaining local deadline to UNO; recheck after queueing/UART.
Reject stale generations after reconnect. Reuse bounded UART newline framing,
oversize drain and 500 ms partial-frame timeout under a distinct G3 protocol.

Persist accepted command ID plus payload fingerprint before execution; exact
retries return recorded status, conflicts reject. New ID for an already consumed
event cannot reopen it. After reset never replay an uncertain action: report
unknown/review and require supervised recovery. Arrival/feedback retry ledgers
are bounded, retain original IDs/timestamps, stop on ack or expiry and report
exhaustion. Proposed retry interval 1 second, event TTL 20 seconds, terminal
feedback retention 24 hours, dedup retention 7 days; full ledger fails closed.
Acknowledging delivery must not acknowledge successful passage/session release.

## Read-only dashboard projection

Proposed `session` fields: `session_id`, monotonic `revision`, `status`
(`still_in`, `left`, `review`), `vehicle_type`, `entered_at`, nullable `exited_at`,
nullable `space_id`. Read-only teammate projection, bounded in-memory cache with
freshness and older revision rejection; no session/Supabase writes. No arbitrary
photo URLs. Render original Unicode plates using textContent, with ASCII LCD
delivery and latest gate outcome displayed separately. Preserve all existing
environmental and historical charts and legacy schema labels.

## Acceptance and activation checklist

- [ ] Teammate confirms exact payloads, types, IDs, expiry/clock, retries/acks,
  isolated test namespace, dedup persistence and supervised confirmation semantics.
- [ ] Teammate confirms revised matched-exit release after terminal feedback,
  and read-only session projection; no A1/M1 sensor dependency.
- [ ] Implement distinct schema, serialized UNO cycles, ESP32 MQTT/UART and LCD.
- [ ] Focused tests: entrance allow/deny/full/expiry; automatic exit without
  command; unknown identity; minimum-open and explicit confirmation; simultaneous
  lanes; obstruction/no echo; duplicate/conflicting/stale/retained commands;
  restart/reconnect; Unicode/ASCII and sportcar; old history remains unchanged.
- [ ] Build both boards and perform supervised servo-disabled bench acceptance,
  real isolated MQTT/local history/dashboard readback and teammate session checks.
- [ ] Record actual receipts; update README/Issue #1 and PR; owner reviews migration.

Rollback: merged PR #4 source is `8d3b445`; retain its exact sketches and
`firmware/gate_common` before uploads. Rebuild/upload that revision using the
previous board settings if needed, restore its isolated demo routing, and keep
new schema histories separate. A Git rollback alone does not restore flashed
firmware. No production configuration changes or new firmware uploads have been
made during contract readiness.
