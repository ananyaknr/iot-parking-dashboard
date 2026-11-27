#include <Arduino.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <GateCommon.h>
#include <GateBench.h>
#include <Servo.h>
#include <util/atomic.h>
using namespace gatev2;
// Default restoration build NEVER attaches D9. Automatic physical output has
// no code path; a later supervised manual build requires this explicit opt-in.
#ifndef GATE_MANUAL_SERVO_ENABLED
#define GATE_MANUAL_SERVO_ENABLED 0
#endif
Servo barrier;
gatebench::Controller bench;
bool localBench=false,servoArmed=false,manualMovement=false;
uint8_t closedAngle=10,openAngle=80;
const uint8_t U1_TRIG=2,U1_ECHO=3,U2_TRIG=4,U2_ECHO=5,VIB=6;
const bool INTEGRATED_MODE=false; // Enable only after teammate contract agreement.
SoftwareSerial gateway(10,11);
LiquidCrystal_I2C lcd27(0x27,16,2),lcd3f(0x3f,16,2);
LiquidCrystal_I2C* lcd=nullptr;
Machine machine;
char bootId[33]="";
Frame<48> usbFrame;
Frame<96> uartFrame;
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
    case gatebench::R_CLOSING:return F("supervised_close");
    case gatebench::R_UNKNOWN:return F("sensor_unknown");
    case gatebench::R_CONFLICT:return F("competing_lanes");
    case gatebench::R_TIMEOUT:return F("cycle_timeout");
    case gatebench::R_OPPOSITE:return F("opposite_lane");
    case gatebench::R_AUTH_TIMEOUT:return F("auth_timeout");
    case gatebench::R_OBSTRUCTION:return F("obstruction");
    case gatebench::R_COMPLETE:return F("bench_completed");
    case gatebench::R_RESET:return F("reset");
    case gatebench::R_STOP:return F("operator_stop");
    default:return F("boot");
  }
}
void showState() {
  if(displayOverride) return;
  if(localBench) {
    rowFlash(0,F("LOCAL BENCH ONLY"));rowFlash(1,benchReason());return;
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
  Serial.print('|');Serial.print(benchReason());Serial.print(F("|servo="));Serial.print(servoArmed?1:0);
  Serial.print(F("|automatic_physical=0|minimum_ms="));Serial.println(bench.minimumOpenMs);
}
bool localCommand(char* text) {
  if(!strcmp_P(text,PSTR("SENSORS?"))) {
    Serial.print(F("SENSOR_DIAG|U1="));Serial.print(machine.u1.cm,1);
    Serial.print(F("|U2="));Serial.print(machine.u2.cm,1);
    Serial.print(F("|LCD="));Serial.print(lcd?1:0);
    Serial.print(F("|UART_SESSION="));Serial.println(machine.ready?1:0);return true;
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
  if(!usb && count==2 && !strcmp(fields[0],"S2") && hex(fields[1],32)) {
    if(!machine.ready) {strcpy(bootId,fields[1]);machine.ready=true;}
    return;
  }
  if(usb || localBench || count<2 || !hex(fields[1],8)) return;
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
    rowFlash(1,test?(!strcmp(type,"car")?F("TEST CAR"):!strcmp(type,"supercar")?F("TEST SUPERCAR"):F("TEST UNKNOWN")):
        (!strcmp(type,"car")?F("TYPE: CAR"):!strcmp(type,"supercar")?F("TYPE: SUPERCAR"):F("TYPE: UNKNOWN")));
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
    if(frame.feed(char(port.read()))) command(frame.data,usb);
  }
}
void reportTo(Print& out,uint8_t raw,uint32_t transitions) {
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

void setup() {
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
  showState();Serial.println(F("INTEGRATED_RESTORED; SERVO DETACHED; AUTO PHYSICAL DISABLED"));
  Serial.print(F("MANUAL_SERVO_BUILD|"));Serial.println(GATE_MANUAL_SERVO_ENABLED);
  Serial.print(F("CYCLE_TIMEOUT_MS|"));Serial.println(machine.cycleTimeoutMs);
}
void loop() {
  readCommands(gateway,uartFrame,false);readCommands(Serial,usbFrame,true);
  uint32_t now=millis();
  if(!machine.ready && uint32_t(now-lastHello)>=500) {gateway.println(F("HELLO2"));lastHello=now;}
  if(uint32_t(now-lastTrigger)>=75) {
    lastTrigger=now;
    if(nextU1) machine.u1.sample(distanceCm(U1_TRIG,U1_ECHO));else machine.u2.sample(distanceCm(U2_TRIG,U2_ECHO));
    nextU1=!nextU1;
  }
  if(localBench) {
    gatebench::Phase before=bench.phase;
    bench.update(machine.u1,machine.u2,millis());
    if(before!=bench.phase) {
      if(bench.phase==gatebench::HOLD && servoArmed && manualMovement) {
        // Unknown/obstructed closing reopens the supervised manual cycle only.
        barrier.write(openAngle);
      }
      if(bench.phase==gatebench::CLOSED) manualMovement=false;
      benchReport();showState();
    }
  } else machine.update(millis());
  if(displayOverride && (machine.arrivals!=displayArrival || machine.eventSeq!=displayEvent
       || uint32_t(millis()-displayAt)>=15000)) {displayOverride=false;showState();}
  if(displayEvent!=machine.eventSeq) {displayEvent=machine.eventSeq;displayOverride=false;showState();}
  static uint32_t reportedSequence=UINT32_MAX;
  if(machine.ready && (machine.eventSeq!=reportedSequence || uint32_t(millis()-lastReport)>=1000)) {
    lastReport=millis();reportedSequence=machine.eventSeq;
    if(localBench) benchReport();else report();
  }
}
