#include <Arduino.h>
#include <SoftwareSerial.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Bench prototype: no Servo library, no D9 output, no physical actuation.
const uint8_t U1_TRIG=2,U1_ECHO=3,U2_TRIG=4,U2_ECHO=5,VIB=6;
const float DETECT_CM=15.0f,CLEAR_CM=18.0f; // provisional, calibrate actual geometry
const unsigned long CLEAR_DWELL=800, CYCLE_TIMEOUT=20000, CLOSE_SIM_MS=500;
SoftwareSerial gateway(10,11);
LiquidCrystal_I2C lcd27(0x27,16,2), lcd3f(0x3f,16,2);
LiquidCrystal_I2C *lcd=nullptr;

enum Zone { UNKNOWN, CLEAR, DETECTED };
enum Gate { BOOT, CLOSED, OPEN_WAIT, PASSING, CLOSING, HOLD };
struct Reading {
  float cm=-1;
  Zone state=UNKNOWN, candidate=UNKNOWN;
  byte consecutive=0;
};
Reading u1,u2;
Gate gate=BOOT;
unsigned long lastTrigger=0,lastReport=0,cycleStart=0,clearSince=0,closingSince=0;
unsigned long arrivalCount=0,completedCount=0;
bool clearTiming=false,nextU1=true;
int vibRaw=HIGH;
unsigned long vibTransitions=0,lastVibTransition=0;
bool displayOverride=false;
unsigned long displayAt=0;
char serialLine[48],gatewayLine[48];
byte serialLen=0,gatewayLen=0;
bool serialOverflow=false,gatewayOverflow=false;

const char* zoneName(Zone s) {
  return s==CLEAR?"clear":s==DETECTED?"detected":"unknown";
}
const char* gateName() {
  switch(gate) {
    case BOOT:return "boot_wait";
    case CLOSED:return "closed";
    case OPEN_WAIT:return "open_wait";
    case PASSING:return "passing";
    case CLOSING:return "closing";
    default:return "hold";
  }
}
void row(byte n,const char *s) {
  if (!lcd) return;
  lcd->setCursor(0,n);
  byte i=0;
  while(i<16 && s[i]) { lcd->print(s[i]); ++i; }
  while(i++<16) lcd->print(' ');
}
void showState() {
  if(displayOverride) return;
  switch(gate) {
    case BOOT:row(0,"CHECK SENSORS");row(1,"SIMULATION");break;
    case CLOSED:row(0,"WAITING FOR CAR");row(1,"GATE CLOSED SIM");break;
    case OPEN_WAIT:row(0,"READING PLATE...");row(1,"GATE OPEN SIM");break;
    case PASSING:row(0,"VEHICLE PASSING");row(1,"GATE OPEN SIM");break;
    case CLOSING:row(0,"CLEAR CONFIRMED");row(1,"CLOSING SIM");break;
    case HOLD:row(0,"CHECK GATE ZONE");row(1,"HOLD OPEN SIM");break;
  }
}
void changeGate(Gate next) {
  if(gate==next) return;
  gate=next;
  if(next==CLOSED || next==HOLD || next==OPEN_WAIT) displayOverride=false;
  showState();
}
bool i2cPresent(byte address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission()==0;
}
float distanceCm(byte trig,byte echo) {
  digitalWrite(trig,LOW);delayMicroseconds(2);
  digitalWrite(trig,HIGH);delayMicroseconds(10);digitalWrite(trig,LOW);
  unsigned long us=pulseIn(echo,HIGH,25000UL);
  if(!us) return -1;
  float cm=us*0.0343f/2.0f;
  return cm>=2 && cm<=400?cm:-1;
}
void sample(Reading &r,byte trig,byte echo) {
  r.cm=distanceCm(trig,echo);
  if(r.cm<0) {r.state=UNKNOWN;r.candidate=UNKNOWN;r.consecutive=0;return;}
  Zone next=r.cm<=DETECT_CM?DETECTED:r.cm>=CLEAR_CM?CLEAR:r.state;
  if(next==r.candidate) {if(r.consecutive<2) ++r.consecutive;}
  else {r.candidate=next;r.consecutive=1;}
  // Do not continue reporting clear while a possible obstruction is being confirmed.
  if(next!=r.state && next!=CLEAR) r.state=UNKNOWN;
  if(r.consecutive>=2) r.state=next;
}
bool bothClear() {
  return u1.state==CLEAR && u2.state==CLEAR
    && u1.cm>=CLEAR_CM && u2.cm>=CLEAR_CM;
}
bool clearFor(unsigned long now) {
  if(!bothClear()) {clearTiming=false;return false;}
  if(!clearTiming) {clearTiming=true;clearSince=now;}
  return now-clearSince>=CLEAR_DWELL;
}
void updateGate(unsigned long now) {
  switch(gate) {
    case BOOT:
      if(clearFor(now)) {clearTiming=false;changeGate(CLOSED);}
      break;
    case CLOSED:
      if(u1.state==DETECTED && u1.cm<=DETECT_CM && u2.state==CLEAR && u2.cm>=CLEAR_CM) {
        ++arrivalCount;cycleStart=now;clearTiming=false;changeGate(OPEN_WAIT);
      }
      break;
    case OPEN_WAIT:
      if(now-cycleStart>=CYCLE_TIMEOUT || u1.cm<0 || u2.cm<0)
        changeGate(HOLD);
      else if(u2.state==DETECTED) {clearTiming=false;changeGate(PASSING);}
      break;
    case PASSING:
      if(now-cycleStart>=CYCLE_TIMEOUT || u1.cm<0 || u2.cm<0)
        changeGate(HOLD);
      else if(clearFor(now)) {closingSince=now;changeGate(CLOSING);}
      break;
    case CLOSING:
      if(!bothClear()) {clearTiming=false;changeGate(HOLD);}
      else if(now-closingSince>=CLOSE_SIM_MS) {++completedCount;clearTiming=false;changeGate(CLOSED);}
      break;
    case HOLD:
      // Explicit supervised USB reset only; no forced timeout closure.
      break;
  }
}
void checkVibration() {
  int value=digitalRead(VIB);
  unsigned long now=millis();
  if(value!=vibRaw) {
    vibRaw=value;
    if(now-lastVibTransition>=50) {++vibTransitions;lastVibTransition=now;}
  }
}
bool safePlate(const char *s) {
  size_t n=strlen(s);
  if(n==0 || n>16) return false;
  for(size_t i=0;i<n;++i) {
    char c=s[i];
    if(!((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c==' '||c=='-')) return false;
  }
  return true;
}
void command(char *line,bool usb) {
  if(usb && strcmp(line,"RESET")==0) {
    if(gate==HOLD && bothClear()) {clearTiming=false;displayOverride=false;changeGate(BOOT);}
    else Serial.println(F("RESET_REFUSED"));
    return;
  }
  if(strncmp(line,"LCD|",4)!=0) return;
  char *plate=line+4,*sep=strchr(plate,'|');
  if(!sep) return;
  *sep='\0';
  const char *type=sep+1;
  if(!lcd || !safePlate(plate) ||
     (strcmp(type,"car") && strcmp(type,"supercar") && strcmp(type,"unknown"))) {
    if(!usb) gateway.println(F("ACK|LCD|REJECTED"));
    Serial.println(F("LCD_REJECTED"));
    return;
  }
  row(0,plate);
  row(1,!strcmp(type,"car")?"TYPE: CAR":!strcmp(type,"supercar")?"TYPE: SUPERCAR":"TYPE: UNKNOWN");
  displayAt=millis();displayOverride=true;
  if(!usb) gateway.println(F("ACK|LCD|OK"));
  Serial.println(F("LCD_UPDATED"));
}
void readCommands(Stream &port,char *buffer,byte &len,bool &overflow,bool usb) {
  while(port.available()) {
    char c=port.read();
    if(c=='\n') {
      if(!overflow && len) {buffer[len]='\0';command(buffer,usb);}
      len=0;overflow=false;
    } else if(c!='\r' && !overflow) {
      if(len<47) buffer[len++]=c;else overflow=true;
    }
  }
}
void printDistance(Print &out,float cm) {
  if(cm<0) out.print(F("null"));else out.print(cm,1);
}
void report(Print &out) {
  out.print(F("{\"node\":\"uno\",\"schema_version\":2,\"mode\":\"gate_sim\",\"u1_distance_cm\":"));
  printDistance(out,u1.cm);
  out.print(F(",\"u2_distance_cm\":"));printDistance(out,u2.cm);
  out.print(F(",\"u1_state\":\""));out.print(zoneName(u1.state));
  out.print(F("\",\"u2_state\":\""));out.print(zoneName(u2.state));
  out.print(F("\",\"gate_sim_state\":\""));out.print(gateName());
  out.print(F("\",\"servo_enabled\":false,\"arrival_count\":"));out.print(arrivalCount);
  out.print(F(",\"completed_count\":"));out.print(completedCount);
  out.print(F(",\"vibration_raw\":"));out.print(vibRaw);
  out.print(F(",\"vibration_transition_count\":"));out.print(vibTransitions);
  out.println(F("}"));
}
void setup() {
  Serial.begin(9600);gateway.begin(9600);gateway.listen();
  pinMode(U1_TRIG,OUTPUT);pinMode(U1_ECHO,INPUT);
  pinMode(U2_TRIG,OUTPUT);pinMode(U2_ECHO,INPUT);
  digitalWrite(U1_TRIG,LOW);digitalWrite(U2_TRIG,LOW);
  pinMode(VIB,INPUT_PULLUP);vibRaw=digitalRead(VIB);
  Wire.begin();
  if(i2cPresent(0x27)) lcd=&lcd27;
  else if(i2cPresent(0x3f)) lcd=&lcd3f;
  if(lcd) {lcd->init();lcd->backlight();Serial.println(F("LCD_FOUND"));}
  else Serial.println(F("LCD_NOT_FOUND"));
  showState();Serial.println(F("GATE_SIM_ONLY; SERVO DISABLED"));
}
void loop() {
  checkVibration();
  readCommands(gateway,gatewayLine,gatewayLen,gatewayOverflow,false);
  readCommands(Serial,serialLine,serialLen,serialOverflow,true);
  unsigned long now=millis();
  if(now-lastTrigger>=75) {
    lastTrigger=now;
    if(nextU1) sample(u1,U1_TRIG,U1_ECHO);else sample(u2,U2_TRIG,U2_ECHO);
    nextU1=!nextU1;
  }
  checkVibration();
  updateGate(millis());
  if(displayOverride && millis()-displayAt>=15000) {displayOverride=false;showState();}
  if(millis()-lastReport>=1000) {
    lastReport=millis();report(Serial);report(gateway);
  }
}
