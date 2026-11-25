
#include <DHT.h>

#define DHT_PIN 4
#define DHT_TYPE DHT22
#define LDR_PIN 34
#define MQ2_PIN 35
#define UART_RX 25
#define UART_TX 26

DHT dht(DHT_PIN, DHT_TYPE);

const unsigned long SENSOR_INTERVAL = 2500;
unsigned long lastSensorRead = 0;

char unoBuffer[384];
size_t unoLength = 0;
bool overflow = false;

int readAverage(int pin) {
  long total = 0;
  for (int i = 0; i < 16; i++) {
    total += analogRead(pin);
    delay(5);
  }
  return total / 16;
}

void printFloat(float value) {
  if (isnan(value)) Serial.print("null");
  else Serial.print(value, 1);
}

// Receive newline-delimited JSON from UNO
void readUNO() {
  while (Serial2.available()) {
    char c = Serial2.read();

    if (c == '\n') {
      if (!overflow && unoLength > 1) {
        unoBuffer[unoLength] = '\0';

        if (unoBuffer[0] == '{' &&
            unoBuffer[unoLength - 1] == '}') {
          Serial.println(unoBuffer);
        }
      }

      unoLength = 0;
      overflow = false;
    }
    else if (c != '\r' && !overflow) {
      if (unoLength < sizeof(unoBuffer) - 1) {
        unoBuffer[unoLength++] = c;
      } else {
        overflow = true;
      }
    }
  }
}

void readEnvironment() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();

  int light = readAverage(LDR_PIN);
  int gas = readAverage(MQ2_PIN);

  Serial.print("{\"node\":\"esp32\"");

  Serial.print(",\"temperature_c\":");
  printFloat(temperature);

  Serial.print(",\"humidity_pct\":");
  printFloat(humidity);

  Serial.print(",\"light_raw\":");
  Serial.print(light);

  Serial.print(",\"gas_raw\":");
  Serial.print(gas);

  Serial.println(
    ",\"gas_status\":"
    "\"unconditioned_or_uncalibrated\"}"
  );
}

void setup() {
  Serial.begin(115200);

  Serial2.setRxBufferSize(1024);
  Serial2.begin(
    9600, SERIAL_8N1, UART_RX, UART_TX
  );

  dht.begin();

  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);

  pinMode(LDR_PIN, INPUT);
  pinMode(MQ2_PIN, INPUT);
}

void loop() {
  readUNO();

  unsigned long now = millis();

  if (now - lastSensorRead >= SENSOR_INTERVAL) {
    lastSensorRead = now;
    readEnvironment();
  }

  readUNO();
}
