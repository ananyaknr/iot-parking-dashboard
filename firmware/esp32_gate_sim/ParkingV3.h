// Internal adapter only; shared MQTT envelopes and durable dedup live in backend.
#include <GateWire3.h>
constexpr const char* V3_CONTROL="parking/test/gate/v3/control";
struct V3Command {char boot[33],gateway[33],token[9],lcd[33],type[9];uint32_t cycle,deadline,generation;};
QueueHandle_t v3Queue;
char gatewayBoot[33]="",v3Pending[128]="",v3Token[9]="";
gatewire3::Telemetry v3Latest{};
bool v3Active=false,v3Retried=false,v3HelloPending=false;
uint32_t v3At=0,v3Deadline=0,uartBytes=0,uartValid=0,uartFrames=0,v3Hellos=0,v3HelloAt=0;
void v3Ack(const char* token,const char* status) {
  JsonDocument d;d["wire_token"]=token;d["status"]=status;
  char payload[96];serializeJson(d,payload,sizeof(payload));enqueue(false,payload,false,false,2);
}
bool receiveV3(char* frame) {
  if(!strcmp(frame,"HELLO3")) {
    v3Active=true;++v3Hellos;
    if(!sessionPending) {randomHex(activeBoot,4);sessionPending=true;v3Token[0]=0;}
    v3HelloPending=true;v3HelloAt=millis();return true;
  }
  if(!strncmp(frame,"K3|",3)) {
    char* f[3];if(gatev2::split(frame,f,3)==3 && !strcmp(f[1],v3Token)
      && (!strcmp(f[2],"ok")||!strcmp(f[2],"duplicate")||!strcmp(f[2],"rejected"))) {
      v3Ack(f[1],f[2]);v3Token[0]=0;
    }
    return true;
  }
  if(strncmp(frame,"G3|",3) && strncmp(frame,"A3|",3) && strncmp(frame,"P3|",3)) return false;
  gatewire3::Telemetry t;
  if(!gatewire3::telemetry(frame,t)) {Serial.println("G3_REJECTED");return true;}
  if(!activeBoot[0]) strcpy(activeBoot,t.boot);
  if(strcmp(activeBoot,t.boot)) {
    // A still-running UNO owns its epoch after an ESP32 restart. Adopting it
    // cannot replay a command: gateway boot nonce and durable arrival ledger guard it.
    if(v3Token[0]) {v3Ack(v3Token,"rejected");v3Token[0]=0;}
    strcpy(activeBoot,t.boot);
  }
  v3Latest=t;v3Active=true;sessionPending=false;lastUnoReceived=millis();++uartValid;
  JsonDocument d;
  d["schema_version"]=3;d["mode"]=t.mode=='P'?"entrance_exit_auto_physical":t.mode=='A'?"entrance_exit_auto_sim":"entrance_exit_sim";d["boot_id"]=t.boot;d["gateway_boot_id"]=gatewayBoot;
  d["uptime_ms"]=t.uptime;d["gateway_uptime_ms"]=millis();
  if(t.u1<0)d["u1_distance_cm"]=nullptr;else d["u1_distance_cm"]=t.u1;
  if(t.u2<0)d["u2_distance_cm"]=nullptr;else d["u2_distance_cm"]=t.u2;
  d["u1_state"]=gatev2::zoneName(t.z1);d["u2_state"]=gatev2::zoneName(t.z2);
  d["phase"]=t.phase;d["lane"]=t.lane;d["cycle"]=t.cycle;
  d["vibration_raw"]=t.raw;d["vibration_transition_count"]=t.vibration;d["reason"]=t.reason;
  d["minimum_open_ms"]=t.minimum;d["started_at_ms"]=t.started;d["servo_enabled"]=t.mode=='P';
  char payload[1024];if(measureJson(d)>=sizeof(payload))return true;
  serializeJson(d,payload,sizeof(payload));enqueue(false,payload,false,false,1);
  return true;
}
void queueV3(byte* bytes,unsigned length) {
  if(!length||length>1024||memchr(bytes,0,length))return;
  JsonDocument d;if(deserializeJson(d,bytes,length))return;
  if(!d["boot_id"].is<const char*>()||!d["gateway_boot_id"].is<const char*>()
    ||!d["wire_token"].is<const char*>()||!d["lcd_hex"].is<const char*>()||!d["vehicle_type"].is<const char*>()
    ||!d["cycle"].is<uint32_t>()||!d["deadline_ms"].is<uint32_t>())return;
  const char* boot=d["boot_id"];const char* gw=d["gateway_boot_id"];const char* token=d["wire_token"];
  const char* lcd=d["lcd_hex"];const char* type=d["vehicle_type"];char decoded[17];
  if(!gatev2::hex(boot,32)||strcmp(gw,gatewayBoot)||!gatev2::hex(token,8)
     ||!gatewire3::lcdDecode(lcd,decoded)||!gatewire3::vehicle(type))return;
  V3Command c{};strcpy(c.boot,boot);strcpy(c.gateway,gw);strcpy(c.token,token);strcpy(c.lcd,lcd);strcpy(c.type,type);
  c.cycle=d["cycle"];c.deadline=d["deadline_ms"];c.generation=mqttGeneration.load();
  if(!gatewire3::deadline(millis(),c.deadline))return;
  xQueueSend(v3Queue,&c,0);
}
void sendV3() {
  uint32_t now=millis();
  if(v3HelloPending) {
    // SoftwareSerial cannot receive during its final transmitted stop bit.
    if(uint32_t(now-v3HelloAt)>=5) {Serial2.print("S3|");Serial2.println(activeBoot);v3HelloPending=false;}
    return;
  }
  if(pendingId[0])return;
  if(v3Token[0]) {
    if(!gatewire3::deadline(now,v3Deadline)||uint32_t(now-v3At)>=1500) {v3Ack(v3Token,"timeout");v3Token[0]=0;}
    else if(!v3Retried && uint32_t(now-v3At)>=750 && uint32_t(now-lastUnoReceived)<100) {
      Serial2.println(v3Pending);v3Retried=true;
    }
    return;
  }
  if(!v3Active||uint32_t(now-lastUnoReceived)>=100)return;
  V3Command c;
  if(xQueueReceive(v3Queue,&c,0)!=pdTRUE)return;
  if(!mqttOnline||c.generation!=mqttGeneration.load()||strcmp(c.boot,activeBoot)
    ||v3Latest.phase!=2||v3Latest.lane!=1||c.cycle!=v3Latest.cycle||!gatewire3::deadline(now,c.deadline)) {
    v3Ack(c.token,"rejected");return;
  }
  // Sample-based deadline is conservative: queue/transit delay can only shorten TTL.
  uint32_t remaining=c.deadline-now;
  uint32_t unoDeadline=v3Latest.uptime+remaining;
  snprintf(v3Pending,sizeof(v3Pending),"C3|%s|%s|%lu|%lu|%s|%s",c.token,c.boot,
      (unsigned long)c.cycle,(unsigned long)unoDeadline,c.lcd,c.type);
  strcpy(v3Token,c.token);v3Deadline=c.deadline;v3At=now;v3Retried=false;Serial2.println(v3Pending);
}
