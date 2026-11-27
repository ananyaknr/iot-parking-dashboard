#include <Arduino.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <GateCommon.h>
#include <GateBench.h>
#include <GateActuator.h>
#include <GateWire3.h>
#include <Servo.h>
#include <util/atomic.h>
using namespace gatev2;
// Default build never attaches D9. Automatic physical output is a separate,
// explicit build opt-in, not a remote command or runtime arming operation.
#ifndef GATE_MANUAL_SERVO_ENABLED
#define GATE_MANUAL_SERVO_ENABLED 0
#endif
#ifndef GATE_ENTRANCE_EXIT_ENABLED
#define GATE_ENTRANCE_EXIT_ENABLED 1
#endif
#if GATE_MANUAL_SERVO_ENABLED && GATE_ENTRANCE_EXIT_ENABLED
#error Confirmed entrance-exit simulation must not enable physical servo output
#endif
#ifndef GATE_AUTOMATIC_ENABLED
#define GATE_AUTOMATIC_ENABLED 0
#endif
#ifndef GATE_PHYSICAL_ENABLED
#define GATE_PHYSICAL_ENABLED 0
#endif
#ifndef GATE_OPEN_ANGLE
#define GATE_OPEN_ANGLE 80
#endif
#ifndef GATE_CLOSED_ANGLE
#define GATE_CLOSED_ANGLE 10
#endif
#if GATE_PHYSICAL_ENABLED && (!GATE_AUTOMATIC_ENABLED || !GATE_ENTRANCE_EXIT_ENABLED || GATE_MANUAL_SERVO_ENABLED)
#error Physical automatic build requires automatic mode and separate manual driver disabled
#endif
static_assert(GATE_OPEN_ANGLE>=5 && GATE_OPEN_ANGLE<=175 && GATE_CLOSED_ANGLE>=5 && GATE_CLOSED_ANGLE<=175 && GATE_OPEN_ANGLE!=GATE_CLOSED_ANGLE,"Invalid angles");
Servo barrier;
gatebench::Controller bench;
bool localBench=GATE_ENTRANCE_EXIT_ENABLED,servoArmed=false,manualMovement=false;
uint8_t closedAngle=GATE_CLOSED_ANGLE,openAngle=GATE_OPEN_ANGLE;
const uint8_t U1_TRIG=2,U1_ECHO=3,U2_TRIG=4,U2_ECHO=5,VIB=6;
const bool INTEGRATED_MODE=false; // Enable only after teammate contract agreement.
SoftwareSerial gateway(10,11);
LiquidCrystal_I2C lcd27(0x27,16,2),lcd3f(0x3f,16,2);
LiquidCrystal_I2C* lcd=nullptr;
Machine machine;
char bootId[33]="";
Frame<48> usbFrame;
Frame<128> uartFrame;
uint16_t uartFrames=0;
uint32_t lastTrigger=0,lastReport=0,lastHello=0,displayAt=0,displayArrival=0,displayEvent=0;
bool nextU1=true,displayOverride=false;
volatile uint8_t vibrationRaw=1;
volatile uint8_t vibrationMinimum=1,vibrationMaximum=1;
volatile uint32_t vibrationTransitions=0,vibrationTicks=0,lastVibrationTick=0;
// SoftwareSerial owns the PCINT vectors. Timer2 samples D6 instead of conflicting
// with those ISRs. Nominal 1 kHz; interrupt masking can miss short pulses.
ISR(TIMER2_COMPA_vect) {
  ++vibrationTicks;
  uint8_t value=(PIND & _BV(PD6))?1:0;
  if(value!=vibrationRaw) {
    vibrationRaw=value;
    if(value<vibrationMinimum) vibrationMinimum=value;
    if(value>vibrationMaximum) vibrationMaximum=value;
    if(uint32_t(vibrationTicks-lastVibrationTick)>=50) {
      if(vibrationTransitions!=UINT32_MAX) ++vibrationTransitions;
      lastVibrationTick=vibrationTicks;
    }
  }
}
void row(uint8_t line,const char* text) {
  if(!lcd) return;
  lcd->setCursor(0,line);uint8_t n=0;
  while(n<16 && text[n]) {lcd->print(text[n]);++n;}
  while(n++<16) lcd->print(' ');
}
void rowFlash(uint8_t line,const __FlashStringHelper* text) {
  if(!lcd) return;
  lcd->setCursor(0,line);const char* flash=(const char*)text;uint8_t n=0;
  while(n<16) {char c=pgm_read_byte(flash+n);if(!c) break;lcd->print(c);++n;}
  while(n++<16) lcd->print(' ');
}
const __FlashStringHelper* benchReason() {
  switch(bench.reason) {
    case gatebench::R_READY:return F("ready");
    case gatebench::R_ENTRANCE:return F("entrance_wait");
    case gatebench::R_EXIT:return F("exit_local");
    case gatebench::R_MANUAL:return F("manual_open");
    case gatebench::R_AUTHORIZED:return F("bench_authorized");
    case gatebench::R_CLOSING:return F("closing_command");
    case gatebench::R_UNKNOWN:return F("sensor_unknown");
    case gatebench::R_CONFLICT:return F("competing_lanes");
    case gatebench::R_TIMEOUT:return F("cycle_timeout");
    case gatebench::R_OPPOSITE:return F("opposite_lane");
    case gatebench::R_AUTH_TIMEOUT:return F("auth_timeout");
    case gatebench::R_OBSTRUCTION:return F("obstruction");
    case gatebench::R_COMPLETE:return F("bench_completed");
    case gatebench::R_RESET:return F("reset");
    case gatebench::R_STOP:return F("operator_stop");
    case gatebench::R_UNVERIFIED:return F("passage_review");
    default:return F("boot");
  }
}
void showState() {
  if(displayOverride) return;
  if(localBench) {
    rowFlash(0,GATE_AUTOMATIC_ENABLED?(GATE_PHYSICAL_ENABLED?F("AUTO UNMEASURED"):F("AUTO SIMULATION")):F("LOCAL BENCH ONLY"));rowFlash(1,benchReason());return;
  }
  if(machine.state==CLOSED) rowFlash(0,F("WAITING FOR CAR"));
  else if(machine.state==AUTH_WAIT) rowFlash(0,F("READING PLATE..."));
  else if(machine.state==HOLD) rowFlash(0,F("SUPERVISED RESET"));
  else row(0,stateName(machine.state));
  rowFlash(1,F("SIMULATION ONLY"));
}
float distanceCm(uint8_t trig,uint8_t echo) {
  digitalWrite(trig,LOW);delayMicroseconds(2);
  digitalWrite(trig,HIGH);delayMicroseconds(10);digitalWrite(trig,LOW);
  uint32_t duration=pulseIn(echo,HIGH,25000UL);
  float value=duration*0.0343f/2;
  return duration && value>=2 && value<=400?value:-1;
}
struct Seen {char id[9];uint32_t hash;};
Seen seen[4]={};uint8_t seenNext=0;
uint32_t fingerprint(const char* s) {uint32_t h=2166136261UL;while(*s) {h^=uint8_t(*s++);h*=16777619UL;}return h;}
void ack(const char* id,const char* result,const char* kind) {
  gateway.print(F("K2|"));gateway.print(id);gateway.print('|');gateway.print(result);
  gateway.print('|');gateway.println(kind);
  Serial.print(F("ACK|"));Serial.print(id);Serial.print('|');Serial.print(result);Serial.print('|');Serial.println(kind);
}
void benchReport() {
  Serial.print(F("BENCH3|entrance_exit|"));Serial.print(bench.cycle);
  Serial.print('|');Serial.print(uint8_t(bench.lane));Serial.print('|');Serial.print(uint8_t(bench.phase));
  Serial.print('|');Serial.print(benchReason());Serial.print(F("|servo="));Serial.print(barrier.attached()?1:0);
  Serial.print(F("|automatic_physical="));Serial.print(GATE_PHYSICAL_ENABLED);Serial.print(F("|position=unmeasured|minimum_ms="));Serial.println(bench.minimumOpenMs);
}
bool localCommand(char* text) {
  if(!strcmp_P(text,PSTR("SENSORS?"))) {
    Serial.print(F("SENSOR_DIAG|U1="));Serial.print(machine.u1.cm,1);
    Serial.print(F("|U2="));Serial.print(machine.u2.cm,1);
    Serial.print(F("|LCD="));Serial.print(lcd?1:0);
    Serial.print(F("|UART_SESSION="));Serial.print(machine.ready?1:0);
    Serial.print(F("|UART_FRAMES="));Serial.print(uartFrames);
    Serial.print(F("|D5="));Serial.println(digitalRead(U2_ECHO));return true;
  }
  if(!strcmp_P(text,PSTR("STATUS"))) {benchReport();return true;}
  if(!strcmp_P(text,PSTR("STOP"))) {
    barrier.detach();servoArmed=false;manualMovement=false;
    bench.hold(gatebench::R_STOP);Serial.println(F("STOPPED_POSITION_UNKNOWN"));return true;
  }
  if(!strcmp_P(text,PSTR("LOCAL"))) {
    if(barrier.attached() || (machine.state!=BOOT && machine.state!=CLOSED && machine.state!=HOLD)) {
      Serial.println(F("LOCAL_BUSY"));return true;
    }
    localBench=true;displayOverride=false;benchReport();showState();return true;
  }
  if(!strcmp_P(text,PSTR("LEGACY"))) {
    // Reset to restore G2: avoids merging counters/epochs across local modes.
    Serial.println(F("REBOOT_TO_RESTORE_G2"));return true;
  }
  bool structured=!strncmp_P(text,PSTR("ANGLES|"),7) || !strncmp_P(text,PSTR("MINIMUM|"),8)
    || !strncmp_P(text,PSTR("ALLOW|"),6) || !strncmp_P(text,PSTR("CONFIRM|"),8);
  char* f[4];uint8_t n=structured?split(text,f,4):0;uint32_t a=0,b=0;
  if(n==3 && !strcmp_P(f[0],PSTR("ANGLES"))) {
    bool ok=!barrier.attached() && bench.phase!=gatebench::OPEN && bench.phase!=gatebench::CLOSING
      && decimal(f[1],a) && decimal(f[2],b) && a>=5 && a<=175 && b>=5 && b<=175 && a!=b;
    if(ok) {closedAngle=a;openAngle=b;}
    Serial.println(ok?F("ANGLES_SET_VOLATILE"):F("ANGLES_REFUSED"));return true;
  }
  if(n==2 && !strcmp_P(f[0],PSTR("MINIMUM"))) {
    bool ok=!barrier.attached() && bench.phase==gatebench::CLOSED && decimal(f[1],a) && a>=5000 && a<=60000;
    if(ok) bench.minimumOpenMs=a;
    Serial.println(ok?F("MINIMUM_SET"):F("MINIMUM_REFUSED"));return true;
  }
  if(!localBench) return false;
  if(!strcmp_P(text,PSTR("ARM"))) {
    // Arming does not attach or command a position. USB only, reboot clears it.
    servoArmed=GATE_MANUAL_SERVO_ENABLED && bench.phase==gatebench::CLOSED
      && machine.u1.clear() && machine.u2.clear();
    Serial.println(servoArmed?F("ARMED_MANUAL_ONLY"):F("ARM_REFUSED_BUILD_OR_STATE"));return true;
  }
  if(!strcmp_P(text,PSTR("OPEN"))) {
    bool ok=machine.u1.clear() && machine.u2.clear() && bench.start(gatebench::MANUAL,millis());
    if(ok && servoArmed) {
      // Preload exact pulse before attach, avoiding an initial neutral pulse.
      barrier.writeMicroseconds(1000UL+uint32_t(openAngle)*1000/180);
      if(!barrier.attached()) barrier.attach(9,1000,2000);
      manualMovement=true;
    }
    Serial.println(ok?(servoArmed?F("MANUAL_OPEN_COMMANDED"):F("SIMULATED_OPEN")):F("OPEN_REFUSED"));
    showState();return true;
  }
  if(n==2 && !strcmp_P(f[0],PSTR("ALLOW"))) {
    bool ok=decimal(f[1],a) && machine.u1.cm>=2 && machine.u2.clear() && bench.authorize(a,millis());
    Serial.println(ok?F("BENCH_ALLOW_SIMULATED"):F("ALLOW_REFUSED"));return true;
  }
  if(n==2 && !strcmp_P(f[0],PSTR("CONFIRM"))) {
    Serial.println(decimal(f[1],a) && bench.confirm(a)?F("BENCH_PASSAGE_CONFIRMED"):F("CONFIRM_REFUSED"));return true;
  }
  if(!strcmp_P(text,PSTR("CLOSE"))) {
    bool ok=machine.u1.clear() && machine.u2.clear() && bench.close(millis());
    if(ok && servoArmed && manualMovement) barrier.write(closedAngle);
    Serial.println(ok?(manualMovement?F("MANUAL_CLOSE_COMMANDED"):F("SIMULATED_CLOSE")):F("CLOSE_REFUSED"));return true;
  }
  if(!strcmp(text,"RESET")) {
    bool ok=!barrier.attached() && machine.u1.clear() && machine.u2.clear() && bench.reset();
    Serial.println(ok?F("BENCH_RESET"):F("RESET_REFUSED"));return true;
  }
  return false;
}
void command(char* text,bool usb) {
  if(usb && localCommand(text)) return;
  if(usb && !strcmp(text,"VIB?")) {
    uint8_t raw,minimum,maximum;uint32_t transitions;
    ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {raw=vibrationRaw;minimum=vibrationMinimum;maximum=vibrationMaximum;transitions=vibrationTransitions;}
    Serial.print(F("VIB_DIAG|"));Serial.print(raw);Serial.print('|');Serial.print(minimum);
    Serial.print('|');Serial.print(maximum);Serial.print('|');Serial.println(transitions);return;
  }
  if(usb && !strcmp(text,"RESET")) {Serial.println(machine.reset()?F("RESET_ACCEPTED"):F("RESET_REFUSED"));return;}
  uint32_t hash=fingerprint(text);char* fields[8];uint8_t count=split(text,fields,8);
  if(!count) return;
  if(!usb && count==2 && !strcmp(fields[0],localBench?"S3":"S2") && hex(fields[1],32)) {
    if(!machine.ready) {strcpy(bootId,fields[1]);machine.ready=true;}
    return;
  }
  if(!usb && localBench && count==7 && !strcmp(fields[0],"C3") && hex(fields[1],8)) {
    const char* result="rejected";
    for(const Seen& item:seen) if(!strcmp(item.id,fields[1])) {
      result=item.hash==hash?"duplicate":"rejected";
      gateway.print(F("K3|"));gateway.print(fields[1]);gateway.print('|');gateway.println(result);return;
    }
    uint32_t cycle=0,end=0;char ascii[17];
    if(machine.ready && !strcmp(fields[2],bootId) && decimal(fields[3],cycle)
      && decimal(fields[4],end) && gatewire3::deadline(millis(),end)
      && gatewire3::lcdDecode(fields[5],ascii) && gatewire3::vehicle(fields[6])
      && machine.u1.cm>=2 && machine.u2.clear() && lcd && bench.authorize(cycle,millis())) {
      row(0,ascii);row(1,fields[6]);displayOverride=true;displayAt=millis();
      displayArrival=machine.arrivals;displayEvent=machine.eventSeq;
      lastReport=0;
      strcpy(seen[seenNext].id,fields[1]);seen[seenNext].hash=hash;seenNext=(seenNext+1)%4;
      result="ok";
    }
    gateway.print(F("K3|"));gateway.print(fields[1]);gateway.print('|');gateway.println(result);return;
  }
  if(usb || (localBench && strcmp(fields[0],"T2")) || count<2 || !hex(fields[1],8)) return;
  for(const Seen& item:seen) if(!strcmp(item.id,fields[1])) {
    ack(fields[1],item.hash==hash?"duplicate":"rejected","display");return;
  }
  bool test=count==4 && !strcmp(fields[0],"T2");
  uint32_t arrival=0;
  bool real=count==6 && !strcmp(fields[0],"L2") && !strcmp(fields[2],bootId)
            && decimal(fields[3],arrival) && arrival==machine.arrivals && arrival>0
            && (machine.state==OPEN_WAIT || machine.state==PASSING || machine.state==AUTH_WAIT);
  const char* plateText=test?fields[2]:real?fields[4]:"";
  const char* type=test?fields[3]:real?fields[5]:"";
  // Test displays are explicit and never authorize a gate cycle.
  if((test||real) && lcd && plate(plateText) && vehicle(type)) {
    row(0,plateText);
    rowFlash(1,test?(!strcmp(type,"car")?F("TEST CAR"):!strcmp(type,"sportcar")?F("TEST SPORTCAR"):!strcmp(type,"supercar")?F("TEST SUPERCAR"):F("TEST UNKNOWN")):
        (!strcmp(type,"car")?F("TYPE: CAR"):!strcmp(type,"sportcar")?F("TYPE: SPORTCAR"):!strcmp(type,"supercar")?F("TYPE: SUPERCAR"):F("TYPE: UNKNOWN")));
    displayAt=millis();displayArrival=machine.arrivals;displayOverride=true;
    strcpy(seen[seenNext].id,fields[1]);seen[seenNext].hash=hash;seenNext=(seenNext+1)%4;
    ack(fields[1],"ok",test?"test":"display");return;
  }
  if(count==6 && !strcmp(fields[0],"A2") && !strcmp(fields[2],bootId)
      && decimal(fields[3],arrival) && !strcmp(fields[5],"v2")
      && (!strcmp(fields[4],"allow")||!strcmp(fields[4],"deny"))
      && machine.authorize(arrival,!strcmp(fields[4],"allow"),millis())) {
    ack(fields[1],"ok","simulation_authorization");return;
  }
  ack(fields[1],"rejected","display");
}
template<size_t N> void readCommands(Stream& port,Frame<N>& frame,bool usb) {
  static uint32_t uartStarted=0,usbStarted=0;
  uint32_t& started=usb?usbStarted:uartStarted;
  if(frame.size && uint32_t(millis()-started)>500) {frame.size=0;frame.bad=true;}
  for(uint8_t budget=0;port.available() && budget<96;++budget) {
    if(!frame.size && !frame.bad) started=millis();
    if(frame.feed(char(port.read()))) {if(!usb && uartFrames!=UINT16_MAX) ++uartFrames;command(frame.data,usb);}
  }
}
void reportTo(Print& out,uint8_t raw,uint32_t transitions) {
  if(localBench) {
    out.print(GATE_PHYSICAL_ENABLED?F("P3|"):GATE_AUTOMATIC_ENABLED?F("A3|"):F("G3|"));out.print(bootId);out.print('|');out.print(millis());out.print('|');
    if(machine.u1.cm<0) out.print(F("null"));else out.print(machine.u1.cm,1);out.print('|');
    if(machine.u2.cm<0) out.print(F("null"));else out.print(machine.u2.cm,1);out.print('|');
    out.print(zoneName(machine.u1.visible()));out.print('|');out.print(zoneName(machine.u2.visible()));out.print('|');
    out.print(uint8_t(bench.phase));out.print('|');out.print(uint8_t(bench.lane));out.print('|');out.print(bench.cycle);out.print('|');
    out.print(raw);out.print('|');out.print(transitions);out.print('|');out.print(uint8_t(bench.reason));out.print('|');
    out.print(bench.minimumOpenMs);out.print('|');out.println(bench.startedAt);return;
  }
  out.print(F("G2|"));out.print(bootId);out.print('|');out.print(millis());out.print('|');
  if(machine.u1.cm<0) out.print(F("null"));else out.print(machine.u1.cm,1);out.print('|');
  if(machine.u2.cm<0) out.print(F("null"));else out.print(machine.u2.cm,1);out.print('|');
  out.print(zoneName(machine.u1.visible()));out.print('|');out.print(zoneName(machine.u2.visible()));out.print('|');
  out.print(stateName(machine.state));out.print('|');out.print(machine.arrivals);out.print('|');
  out.print(machine.completed);out.print('|');out.print(raw);out.print('|');out.print(transitions);out.print('|');
  out.print(machine.eventSeq);out.print('|');out.print(machine.event);out.print('|');out.println(INTEGRATED_MODE?1:0);
}
void report() {
  uint8_t raw;uint32_t transitions;
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {raw=vibrationRaw;transitions=vibrationTransitions;}
  reportTo(gateway,raw,transitions);reportTo(Serial,raw,transitions);
}

void automaticActuator() {
#if GATE_PHYSICAL_ENABLED
  static gatebench::Actuator policy;
  gatebench::Motion motion=policy.update(bench.phase);
  if(motion==gatebench::MOVE_OPEN) {
    // Retain the previously verified 1000–2000 us SG90 pulse mapping.
    barrier.writeMicroseconds(1000+uint16_t(openAngle)*1000/180);
    if(!barrier.attached()) barrier.attach(9,1000,2000);
  } else if(motion==gatebench::MOVE_CLOSE && barrier.attached()) barrier.write(closedAngle);
  else if(motion==gatebench::REOPEN && barrier.attached()) barrier.write(openAngle);
#endif
}
void setup() {
  bench.automatic=GATE_AUTOMATIC_ENABLED;
  Serial.begin(115200);gateway.begin(19200);gateway.listen();
  pinMode(U1_TRIG,OUTPUT);pinMode(U1_ECHO,INPUT);pinMode(U2_TRIG,OUTPUT);pinMode(U2_ECHO,INPUT);
  digitalWrite(U1_TRIG,LOW);digitalWrite(U2_TRIG,LOW);pinMode(VIB,INPUT_PULLUP);
  vibrationRaw=digitalRead(VIB);vibrationMinimum=vibrationMaximum=vibrationRaw;machine.integrated=INTEGRATED_MODE;
  // Supervised, servo-disabled standalone bench steps need time for an operator.
  // Unknown echoes/obstructions still hold immediately; real authorization stays 20 s.
  machine.cycleTimeoutMs=INTEGRATED_MODE?20000UL:120000UL;
  Wire.begin();Wire.setWireTimeout(25000,true);
  for(uint8_t address=8;address<120;++address) {
    Wire.beginTransmission(address);
    if(Wire.endTransmission()==0) {Serial.print(F("I2C_ADDRESS|"));Serial.println(address,HEX);
      if(address==0x27) lcd=&lcd27;else if(!lcd && address==0x3f) lcd=&lcd3f;}
  }
  if(lcd) {lcd->init();lcd->backlight();}else Serial.println(F("LCD_NOT_FOUND"));
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {TCCR2A=_BV(WGM21);TCCR2B=_BV(CS22);OCR2A=249;TIMSK2|=_BV(OCIE2A);}
  showState();Serial.println(F("INTEGRATED_RESTORED; SERVO DETACHED; POSITION UNMEASURED"));
  Serial.print(F("AUTOMATIC_BUILD|"));Serial.println(GATE_AUTOMATIC_ENABLED);
  Serial.print(F("PHYSICAL_BUILD|"));Serial.println(GATE_PHYSICAL_ENABLED);
  Serial.print(F("MANUAL_SERVO_BUILD|"));Serial.println(GATE_MANUAL_SERVO_ENABLED);
  Serial.print(F("CYCLE_TIMEOUT_MS|"));Serial.println(machine.cycleTimeoutMs);
}
void loop() {
  readCommands(gateway,uartFrame,false);readCommands(Serial,usbFrame,true);
  uint32_t now=millis();
  if(!machine.ready && uint32_t(now-lastHello)>=500) {gateway.println(localBench?F("HELLO3"):F("HELLO2"));lastHello=now;}
  // G3 commands return immediately after a report. SoftwareSerial's receive ISR
  // can hide a short HC-SR04 echo from pulseIn. Reserve a bounded receive slot;
  // never convert a failed measurement into clearance or relax hold rules.
  bool receiveSlot=localBench && machine.ready && uint32_t(now-lastReport)<250;
  if(uint32_t(now-lastTrigger)>=75 && !receiveSlot && !uartFrame.size && !gateway.available()) {
    lastTrigger=now;
    if(nextU1) machine.u1.sample(distanceCm(U1_TRIG,U1_ECHO));else machine.u2.sample(distanceCm(U2_TRIG,U2_ECHO));
    nextU1=!nextU1;
  }
  if(localBench) {
    gatebench::Phase before=bench.phase;
    bench.update(machine.u1,machine.u2,millis());
    automaticActuator(); // start movement before potentially slow UART reporting
    if(before!=bench.phase) {
      if(bench.phase==gatebench::HOLD || bench.phase==gatebench::CLOSED) displayOverride=false;
      if(bench.phase==gatebench::HOLD && servoArmed && manualMovement) {
        // Unknown/obstructed closing reopens the supervised manual cycle only.
        barrier.write(openAngle);
      }
      if(bench.phase==gatebench::CLOSED) manualMovement=false;
      benchReport();showState();
      if(machine.ready) {report();lastReport=millis();}
    }
  } else machine.update(millis());
  automaticActuator();
  if(displayOverride && (machine.arrivals!=displayArrival || machine.eventSeq!=displayEvent
       || uint32_t(millis()-displayAt)>=15000)) {displayOverride=false;showState();}
  if(displayEvent!=machine.eventSeq) {displayEvent=machine.eventSeq;displayOverride=false;showState();}
  static uint32_t reportedSequence=UINT32_MAX;
  if(machine.ready && (machine.eventSeq!=reportedSequence || uint32_t(millis()-lastReport)>=1000)) {
    lastReport=millis();reportedSequence=machine.eventSeq;
    report();
  }
}
