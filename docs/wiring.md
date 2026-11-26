# Working wiring — preserve connections

## Current gate assignment, 2026-11-26

The owner reports U1 D2/D3, U2 D4/D5, KY-002 D6 and I2C LCD A4/A5 connected
and diagnostic-tested. After the hardware correction, USB enumeration identifies
UNO COM7 (CH340, VID 1A86/PID 7523) and ESP32 COM10 (CH9102,
VID 1A86/PID 55D4). COM assignments can change; detect them before each upload.
UNO D10 RX connects to ESP32 GPIO26 TX. UNO D11 TX reaches ESP32 GPIO25 RX
through the corrected divider below. Both boards share signal ground.

The UNO sensors and ESP32 sensors now use **two separate breadboards and separate
sensor power circuits**, powered from their respective USB-connected boards.
Keep the positive power rails separate; retain the common signal ground.
The divider uses **three 1 kΩ resistors**: one upper resistor from UNO D11 to
the GPIO25 junction, and two series 1 kΩ resistors from that junction to GND
(2 kΩ lower leg). Nominal output is `5 V × 2/(1+2) = 3.33 V`.

```text
UNO D11 TX -- 1 kΩ --+-- ESP32 GPIO25 RX
                    |
                   1 kΩ
                    |
                   1 kΩ
                    |
                 common GND
ESP32 GPIO26 TX -------- UNO D10 RX
```

These wiring changes were completed manually by the owner. Verification work
does not modify wiring. See the current acceptance ledger for measured results.
New gate firmware uses **19200 inter-board baud and 115200 USB on both boards**.
ESP32 DHT22 GPIO4, LDR34 and MQ-2 35 remain unchanged. SG90 is disconnected,
D9 is unused, and suitable external servo power is unavailable. No rewiring or
servo output is authorized. Thresholds 15/18 cm and clear dwell 800 ms are
provisional pending physical calibration. KY polarity is unverified; its counter
is sampled transitions, not calibrated vibration events.

The following table/text is retained as historical pre-gate wiring evidence; it
does not describe the newly owner-reported U2/KY/LCD installation.

Disconnect power before changing physical wiring. No rewiring is needed for the native Windows deployment.

| Board | Device / function | Connection |
|---|---|---|
| UNO | HC-SR04 A1 TRIG / ECHO | D2 / D3 |
| UNO | HC-SR04 power | 5V / GND |
| UNO | Future HC-SR04 M1 | D4 / D5 reserved; disabled |
| UNO | Future KY-002 vibration | D6 reserved; not installed |
| UNO | Future servo | D9 reserved |
| UNO | UART RX / TX | D10 / D11, 9600 baud |
| UNO | Future I2C LCD | A4 / A5 reserved |
| ESP32 | DHT22 signal | GPIO4 |
| ESP32 | LDR analog | GPIO34 |
| ESP32 | MQ-2 analog | GPIO35 |
| ESP32 | UART RX / TX | GPIO25 / GPIO26, 9600 baud |
| ESP32 | USB debug | 115200 baud |

UNO D11 TX reaches ESP32 GPIO25 RX through the existing voltage divider. Both boards share GND. ESP32 GPIO26 TX is configured but physically unconnected. Preserve the existing sensor power and analog voltage conditioning; do not connect a 5V output directly to an ESP32 pin.

M1 and vibration remain disabled. UNO M1 fields are null; vibration fields are null and status is `not_installed`. Raw MQ-2 readings are unconditioned/uncalibrated and not gas concentration measurements. Existing working UNO and original ESP32 source are retained.
