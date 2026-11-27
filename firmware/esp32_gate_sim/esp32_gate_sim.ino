#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <GateCommon.h>
#include <atomic>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include "secrets.h"
// Full gate JSON can be decoded while the environmental ADC loop drains UART.
// Reserve room for those nested frames and the MQTT hand-off on the ESP32.
SET_LOOP_TASK_STACK_SIZE(16384);
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
struct Message { bool uno; bool gate; bool ack; uint8_t v3;uint32_t received,generation; char payload[1024]; };
struct DisplayMessage { char text[48]; uint32_t received,generation; bool usb; };
QueueHandle_t displayQueue;
char usbLine[48]; size_t usbLength=0; bool usbOverflow=false;
QueueHandle_t publishQueue;
std::atomic<bool> mqttOnline{false};
std::atomic<uint32_t> mqttGeneration{0};
char commandTopic[96]="";
uint32_t lastSensorRead = 0;
gatev2::Frame<224> unoFrame;
char activeBoot[33]="";
bool sessionPending=false;
uint32_t lastUnoReceived=0,frameStarted=0;
char pendingId[9]="",pendingText[64]="";
uint32_t pendingSince=0;
bool pendingRetried=false;

void enqueue(bool uno, const char *payload, bool gate=false, bool ack=false,uint8_t v3=0) {
  // Drop offline data; never replay an old UNO message as a fresh arrival.
  if (!mqttOnline) return;
  Message item{};
  item.uno = uno; item.gate = gate; item.ack=ack;item.v3=v3;item.generation=mqttGeneration.load();
  item.received = millis();
  strlcpy(item.payload, payload, sizeof(item.payload));
  if (xQueueSend(publishQueue, &item, 0) != pdTRUE)
    Serial.println(F("[MQTT] queue full; telemetry dropped"));
}

void randomHex(char* target,size_t words) {
  for(size_t i=0;i<words;++i) snprintf(target+i*8,9,"%08lx",(unsigned long)esp_random());
}
#include "ParkingV3.h"
void receiveFrame(char* frame) {
  ++uartFrames;
  if(receiveV3(frame)) return;
  if(!strcmp(frame,"HELLO2")) {
    if(!sessionPending) {randomHex(activeBoot,4);sessionPending=true;pendingId[0]=0;}
    Serial2.print("S2|");Serial2.println(activeBoot);return;
  }
  if(!strncmp(frame,"K2|",3)) {
    char* fields[4];
    if(gatev2::split(frame,fields,4)!=4 || !gatev2::hex(fields[1],8) || strcmp(fields[1],pendingId)) return;
    if(strcmp(fields[2],"ok") && strcmp(fields[2],"duplicate") && strcmp(fields[2],"rejected")) return;
    Serial.printf("LCD_ACK|%s|%s|%s\n",fields[1],fields[2],fields[3]);
    char ack[160];snprintf(ack,sizeof(ack),"{\"schema_version\":2,\"command_id\":\"%s\",\"status\":\"%s\",\"origin\":\"synthetic\",\"physical_movement\":false}",fields[1],fields[2]);
    enqueue(false,ack,false,true);pendingId[0]=0;return;
  }
  gatev2::Telemetry data;
  if(!gatev2::telemetry(frame,data)) {Serial.println("UART_REJECTED");return;}
  // ESP32 restarts can adopt the still-running UNO's epoch. A new HELLO gets a
  // fresh random 128-bit epoch; reconnects do not turn counters into new IDs.
  if(!activeBoot[0]) strcpy(activeBoot,data.boot);
  if(strcmp(activeBoot,data.boot)) {Serial.println("UART_OLD_BOOT");return;}
  sessionPending=false;lastUnoReceived=millis();
  JsonDocument document;
  document["node"]="uno";document["schema_version"]=2;document["mode"]="gate_sim";
  document["control_mode"]=data.integrated?"integrated":"standalone";
  document["boot_id"]=data.boot;document["uptime_ms"]=data.uptime;
  if(data.u1<0) document["u1_distance_cm"]=nullptr;else document["u1_distance_cm"]=data.u1;
  if(data.u2<0) document["u2_distance_cm"]=nullptr;else document["u2_distance_cm"]=data.u2;
  document["u1_state"]=gatev2::zoneName(data.z1);document["u2_state"]=gatev2::zoneName(data.z2);
  document["gate_sim_state"]=gatev2::stateName(data.state);document["servo_enabled"]=false;
  document["arrival_count"]=data.arrivals;document["completed_count"]=data.completed;
  document["vibration_raw"]=data.raw;document["vibration_transition_count"]=data.vibration;
  document["vibration_semantics"]="sampled_transitions";
  document["event_seq"]=data.sequence;document["last_event"]=data.event;
  char id[64];
  snprintf(id,sizeof(id),"v2:%s:a:%lu",data.boot,(unsigned long)data.arrivals);
  if(data.arrivals) document["arrival_id"]=id;else document["arrival_id"]=nullptr;
  char passage[64];snprintf(passage,sizeof(passage),"v2:%s:p:%lu",data.boot,(unsigned long)data.completed);
  if(data.completed) document["passage_id"]=passage;else document["passage_id"]=nullptr;
  char event[64];snprintf(event,sizeof(event),"v2:%s:e:%lu",data.boot,(unsigned long)data.sequence);
  document["event_id"]=event;
  char payload[1024];
  if(measureJson(document)>=sizeof(payload)) {Serial.println("UART_JSON_TOO_LARGE");return;}
  serializeJson(document,payload,sizeof(payload));Serial.println(payload);enqueue(true,payload,true);
}
void readUNO() {
  if(unoFrame.size && uint32_t(millis()-frameStarted)>500) {unoFrame.size=0;unoFrame.bad=true;}
  for(uint16_t budget=0;Serial2.available() && budget<512;++budget) {
    if(!unoFrame.size && !unoFrame.bad) frameStarted=millis();
    ++uartBytes;if(unoFrame.feed(char(Serial2.read()))) receiveFrame(unoFrame.data);
  }
}
// USB and rotating-nonce MQTT test topics accept synthetic display-only commands.
// Production recognition delivery remains disabled pending teammate agreement.
bool validDisplay(const char* text) {
  if(strlen(text)>=48) return false;
  char copy[48];strcpy(copy,text);char* fields[3];
  return gatev2::split(copy,fields,3)==3 && !strcmp(fields[0],"LCD")
    && gatev2::plate(fields[1]) && gatev2::vehicle(fields[2]);
}
void queueDisplay(const char* text,bool usb) {
  if(!displayQueue || !validDisplay(text)) {Serial.println("LCD_REJECTED");return;}
  DisplayMessage message{};strlcpy(message.text,text,sizeof(message.text));
  message.received=millis();message.generation=mqttGeneration.load();message.usb=usb;
  if(xQueueSend(displayQueue,&message,0)!=pdTRUE) Serial.println("LCD_QUEUE_FULL");
}
void readUSB() {
  while(Serial.available()) {
    char c=Serial.read();
    if(c=='\n') {
      if(!usbOverflow && usbLength) {usbLine[usbLength]=0;queueDisplay(usbLine,true);}
      usbLength=0;usbOverflow=false;
    } else if(c!='\r' && !usbOverflow) {
      if(uint8_t(c)<32 || uint8_t(c)>126 || usbLength>=sizeof(usbLine)-1) usbOverflow=true;
      else usbLine[usbLength++]=c;
    }
  }
}
void testDisplayCallback(char* topic,byte* payload,unsigned int length) {
  if(!strcmp(topic,V3_CONTROL)) {queueV3(payload,length);return;}
  if(strcmp(topic,commandTopic) || !length || length>=48) return;
  char text[48];memcpy(text,payload,length);text[length]=0;
  if(strlen(text)==length) queueDisplay(text,false);
}
void sendDisplay() {
  if(v3Token[0]) return;
  uint32_t now=millis();
  if(pendingId[0]) {
    if(uint32_t(now-pendingSince)>=1500) {Serial.printf("LCD_ACK_TIMEOUT|%s\n",pendingId);pendingId[0]=0;}
    else if(!pendingRetried && uint32_t(now-pendingSince)>=750 && uint32_t(now-lastUnoReceived)<100) {
      Serial2.println(pendingText);pendingRetried=true;
    }
    return;
  }
  // Drain one small frame just after a UNO report, while SoftwareSerial is receiving.
  if(uint32_t(now-lastUnoReceived)>=100) return;
  DisplayMessage message;
  if(displayQueue && xQueueReceive(displayQueue,&message,0)==pdTRUE) {
    if(uint32_t(now-message.received)>=2000 || (!message.usb &&
       (!mqttOnline || message.generation!=mqttGeneration.load()))) {Serial.println("LCD_EXPIRED");return;}
    char copy[48];strcpy(copy,message.text);char* fields[3];
    if(gatev2::split(copy,fields,3)!=3) return;
    randomHex(pendingId,1);
    snprintf(pendingText,sizeof(pendingText),"T2|%s|%s|%s",pendingId,fields[1],fields[2]);
    pendingSince=now;pendingRetried=false;Serial2.println(pendingText);
    Serial.printf("LCD_SENT_TEST|%s\n",pendingId);
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
  wifiClient.setConnectionTimeout(1000);
  mqtt.setCallback(testDisplayCallback);
  if (!mqtt.setBufferSize(1536)) {
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
          ++mqttGeneration;
          char nonce[17];randomHex(nonce,2);
          snprintf(commandTopic,sizeof(commandTopic),"parking/test/gate/lcd/%s",nonce);
          // Subscribe before advertising the fresh random topic. An old retained
          // command belongs to an earlier connection topic and cannot be replayed.
          if(!mqtt.subscribe(commandTopic,0)) Serial.println(F("[LCD] test subscription failed"));
          mqtt.subscribe(V3_CONTROL,1);
          char ready[180];snprintf(ready,sizeof(ready),"{\"schema_version\":2,\"test_only\":true,\"topic\":\"%s\"}",commandTopic);
          mqtt.publish("parking/test/gate/lcd/ready",ready,false);
          mqttOnline = true;
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
        if (item.generation==mqttGeneration.load() && millis() - item.received <= 1000) {
          bool ok = mqtt.publish(item.v3==1?"parking/test/gate/v3/telemetry":item.v3==2?"parking/test/gate/v3/ack":item.ack ? "parking/test/gate/lcd/ack" : item.gate ? "parking/test/gate/telemetry" : item.uno ? "parking/node/telemetry" : "parking/gateway/telemetry",
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
  Serial2.begin(19200, SERIAL_8N1, UART_RX, UART_TX);
  dht.begin();
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(LDR_PIN, INPUT); pinMode(MQ2_PIN, INPUT);
  publishQueue = xQueueCreate(16, sizeof(Message));
  displayQueue = xQueueCreate(4,sizeof(DisplayMessage));
  v3Queue=xQueueCreate(4,sizeof(V3Command));randomHex(gatewayBoot,4);
  if (!publishQueue || !displayQueue || !v3Queue || xTaskCreate(networkTask, "network", 16384, nullptr, 1, nullptr) != pdPASS) {
    Serial.println(F("[MQTT] task setup failed; USB telemetry remains active"));
  }
}

void loop() {
  readUNO();
  readUSB();
  sendV3();
  sendDisplay();
  uint32_t now = millis();
  if (now - lastSensorRead >= SENSOR_INTERVAL_MS) {
    lastSensorRead = now;
    readEnvironment();
  }
  readUNO();
  static uint32_t diagAt=0;
  if(uint32_t(millis()-diagAt)>=10000) {diagAt=millis();Serial.printf("UART_DIAG|bytes=%lu|frames=%lu|hello3=%lu|g3=%lu\n",(unsigned long)uartBytes,(unsigned long)uartFrames,(unsigned long)v3Hellos,(unsigned long)uartValid);}
  delay(1);
}
