# Integration v1 proposal — awaiting teammate agreement

No endpoint/topic in this document is implemented unless marked existing. Do not treat examples as an agreed API. Coordination thread: [issue 1](https://github.com/ananyaknr/iot-parking-dashboard/issues/1#issuecomment-7182268863).

## Ownership and flow

Proposal: teammate local recognition/decision service owns capture, classification, OCR, bay selection, atomic reservation, matched exit, and session/photo persistence. Our service reports availability and executes an authorized, unexpired gate command after hardware safety checks. Only one decision engine may reserve bays. Fresh vacant availability is a sensor observation, not proof a bay remains unreserved.

1. Dedicated entrance detector or operator action creates arrival ID. In-bay occupancy does not trigger capture. Owner, detector and debounce interval require agreement.
2. Teammate deduplicates arrival ID, captures one still, recognizes/reviews it, reserves an eligible matching bay atomically or matches an exit session.
3. Teammate issues gate command with a stable ID, arrival/session correlation, short expiry and authorization. Our executor acknowledges receipt and reports hardware outcome separately.
4. Teammate archives photos and session changes asynchronously, exposes a dashboard projection; cloud failure never grants a gate command or blocks local sensor monitoring.

## Proposed transport and envelopes

Use local authenticated MQTT for arrival/command/ack, with distinct credentials and exact-topic ACLs; non-retained QoS 1 requires application deduplication. Use authenticated loopback HTTP for availability and session projection; cross-machine exposure requires agreed TLS/access controls. Proposed topics: `parking/v1/arrival`, `parking/v1/gate/command`, `parking/v1/gate/ack`. They are deliberately absent from deployed and candidate ACL permissions until agreement.

Every event: `schema_version: 1`, unique `event_id`, `occurred_at` as UTC RFC3339, `producer_id`, and correlation IDs. Reject unsupported versions, oversized/malformed messages, retained control events and expired commands. MQTT authentication identifies the allowed publisher; payload names alone do not authenticate it. Devices need an agreed trusted clock or server-issued deadline before expiry can be enforced safely.

| Contract | Fields / semantics | Ownership / failure behavior |
| --- | --- | --- |
| Arrival | `arrival_id`, `trigger` (`operator` or agreed detector), `occurred_at`, direction if explicitly known; never infer entry/exit from bay occupancy | Ours produces; teammate captures once per ID. Persist dedup ledger across reconnect/restart; expiry/debounce/retention to agree. |
| Availability | **Existing** `/api/latest` provides `sources.uno` fields `fresh`, `payload_valid`, `a1_state`, `a1_allocation_eligible`, `m1_installed`, `m1_allocation_eligible`, `last_received_utc`, age | Ours observes only. Teammate must exclude stale/unknown/uninstalled bays, validate snapshot age at reservation, and arbitrate concurrent arrivals atomically. Proposed v1 projection can add `snapshot_id`, `expires_at`, per-bay observation timestamps; not implemented. |
| Reservation | Decision service owns reservation token, bay, arrival, TTL, commit/release and compare-and-set semantics | Teammate proposal; no reservation writes in this repository. Agree refresh/invalidation if occupancy changes or network fails. |
| Gate command | `command_id`, `arrival_id`, `session_id`, action `OPEN`, `issued_at`, `expires_at`, decision/reservation correlation | Teammate authorizes; ours validates/executes only. Repeated same ID/same command returns recorded outcome; same ID/different content rejected. Persist command ledger before movement. Never turn retry into a new OPEN. |
| Gate ack | `ack_id`, `command_id`, `occurred_at`, state `accepted`, `executed`, `rejected`, `failed` or `unknown`, sanitized reason | Ours produces; `accepted` does not establish physical opening. Without position feedback, do not claim observed servo/gate position. Decision service times out to review. Timeout/restart semantics must not replay movement. |
| Session dashboard projection | `schema_version`, `session_id`, monotonic `revision`, `vehicle_type` (`car`, `motorcycle`, `unknown`), `license_plate` nullable, `status` (`still_in`, `left`), `entered_at`, nullable `exited_at`, private `photo_ref` | Teammate owns storage/matching/API. Dashboard ignores older revisions, keys updates by session ID, renders plate as text, displays UTC in configured lot-local time. No public photo URL, raw HTML or cloud credentials in client. |

## Questions requiring agreement before implementation

- Confirm teammate orchestration ownership, transport endpoints, source authentication, message size/rate limits, clock sync and supported versions.
- Select operator versus dedicated detector arrival source, direction and physical debounce; agree duplicate ledger lifetime and capture retries.
- Agree atomic reservation/TTL/release and two simultaneous arrivals competing for one bay; no independent allocator here.
- Agree servo pin/wiring/power, safe closed behavior, obstruction handling, emergency/operator override, command TTL, acknowledgement timeout and restart interlock. No automatic movement until user-approved hardware acceptance.
- Agree session projection retrieval/push, revision ordering, retention, operator permissions and authenticated same-origin photo proxy/access. Dashboard must not fetch arbitrary untrusted photo URLs or persist teammate records as a second archive.
- Agree legacy `parking/camera/result` deprecation date and third-source rubric evidence. Keep its validation and advisory display working until replacement is accepted; no per-slot state refactor.

## Joint acceptance plan (all pending)

| Scenario | Expected evidence |
| --- | --- |
| Entry / matched exit | One arrival/capture/command, appropriate reservation or match, same stable session ID, UTC entry then exit, local-time dashboard |
| Full matching bay or unknown/M1 unavailable | No unauthorized open or reservation; operator-visible refusal |
| Unreadable plate / unknown class | Review path, no automatic open |
| Duplicate arrival / command, concurrent arrivals | One capture/movement per ID, one atomic reservation, replay ledger survives restart |
| Sensor stale/disconnect/change after selection | Bay excluded, reservation cancelled/revalidated under agreed policy |
| Ack lost, executor restart or servo fault | Outcome unknown/review, no blind replay; physical feedback limits stated |
| Cloud outage and delayed archive update | Local control/monitoring continues, bounded retries, completed session never overwritten by older revision |

First run isolated mocks in a separate namespace/bucket with no hardware movement, then user-approved connected hardware tests. Mark mock, software and physical evidence separately.
