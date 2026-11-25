#include <Arduino.h>
#include <SoftwareSerial.h>

// Adjust each pair after measuring the actual parking slot.
// These are provisional bench-test thresholds, in cm.
const float A1_ENTER_CM = 15.0f;
const float A1_LEAVE_CM = 18.0f;
const float M1_ENTER_CM = 15.0f;
const float M1_LEAVE_CM = 18.0f;
// Set true only after installing the second HC-SR04 on D4/D5.
const bool M1_SENSOR_ENABLED = false;
const uint8_t A1_TRIG = 2, A1_ECHO = 3;
const uint8_t M1_TRIG = 4, M1_ECHO = 5;
const unsigned long SAMPLE_INTERVAL_MS = 1000;
const unsigned long ECHO_TIMEOUT_US = 30000;
SoftwareSerial gateway(10, 11); // RX, TX; connect in Phase 3 only

enum Occupancy { UNKNOWN, VACANT, OCCUPIED };
Occupancy a1State = UNKNOWN, m1State = UNKNOWN;

float readDistance(uint8_t trig, uint8_t echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);
  unsigned long duration = pulseIn(echo, HIGH, ECHO_TIMEOUT_US);
  if (duration == 0) return -1.0f;
  float cm = duration * 0.0343f / 2.0f;
  return (cm >= 2.0f && cm <= 400.0f) ? cm : -1.0f;
}

// Require at least two valid samples; median of three or mean of two.
float filtered(float *values) {
  float valid[3];
  uint8_t n = 0;
  for (uint8_t i = 0; i < 3; ++i) {
    if (values[i] >= 0.0f) valid[n++] = values[i];
  }
  if (n < 2) return -1.0f;
  if (n == 2) return (valid[0] + valid[1]) / 2.0f;
  for (uint8_t i = 0; i < 2; ++i) {
    for (uint8_t j = i + 1; j < 3; ++j) {
      if (valid[j] < valid[i]) {
        float tmp = valid[i]; valid[i] = valid[j]; valid[j] = tmp;
      }
    }
  }
  return valid[1];
}

Occupancy updateState(float cm, Occupancy previous, float enter, float leave) {
  if (cm < 0.0f) return UNKNOWN;
  if (cm <= enter) return OCCUPIED;
  if (cm >= leave) return VACANT;
  return previous; // hysteresis: hold prior state in the middle band
}

void printDistance(Print &out, float cm) {
  if (cm < 0.0f) out.print(F("null"));
  else out.print(cm, 1);
}
void printOccupancy(Print &out, Occupancy state) {
  if (state == UNKNOWN) out.print(F("null"));
  else if (state == OCCUPIED) out.print(F("true"));
  else out.print(F("false"));
}
void sendTelemetry(Print &out, float a1, float m1) {
  out.print(F("{\"node\":\"uno\",\"a1_distance_cm\":")); printDistance(out, a1);
  out.print(F(",\"m1_distance_cm\":")); printDistance(out, m1);
  out.print(F(",\"a1_occupied\":")); printOccupancy(out, a1State);
  out.print(F(",\"m1_occupied\":")); printOccupancy(out, m1State);
  out.println(F(",\"vibration\":null,\"vibration_count\":null,\"vibration_status\":\"not_installed\"}"));
}

void setup() {
  pinMode(A1_TRIG, OUTPUT); pinMode(A1_ECHO, INPUT);
  digitalWrite(A1_TRIG, LOW);
  if (M1_SENSOR_ENABLED) {
    pinMode(M1_TRIG, OUTPUT); pinMode(M1_ECHO, INPUT);
    digitalWrite(M1_TRIG, LOW);
  } // Otherwise leave D4/D5 unconfigured and reserved.
  Serial.begin(9600);
  gateway.begin(9600);
  gateway.stopListening(); // telemetry-only for now; no floating RX interrupts
  // D6 reserved for vibration; D9 servo; A4/A5 I2C LCD.
}

void loop() {
  unsigned long started = millis();
  float a[3], m[3];
  for (uint8_t i = 0; i < 3; ++i) {
    a[i] = readDistance(A1_TRIG, A1_ECHO);
    delay(70); // allow echoes to decay before triggering the other sensor
    if (M1_SENSOR_ENABLED) {
      m[i] = readDistance(M1_TRIG, M1_ECHO);
      delay(70);
    }
  }
  float a1 = filtered(a);
  float m1 = M1_SENSOR_ENABLED ? filtered(m) : -1.0f;
  a1State = updateState(a1, a1State, A1_ENTER_CM, A1_LEAVE_CM);
  m1State = M1_SENSOR_ENABLED
      ? updateState(m1, m1State, M1_ENTER_CM, M1_LEAVE_CM) : UNKNOWN;
  sendTelemetry(Serial, a1, m1);
  sendTelemetry(gateway, a1, m1);
  unsigned long elapsed = millis() - started;
  if (elapsed < SAMPLE_INTERVAL_MS) delay(SAMPLE_INTERVAL_MS - elapsed);
}
