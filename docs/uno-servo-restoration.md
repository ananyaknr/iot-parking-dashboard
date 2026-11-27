# Integrated UNO restoration and supervised servo preparation

2026-11-27, PR #5, `feature/parking-full-integration`.

The owner reported that a temporary standalone SG90 diagnostic replaced the
integrated UNO sketch and passed unloaded USB-powered movement. This work starts
from the repository's verified `uno_gate_sim.ino`, not that temporary sketch.
Owner confirmed the servo was disconnected before uploading. Combined-system
servo power/stability remains unverified. ESP32 firmware is unchanged.

## Build and physical-output boundary

`GATE_MANUAL_SERVO_ENABLED` defaults to **0**. The uploaded build never attaches
D9. It starts detached and never commands a boot position. Automatic physical
actuation has no implementation path, including in a manual-enabled build.
The Servo library is present for future explicitly supervised manual use.

Mapping: U1 D2/D3; U2 D4/D5; KY-002 D6; SG90 D9; SoftwareSerial RX D10/TX D11;
I2C LCD A4/A5. Preserve separate breadboards and corrected UART divider. Do not
reconnect the servo for integrated operation using the UNO USB rail based on
the earlier unloaded standalone result.

Timer/source review: Arduino Servo 1.3.0 selects Timer1 on ATmega328P; vibration
uses TIMER2_COMPA; Arduino millis uses Timer0; SoftwareSerial owns PCINT.
Both build variants link without ISR collisions. SoftwareSerial masks interrupts
during bit timing and can delay servo edges and vibration samples. The existing
19200-baud framing, partial-frame timeout and bounded ultrasonic pulseIn calls
are retained; pulseIn can still occupy up to 25 ms. Gate timing itself uses
millis without servo delays. Compile success does not establish pulse quality,
power stability or reliable simultaneous physical operation. See the
[official Servo timer selection](https://github.com/arduino-libraries/Servo/blob/1.3.0/src/avr/ServoTimers.h).

## Modes and commands

Default boot restores the unchanged G2 handshake, historical arrival/passage
simulation, LCD commands, vibration sampling and UART telemetry expected by the
existing ESP32/backend/cloud/dashboard. That behavior is preserved for rollback
and is **not** presented as the revised entrance/exit workflow.

USB `LOCAL` selects an explicit local entrance/exit bench controller. It suspends
G2 gate telemetry and incoming remote display/authorization commands for that
boot, preventing entrance/exit cycles from being archived as legacy U2 passages.
The ESP32 environmental loop remains independent. New BENCH3 status is USB-only;
it is not an agreed MQTT protocol or a new dashboard feed. Reset/reboot restores
G2 and obtains a new boot epoch; there is no hot switch merging event counters.
Full new-schema MQTT/dashboard delivery remains pending teammate agreement.

In LOCAL, both detectors must become valid and clear for 800 ms before ready.
U1 starts an entrance authorization wait; U2 starts a local simulated exit opening
without authorization. Simultaneous/opposite-lane detection holds for review.
There is one cycle at a time. Unknown echo, timeout or closing obstruction holds;
no timeout forces closure or confirms passage. Every CLOSE needs matching
supervised confirmation, valid sustained clearance and at least five seconds
since opening. Closing is explicitly commanded; elapsed time alone never starts
it. A 500 ms simulated closing interval ends the logical cycle, not measured
physical position. A new close-to-clear recovery is required after faults.

USB is 115200 baud, newline terminated. Send one command at a time; do not paste
multiple commands while SoftwareSerial is transmitting. UART remains 19200.

| Command | Behavior |
|---|---|
| `SENSORS?` | Distances (`-1` means no echo), LCD discovery and UART session flag |
| `VIB?` | Retained raw/min/max/sampled-transition diagnostic |
| `STATUS` | BENCH3 cycle, lane, phase, reason and output flags; it does not select LOCAL |
| `LOCAL` | Select independent local bench; no movement; may refuse an active legacy cycle |
| `ANGLES\|80\|100` | Set volatile closed/open degrees while detached and not opening/closing; example calibration range only |
| `MINIMUM\|5000` | Set 5000–60000 ms while local controller is closed and servo detached |
| `ARM` | LOCAL only; refuses in uploaded build. In enabled build, requires closed/clear; does not attach |
| `OPEN` | LOCAL only, closed/clear; starts manual cycle. Simulated in uploaded build; only explicit armed manual OPEN can attach D9 |
| `ALLOW\|<cycle>` | LOCAL simulated entrance authorization within 20 s; exact active cycle required; never drives servo |
| `CONFIRM\|<cycle>` | Explicit supervised bench passage confirmation after opening; exact cycle required |
| `CLOSE` | Refused until confirmation, minimum-open time and clear dwell; drives only an already armed manual movement |
| `STOP` | Detach immediately, disarm and hold; position unknown, no mechanical emergency-stop claim |
| `RESET` | LOCAL hold recovery only while detached and detectors clear; boot dwell required again |
| `LEGACY` | Prints reboot instruction; does not switch counters or reset automatically |

Lane numbers: 0 none, 1 entrance, 2 exit, 3 manual. Phase numbers: 0 boot,
1 closed, 2 authorization wait, 3 open, 4 closing, 5 hold. Cycle IDs are local,
volatile and never represent a parking session. Bench ALLOW is not camera
authorization. No availability, reservation, OCR, Supabase or session writes
were implemented. Original Unicode/ASCII shared recognition delivery remains in
the pending [contract proposal](parking-full-integration-contract.md).

## Actual results

| Check | Result |
|---|---|
| Port identity | CH340 COM7, consistent with previously verified UNO; no ESP32 USB device detected in this check |
| Default build | PASS: AVR 1.8.8, Servo 1.3.0, 20,178/32,256 flash, 1,450/2,048 static RAM, 598 bytes stack/locals margin |
| Manual-enabled build, compile only | PASS: 20,246 flash, 1,450 static RAM; not uploaded |
| Output-disabled upload | PASS on COM7 with `--verify`; initial attempt failed because Arduino Serial Monitor held port; owner closed it and retry succeeded |
| Final HEX SHA-256 | `4a700de3fa76f4cd55562f054ca8b66719e22955707adccd332046dab8caccff` |
| Legacy C++ regression | PASS: existing cycle, debounce, clearance, obstruction, unknown, timeout/wrap, authorization and framing assertions |
| New controller C++ regression | PASS: authorized entrance, local automatic exit, minimum-open/confirmation, serialization, conflicting lanes, obstruction/no echo, auth expiry, rollover |
| Live USB status | `servo=0`, `automatic_physical=0`, `minimum_ms=5000` |
| Live sensor diagnostic | U1=-1.0, U2=-1.0, LCD=1, UART_SESSION=0: I2C device discovered, both no echo, no ESP32 handshake |
| Live vibration at rest | raw/min/max=1/1/1, transitions=0; no new physical tap acceptance |
| Serial continuity | Diagnostic reader then reported port closed unexpectedly; sustained USB stability not established |
| Native services | Existing startup restored broker/Influx/backend. Initial Python loopback request hit inherited proxy HTTP 503; scoped NO_PROXY for localhost/127.0.0.1/current LAN resolved it; no credentials changed |
| Dashboard APIs :5000/:5001 | MQTT and storage connected; production routing off, demo isolated; all hardware sources stale/no received samples at checkpoint |
| Cloud | Existing configuration enabled, no reported error, zero new uploads at checkpoint; fresh cloud readback not established |
| Actual new servo/LCD visual/sensor/UART acceptance | Pending connected hardware and owner observation; compilation and old evidence do not substitute |

Follow-up after owner reconnected ESP32: owner visually confirmed the integrated
LCD screen. Both APIs received environmental samples through 07:42:17 UTC, then
reported them stale at the next check; cloud counters advanced to four production
and three isolated uploads (one isolated pending). This establishes some new
delivery, not sustained live operation or independent cloud value readback.
UNO diagnostics initially returned both no echo and UART_SESSION=0; the final
sample in that capture recovered U1=8.4 cm while U2 remained no echo and UART
remained unestablished. A startup banner
reappeared during the capture; a reset/reconnect occurred, but its cause was not
established. Owner was asked to check existing power/UART and position clear
20–40 cm targets with servo disconnected. No automatic physical output or ESP32
reflash was used to try to resolve this hardware-dependent condition.

At 07:41:34 UTC, read-only 24-hour archive API queries passed: production
temperature history 601 windows/19 populated, isolated local U1 history 601/9,
isolated cloud U1 history 601/9. These are historical values, not current sensor
acceptance. Both dashboards retain their original source/history routing.

The first draft consumed 1,664 static bytes and left only 384 bytes. Moving bench
reason/command text to flash, reducing the USB-only frame to 48 bytes and removing
a 96-byte parser stack copy improved the final margin. No heap allocation was
added. The margin is not a measured worst-case stack proof or long-duration
stability result. UART frame remains 96 bytes. Only the small standard Servo
library was added to the local toolchain; no heavyweight dependency or ESP32
source change was needed. Old Python/cloud/browser regression evidence is reused
because those implementations were unchanged.

Latest check after owner verified power/connections and placed targets around
10 cm: at 07:45:42 UTC ESP32 environment was fresh/valid on both dashboards;
cloud counters reached 32 production/31 isolated uploads, with 3/4 pending.
UNO read U1=8.3 then 9.8 cm; U2 remained no echo, UART_SESSION=0, LCD=1,
rest vibration unchanged. Environment delivery resumed at this checkpoint;
U2 and bidirectional UART remain blocked. A 10 cm target is valid detection,
not clearance; limited bench space does not justify lowering the 18 cm
clearance threshold or treating no echo as clear.

## Supervised calibration after suitable power confirmation

1. Keep servo disconnected until the owner confirms suitable regulated external
   power, common ground, safe signal wiring, free travel and supervised movement.
   First verify stable UNO/ESP32 sensors/UART with no servo load.
2. Only after that confirmation, explicitly build/upload the manual-enabled
   variant using `--build-property compiler.cpp.extra_flags=-DGATE_MANUAL_SERVO_ENABLED=1`.
   Automatic physical actuation stays disabled. The current disabled build cannot
   be enabled by a serial command.
3. With linkage disengaged and both sensors clear, select LOCAL. Wait for ready,
   choose a narrow unloaded range such as `ANGLES|80|100` rather than assuming
   default 10/80 are safe endpoints. These are configurable trial values, not
   calibrated physical angles. Send ARM, then OPEN only under supervision.
4. Observe travel/current/power and serial/UART behavior. Send STATUS; after at
   least five seconds, explicitly CONFIRM its cycle, then CLOSE when clear.
   STOP detaches but does not hold a falling barrier mechanically.
5. Disconnect servo power before changing wiring/linkage. Reboot/disarm, adjust
   endpoints gradually while detached, and repeat only the necessary supervised
   cycles. Confirm no binding, brownouts, jitter, missed UART or false vibration
   before considering an integrated physical trial. No automatic physical mode
   is enabled by these steps.

Rollback: rebuild/upload merged `8d3b445` UNO sketch plus its `gate_common` library
using the recorded UNO configuration, with servo disconnected. Keep ESP32 as is.
No legacy history is rewritten; source rollback does not itself restore flash.
