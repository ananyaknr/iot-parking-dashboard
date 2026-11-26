#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "secrets.h"
#ifndef WIFI_ENTERPRISE
#define WIFI_ENTERPRISE 0
#endif
#if WIFI_ENTERPRISE
#include <esp_eap_client.h>
#include <sys/time.h>
#endif

// Preserve existing environmental monitoring. Gate simulation uses isolated test topics.
constexpr uint8_t DHT_PIN = 4, LDR_PIN = 34, MQ2_PIN = 35;
constexpr uint8_t UART_RX = 25, UART_TX = 26;
constexpr uint32_t SENSOR_INTERVAL_MS = 2500;
DHT dht(DHT_PIN, DHT22);
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
struct Message { bool uno; bool gate; uint32_t received; char payload[384]; };
struct DisplayMessage { char text[48]; uint32_t received; };
QueueHandle_t displayQueue;
char usbLine[48]; size_t usbLength=0; bool usbOverflow=false;
QueueHandle_t publishQueue;
volatile bool mqttOnline = false;
uint32_t lastSensorRead = 0;
char unoBuffer[384];
size_t unoLength = 0;
bool overflow = false;

void enqueue(bool uno, const char *payload, bool gate=false) {
  // Drop offline data; never replay an old UNO message as a fresh arrival.
  if (!mqttOnline) return;
  Message item{};
  item.uno = uno; item.gate = gate;
  item.received = millis();
  strlcpy(item.payload, payload, sizeof(item.payload));
  if (xQueueSend(publishQueue, &item, 0) != pdTRUE)
    Serial.println(F("[MQTT] queue full; telemetry dropped"));
}

void readUNO() {
  while (Serial2.available()) {
    char c = Serial2.read();
    if (c == '\n') {
      if (!overflow && unoLength > 1) {
        unoBuffer[unoLength] = '\0';
        if (unoBuffer[0] == '{' && unoBuffer[unoLength - 1] == '}') {
          // Only gate simulation schema goes to isolated test topic.
          const bool isGate = strstr(unoBuffer, "\"schema_version\":2") && strstr(unoBuffer, "\"mode\":\"gate_sim\"");
          Serial.println(unoBuffer);
          if (isGate) enqueue(true, unoBuffer, true);
          else if (strstr(unoBuffer, "\"a1_distance_cm\":")) enqueue(true, unoBuffer);
        } else if (strcmp(unoBuffer,"ACK|LCD|OK")==0 || strcmp(unoBuffer,"ACK|LCD|REJECTED")==0) {
          Serial.println(unoBuffer);
        }
      }
      unoLength = 0;
      overflow = false;
    } else if (c != '\r' && !overflow) {
      if (unoLength < sizeof(unoBuffer) - 1) unoBuffer[unoLength++] = c;
      else overflow = true;
    }
  }
}

// Bench-only display commands: no gate authorization or motion commands.
bool validDisplay(const char *text) {
  if (strncmp(text,"LCD|",4)) return false;
  const char *p=text+4,*sep=strchr(p,'|');
  if(!sep || sep==p || sep-p>16) return false;
  for(;p<sep;++p) {
    char c=*p;
    if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c==' '||c=='-')) return false;
  }
  return !strcmp(sep+1,"car") || !strcmp(sep+1,"supercar") || !strcmp(sep+1,"unknown");
}
void queueDisplay(const char *text) {
  if(!displayQueue || !validDisplay(text)) return;
  DisplayMessage m{};
  strlcpy(m.text,text,sizeof(m.text));m.received=millis();
  if(xQueueSend(displayQueue,&m,0)!=pdTRUE) Serial.println(F("[LCD] queue full"));
}
void readUSB() {
  while(Serial.available()) {
    char c=Serial.read();
    if(c=='\n') {
      if(!usbOverflow && usbLength) {usbLine[usbLength]='\0';queueDisplay(usbLine);}
      usbLength=0;usbOverflow=false;
    } else if(c!='\r' && !usbOverflow) {
      if(usbLength<sizeof(usbLine)-1) usbLine[usbLength++]=c;else usbOverflow=true;
    }
  }
}
void testDisplayCallback(char *topic,byte *payload,unsigned int length) {
  if(strcmp(topic,"parking/test/gate/lcd") || length==0 || length>=48) return;
  char text[48];
  memcpy(text,payload,length);text[length]='\0';
  if(strlen(text)!=length) return;
  queueDisplay(text);
}
void sendDisplay() {
  DisplayMessage m;
  if(displayQueue && xQueueReceive(displayQueue,&m,0)==pdTRUE && millis()-m.received<2000) {
    Serial2.println(m.text);
    Serial.println(F("[LCD] forwarded test command; wait for UNO ACK"));
  }
}

int readAverage(int pin) {
  long total = 0;
  for (int i = 0; i < 16; ++i) {
    total += analogRead(pin);
    readUNO(); // drain UART throughout the retained 16-sample ADC averaging
    delay(5);
  }
  return total / 16;
}

void readEnvironment() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  int light = readAverage(LDR_PIN);
  int gas = readAverage(MQ2_PIN);
  char t[20], h[20], payload[384];
  if (isnan(temperature)) strlcpy(t, "null", sizeof(t));
  else snprintf(t, sizeof(t), "%.1f", temperature);
  if (isnan(humidity)) strlcpy(h, "null", sizeof(h));
  else snprintf(h, sizeof(h), "%.1f", humidity);
  snprintf(payload, sizeof(payload),
    "{\"node\":\"esp32\",\"temperature_c\":%s,\"humidity_pct\":%s,"
    "\"light_raw\":%d,\"gas_raw\":%d,\"gas_status\":\"unconditioned_or_uncalibrated\"}",
    t, h, light, gas);
  Serial.println(payload);
  enqueue(false, payload);
}

void networkTask(void *) {
  // Only this task touches MQTT; slow TCP/MQTT connects cannot block UART reception.
  uint32_t lastWifiAttempt = 0, lastMqttAttempt = 0;
  bool wifiStarted = false;
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(testDisplayCallback);
  if (!mqtt.setBufferSize(768)) {
    Serial.println(F("[MQTT] buffer allocation failed"));
    vTaskDelete(nullptr);
  }
  mqtt.setSocketTimeout(1);
  mqtt.setKeepAlive(15);
  char clientId[40];
  snprintf(clientId, sizeof(clientId), "parking-esp32-%llx", ESP.getEfuseMac());
  WiFi.mode(WIFI_STA);
  // This task owns retries; do not race an automatic association attempt.
  WiFi.setAutoReconnect(false);
  WiFi.onEvent([](WiFiEvent_t, WiFiEventInfo_t info) {
    Serial.printf("[WiFi] disconnected, reason=%u\n", info.wifi_sta_disconnected.reason);
  }, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
#if WIFI_ENTERPRISE
  struct timeval clockTime = {static_cast<time_t>(WIFI_BOOTSTRAP_EPOCH), 0};
  settimeofday(&clockTime, nullptr);
  if (strlen(WIFI_CA_CERT) == 0 || strlen(WIFI_EAP_SERVER_NAME) == 0) {
    Serial.println(F("[WiFi] enterprise CA/server name missing; credentials not transmitted"));
    vTaskDelete(nullptr);
  }
#endif
  for (;;) {
    uint32_t now = millis();
    if (WiFi.status() != WL_CONNECTED) {
      mqttOnline = false;
      if (mqtt.connected()) mqtt.disconnect();
      if (!wifiStarted || now - lastWifiAttempt >= 20000) {
        wifiStarted = true;
        lastWifiAttempt = now;
        WiFi.disconnect(false, false);
        vTaskDelay(pdMS_TO_TICKS(250));
        Serial.println(F("[WiFi] connecting"));
#if WIFI_ENTERPRISE
        // Configure before associating so server identity is checked before sending inner credentials.
        WiFi.begin(WIFI_SSID, WPA2_AUTH_PEAP, WIFI_EAP_USERNAME, WIFI_EAP_USERNAME,
                   WIFI_PASSWORD, WIFI_CA_CERT, nullptr, nullptr, -1, 0, nullptr, false);
        if (esp_eap_client_set_domain_name(WIFI_EAP_SERVER_NAME) == ESP_OK &&
            esp_eap_client_set_disable_time_check(false) == ESP_OK) {
          WiFi.STA.connect();
        } else Serial.println(F("[WiFi] enterprise validation setup failed"));
#else
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#endif
      }
    } else if (!mqtt.connected()) {
      mqttOnline = false;
      if (lastMqttAttempt == 0 || now - lastMqttAttempt >= 5000) {
        lastMqttAttempt = now;
        Serial.print(F("[WiFi] connected, local IP: "));
        Serial.println(WiFi.localIP());
        if (mqtt.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)) {
          xQueueReset(publishQueue); // erase anything queued before this connection
          mqttOnline = true;
          if(!mqtt.subscribe("parking/test/gate/lcd",0)) Serial.println(F("[LCD] test subscription failed"));
          Serial.println(F("[MQTT] connected"));
        } else {
          Serial.print(F("[MQTT] connect failed, state=")); Serial.println(mqtt.state());
        }
      }
    } else {
      if (!mqtt.loop()) mqttOnline = false;
      Message item;
      if (mqttOnline && xQueueReceive(publishQueue, &item, 0) == pdTRUE) {
        // A short bounded hand-off, not an offline/reconnection replay buffer.
        if (millis() - item.received <= 1000) {
          bool ok = mqtt.publish(item.gate ? "parking/test/gate/telemetry" : item.uno ? "parking/node/telemetry" : "parking/gateway/telemetry",
                                 item.payload, false);
          if (!ok) {
            Serial.println(F("[MQTT] publish failed; message dropped"));
            mqttOnline = mqtt.connected();
          }
        } else Serial.println(F("[MQTT] expired queued message dropped"));
      }
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

void setup() {
  Serial.begin(115200);
  Serial2.setRxBufferSize(1024);
  Serial2.begin(9600, SERIAL_8N1, UART_RX, UART_TX);
  dht.begin();
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(LDR_PIN, INPUT); pinMode(MQ2_PIN, INPUT);
  publishQueue = xQueueCreate(16, sizeof(Message));
  displayQueue = xQueueCreate(4,sizeof(DisplayMessage));
  if (!publishQueue || xTaskCreate(networkTask, "network", 8192, nullptr, 1, nullptr) != pdPASS) {
    Serial.println(F("[MQTT] task setup failed; USB telemetry remains active"));
  }
}

void loop() {
  readUNO();
  readUSB();
  sendDisplay();
  uint32_t now = millis();
  if (now - lastSensorRead >= SENSOR_INTERVAL_MS) {
    lastSensorRead = now;
    readEnvironment();
  }
  readUNO();
  delay(1);
}
