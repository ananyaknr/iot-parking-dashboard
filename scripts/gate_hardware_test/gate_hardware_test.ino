
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Pin configuration
const byte U1_TRIG = 2;
const byte U1_ECHO = 3;
const byte U2_TRIG = 4;
const byte U2_ECHO = 5;
const byte VIB_PIN = 6;

// Servo D9 intentionally unused.

LiquidCrystal_I2C lcd27(0x27, 16, 2);
LiquidCrystal_I2C lcd3F(0x3F, 16, 2);
LiquidCrystal_I2C* lcd = nullptr;

float u1Distance = -1;
float u2Distance = -1;

unsigned long lastSample = 0;
unsigned long lastReport = 0;
unsigned long lastVibration = 0;
unsigned long vibrationCount = 0;

bool vibrationDetected = false;
int previousVibration;

char command[48];
byte commandLength = 0;

// Read ultrasonic distance
float readDistance(byte trig, byte echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);

  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);

  unsigned long duration = pulseIn(
    echo, HIGH, 25000UL
  );

  if (duration == 0) return -1;

  float cm = duration * 0.0343 / 2.0;

  if (cm < 2 || cm > 400) return -1;

  return cm;
}

// Display exactly 16 characters per row
void printRow(byte row, const char* text) {
  if (lcd == nullptr) return;

  lcd->setCursor(0, row);

  byte i = 0;

  while (text[i] && i < 16) {
    lcd->print(text[i]);
    i++;
  }

  while (i < 16) {
    lcd->print(' ');
    i++;
  }
}

bool i2cExists(byte address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

// Test display commands from USB Serial
void handleCommand(char* text) {
  if (strcmp(text, "WAIT") == 0) {
    printRow(0, "WAITING FOR CAR");
    printRow(1, "SYSTEM TEST");
    return;
  }

  if (strcmp(text, "READ") == 0) {
    printRow(0, "READING PLATE...");
    printRow(1, "PLEASE WAIT");
    return;
  }

  // Example: LCD|AB1234|supercar
  if (strncmp(text, "LCD|", 4) == 0) {
    char* plate = text + 4;
    char* separator = strchr(plate, '|');

    if (separator == nullptr) return;

    *separator = '\0';
    char* type = separator + 1;

    if (strlen(plate) > 16) return;

    printRow(0, plate);

    if (strcmp(type, "car") == 0) {
      printRow(1, "TYPE: CAR");
    }
    else if (strcmp(type, "supercar") == 0) {
      printRow(1, "TYPE: SUPERCAR");
    }
    else {
      printRow(1, "TYPE: UNKNOWN");
    }

    Serial.println(F("LCD display updated"));
  }
}

void readCommands() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n') {
      command[commandLength] = '\0';
      handleCommand(command);
      commandLength = 0;
    }
    else if (c != '\r') {
      if (commandLength < sizeof(command) - 1) {
        command[commandLength++] = c;
      }
    }
  }
}

// Poll vibration input and report raw transitions.
// This is a preliminary hardware diagnostic,
// not a calibrated vibration-event counter.
void checkVibration() {
  int current = digitalRead(VIB_PIN);
  unsigned long now = millis();

  if (current != previousVibration) {
    if (now - lastVibration >= 100) {
      vibrationCount++;
      vibrationDetected = true;
      lastVibration = now;

      Serial.print(F("VIB transition: "));
      Serial.println(current);
    }

    previousVibration = current;
  }

  if (now - lastVibration > 500) {
    vibrationDetected = false;
  }
}

void printDistance(float distance) {
  if (distance < 0) {
    Serial.print(F("UNKNOWN"));
  }
  else {
    Serial.print(distance, 1);
    Serial.print(F(" cm"));
  }
}

void setup() {
  Serial.begin(9600);

  pinMode(U1_TRIG, OUTPUT);
  pinMode(U1_ECHO, INPUT);
  pinMode(U2_TRIG, OUTPUT);
  pinMode(U2_ECHO, INPUT);
  pinMode(VIB_PIN, INPUT_PULLUP);

  digitalWrite(U1_TRIG, LOW);
  digitalWrite(U2_TRIG, LOW);

  previousVibration = digitalRead(VIB_PIN);

  Wire.begin();

  if (i2cExists(0x27)) {
    lcd = &lcd27;
    Serial.println(F("LCD found: 0x27"));
  }
  else if (i2cExists(0x3F)) {
    lcd = &lcd3F;
    Serial.println(F("LCD found: 0x3F"));
  }
  else {
    Serial.println(F("LCD NOT FOUND"));
  }

  if (lcd != nullptr) {
    lcd->init();
    lcd->backlight();

    printRow(0, "WAITING FOR CAR");
    printRow(1, "SYSTEM TEST");
  }

  Serial.println(F("GATE HARDWARE TEST"));
  Serial.println(F("SERVO DISABLED"));
}

void loop() {
  checkVibration();
  readCommands();

  unsigned long now = millis();

  // Alternate ultrasonic triggers to reduce crosstalk.
  static bool readU1 = true;

  if (now - lastSample >= 75) {
    lastSample = now;

    if (readU1) {
      u1Distance = readDistance(
        U1_TRIG, U1_ECHO
      );
    }
    else {
      u2Distance = readDistance(
        U2_TRIG, U2_ECHO
      );
    }

    readU1 = !readU1;
  }

  if (now - lastReport >= 1000) {
    lastReport = now;

    Serial.print(F("U1: "));
    printDistance(u1Distance);

    Serial.print(F(" | U2: "));
    printDistance(u2Distance);

    Serial.print(F(" | VIB_RAW: "));
    Serial.print(digitalRead(VIB_PIN));

    Serial.print(F(" | VIB_ACTIVE: "));
    Serial.print(vibrationDetected);

    Serial.print(F(" | COUNT: "));
    Serial.println(vibrationCount);
  }
}
