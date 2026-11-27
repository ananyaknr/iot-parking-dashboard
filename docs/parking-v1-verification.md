# PR #5 verification — 2026-11-27

Implementation continues from b86e5eb on feature/parking-full-integration.
All gate tests use isolated parking/test topics and a separate SQLite ledger.
SG90 is disconnected; physical output is compile-disabled. No real plates,
parking sessions, allocations, teammate repository or Supabase records are used.

## Actual results

- Owner manually recovered wiring without firmware changes: U1 9.7 cm,
  U2 10.4 cm, LCD=1, UART_SESSION=1, UART_FRAMES=1. ESP32 reported
  temperature 25.3 C, humidity 63.3%, light 1057 and gas 500.
- Fresh observation at 09:28 UTC received 12 G3 and four environmental messages
  in 12 seconds. Both U1/U2 readings and separate schema=3 reached the dashboard.
- Native broker, local storage and environmental cloud uploads are active.
  Production :5000 remains independent; isolated :5001 uses sensor_test.
- Chrome check at 09:30 UTC passed: six history charts, fresh G3, disabled
  servo, enabled feedback adapter, no JavaScript errors. Screenshot is local
  .runtime/parking-v3-dashboard.png; sanitized receipt is committed beside this doc.
- Eleven focused Python contract tests passed: all three vehicle types,
  Unicode/ASCII LCD encoding, duplicate/conflicting IDs, exact five-second expiry,
  full-category absence of OPEN, automatic exit messages, no-echo safety,
  pending-command restart => unknown/no replay, controller acceptance before ACK,
  feedback backoff, lost ACK/restart recovery and correlated recorded receipts.
- Existing native C++ GateBench, G3 wire and legacy core tests passed. These cover
  authorized entrance, local automatic exit, five-second minimum, explicit
  confirmation, obstruction, serialization, timeout and millis wrap.
- Actual authenticated broker test at 09:30 UTC passed with mock teammate/gateway:
  duplicated entrance command produced one internal control; Unicode/sportcar
  delivered; exit arrival required no OPEN; direction/expiry rejected; feedback
  persisted and received its correlated recorded application acknowledgement.
- Earlier history readback passed for local environmental, local historical G2
  and isolated cloud G2. No historical U2 passage is relabeled as exit.

## Firmware build and deployment receipts

The existing integrated sketch was extended, never the temporary servo sketch.
UNO upload verified on COM7; ESP32 necessary G3 adapter upload hash verified on
COM10. Recovered live G3/environmental telemetry proves both are running.

| Build | Flash | Static RAM | SHA256 of uploaded artifact |
|---|---:|---:|---|
| UNO hex | 21,922 / 32,256 | 1,499 / 2,048 | A4EC6697002312B99DA459B453F8F73503A22E39EB2D25CE643F3ED0378C45BA |
| ESP32 bin | 1,004,921 / 1,310,720 | 50,976 / 327,680 | 730B337B78B3161FCDD83D89E1F9840191E7BE84C6F15AD63F414B5D9FADF7A0 |

UNO leaves 549 bytes SRAM; no JSON/Unicode parser or dynamic String was added.
Servo uses Timer1 only if attached; this build never attaches it. Vibration uses
Timer2, preserving SoftwareSerial PCINT ownership. Existing timer tests and
actual UART session are retained evidence; unloaded standalone servo motion
does not prove combined power stability.

During initial ESP32 development, a missing return in receiveV3 caused an abort;
it was fixed before the final hash-verified upload. Final firmware also delays
HELLO3 response 5 ms for SoftwareSerial turnaround and bounds TCP connection
attempts. The final UNO upload additionally reserves a 250 ms receive slot after each G3 report and drains partial UART frames before ultrasonic measurement. This addresses a reproduced no-echo collision during long C3 reception, without changing unknown/obstruction hold rules. Python feedback/clock changes require no ESP32 upload.

Windows Time was stopped. An independent time-server probe measured about
2.4 seconds clock offset. The adapter now verifies/corrects its own UTC using
SNTP without changing Windows time and refuses new OPEN when unverifiable.
The running adapter reports clock_verified=true.

## Live acceptance limits and remaining work

A real U1 arrival reached the backend and correlated test OPEN reached the UNO.
U1 lost echo while the target was moved, so the controller safely held and
rejected OPEN; feedback state=hold, passage_confirmed=false. This is an actual
safety-path receipt, not a successful opening or completed passage.

The UART receive-slot fix was then uploaded and live acceptance succeeded:

- Entrance at 09:45 UTC: U1 detection, arrival, duplicated synthetic OPEN,
  one accepted cycle, LCD TEST0001/sportcar visually confirmed by owner.
  Owner explicitly confirmed simulated passage with both zones clear;
  CONFIRM|1 and CLOSE produced closed/R_COMPLETE at 09:47 UTC and terminal
  completed feedback with passage_confirmed:true and the matching command_id.
- Exit at 09:47 UTC: U2 started local simulated OPEN, correlated exit arrival,
  zero remote commands and command_id:null. Owner explicitly confirmed passage;
  CONFIRM|2 and safe CLOSE produced completed/passage_confirmed:true at 09:49 UTC.
- Both cycles retained minimum_open_ms=5000, servo_enabled:false. Neither cycle
  inferred passage from the timer, command ACK or OCR. Actual receipts are in
  docs/evidence/parking-v1-20261127.
- Backend restart with seven unacknowledged feedback messages passed at 09:50 UTC:
  all seven reappeared with identical payloads, including opening/hold/completed.
  The isolated mock recorder acknowledged them with matching recorded receipts;
  pending queue became zero. No parking sessions were written.
- Final check at 09:51 UTC: both sensors clear, controller closed, fresh G3 and
  environmental telemetry, verified UTC, broker/storage connected, pending
  feedback zero. Production cloud counter reached 923 with zero pending;
  isolated cloud upload also advanced after restart. Chrome/history recheck passed.

Joint camera/reservation/full-category policy and matched/unmatched-session
release tests require the teammate's test service. Mock protocol tests do not
verify teammate persistence. This repository intentionally never releases bays.
Live simulated LCD/open/close/passage acceptance is now observed and explicitly
confirmed as described above. Physical movement remains untested/disabled.
Do not merge PR #5 automatically.

Rollback remains b86e5eb (prior integrated restoration) or merged PR #4 8d3b445.
Rebuild and upload the matching UNO/ESP32 revision with servo disconnected;
flashed devices are not rolled back merely by checking out source. Disable
PARKING_V1_ENABLED to stop the shared adapter. Retain SQLite for pending receipts;
do not delete it to silence unacknowledged feedback.
