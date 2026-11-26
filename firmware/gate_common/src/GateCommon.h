#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

namespace gatev2 {
// This library describes simulation only. It has no pin or actuator API.
enum Zone { UNKNOWN, CLEAR, DETECTED };
enum State { BOOT, CLOSED, AUTH_WAIT, OPEN_WAIT, PASSING, CLOSING, HOLD };
inline const char* zoneName(Zone z) { return z==CLEAR?"clear":z==DETECTED?"detected":"unknown"; }
inline const char* stateName(State s) {
  switch(s) {
    case BOOT:return "boot_wait"; case CLOSED:return "closed";
    case AUTH_WAIT:return "authorization_wait"; case OPEN_WAIT:return "open_wait";
    case PASSING:return "passing"; case CLOSING:return "closing";
    default:return "hold";
  }
}
struct Reading {
  float cm=-1;
  Zone stable=UNKNOWN,candidate=UNKNOWN;
  uint8_t count=0;
  void sample(float value) {
    cm=value;
    if(value<2 || value>400) {cm=-1;stable=candidate=UNKNOWN;count=0;return;}
    Zone next=value<=15?DETECTED:value>=18?CLEAR:stable;
    if(next==UNKNOWN) {candidate=UNKNOWN;count=0;return;}
    if(next==candidate) {if(count<2) ++count;} else {candidate=next;count=1;}
    if(count>=2) stable=next;
  }
  Zone visible() const {return count>=2 && candidate==stable?stable:UNKNOWN;}
  bool clear() const {return visible()==CLEAR && cm>=18;}
  bool detected() const {return visible()==DETECTED && cm<=15;}
};
struct Machine {
  Reading u1,u2;
  State state=BOOT;
  bool integrated=false,ready=false,clearTiming=false,u1Cleared=false;
  uint32_t clearSince=0,cycleStart=0,closingSince=0,arrivals=0,completed=0,eventSeq=0;
  const char* event="boot";
  bool bothClear() const {return u1.clear() && u2.clear();}
  void change(State next,const char* reason) {
    if(state!=next) {state=next;event=reason;++eventSeq;clearTiming=false;}
  }
  bool clearFor(uint32_t now) {
    if(!bothClear()) {clearTiming=false;return false;}
    if(!clearTiming) {clearTiming=true;clearSince=now;}
    return uint32_t(now-clearSince)>=800;
  }
  bool reset() {
    if(state!=HOLD || !bothClear()) return false;
    change(BOOT,"supervised_reset");return true;
  }
  bool authorize(uint32_t arrival,bool allowed,uint32_t now) {
    if(!integrated || state!=AUTH_WAIT || arrival!=arrivals || uint32_t(now-cycleStart)>=20000) return false;
    if(!allowed || u1.cm<0 || u2.cm<0) change(HOLD,"authorization_denied");
    else change(OPEN_WAIT,"authorized");
    return true;
  }
  void update(uint32_t now) {
    switch(state) {
      case BOOT:if(ready && clearFor(now)) change(CLOSED,"ready");break;
      case CLOSED:
        if(u1.cm<0 || u2.cm<0) change(HOLD,"sensor_unknown");
        else if(u2.detected()) change(HOLD,"unexpected_passage");
        else if(u1.detected() && u2.clear()) {
          if(arrivals==UINT32_MAX) {change(HOLD,"counter_exhausted");break;}
          ++arrivals;cycleStart=now;u1Cleared=false;
          change(integrated?AUTH_WAIT:OPEN_WAIT,"arrival");
        }
        break;
      case AUTH_WAIT:case OPEN_WAIT:case PASSING:
        if(uint32_t(now-cycleStart)>=20000) {change(HOLD,"cycle_timeout");break;}
        // A debounce transition is not a missing echo. Only invalid ranging holds here.
        if(u1.cm<0 || u2.cm<0) {change(HOLD,"sensor_unknown");break;}
        if(u1.clear()) u1Cleared=true;
        if(u1Cleared && u1.detected()) {change(HOLD,"second_vehicle");break;}
        if(state==OPEN_WAIT && u2.detected()) change(PASSING,"passage_detected");
        else if(state==PASSING && clearFor(now)) {closingSince=now;change(CLOSING,"clearance_confirmed");}
        break;
      case CLOSING:
        if(!bothClear()) change(HOLD,"closing_obstruction");
        else if(uint32_t(now-closingSince)>=500) {
          if(completed==UINT32_MAX) {change(HOLD,"counter_exhausted");break;}
          ++completed;change(CLOSED,"passage_completed");
        }
        break;
      case HOLD:break; // Supervised RESET only; never force closure on a timeout.
    }
  }
};
inline bool decimal(const char* s,uint32_t& value) {
  if(!s || !*s || strlen(s)>10) return false;
  uint32_t number=0;
  for(;*s;++s) {
    if(*s<'0'||*s>'9' || number>(UINT32_MAX-uint32_t(*s-'0'))/10) return false;
    number=number*10+uint32_t(*s-'0');
  }
  value=number;return true;
}
inline bool hex(const char* s,size_t length) {
  if(!s || strlen(s)!=length) return false;
  for(;*s;++s) if(!((*s>='0'&&*s<='9')||(*s>='a'&&*s<='f'))) return false;
  return true;
}
inline bool plate(const char* s) {
  if(!s || !*s || strlen(s)>16) return false;
  for(;*s;++s) if(!((*s>='A'&&*s<='Z')||(*s>='a'&&*s<='z')||(*s>='0'&&*s<='9')||*s==' '||*s=='-')) return false;
  return true;
}
inline bool vehicle(const char* s) {return s && (!strcmp(s,"car")||!strcmp(s,"supercar")||!strcmp(s,"unknown"));}
// Exact token count; reject empty, extra, control and embedded NUL bytes upstream.
inline uint8_t split(char* text,char** fields,uint8_t maximum) {
  uint8_t count=1;fields[0]=text;
  for(char* p=text;*p;++p) {
    if(*p=='|') {if(count>=maximum || p==fields[count-1]) return 0;*p=0;fields[count++]=p+1;}
    else if(uint8_t(*p)<32 || uint8_t(*p)>126) return 0;
  }
  return *fields[count-1]?count:0;
}
template<size_t N> struct Frame {
  char data[N];size_t size=0;bool bad=false,carriage=false;
  // Caller handles returned complete frame before next byte. Oversized frames drain to newline.
  bool feed(char c) {
    if(c=='\n') {data[size]=0;bool complete=!bad&&size;size=0;bad=carriage=false;return complete;}
    if(carriage) {bad=true;return false;}
    if(c=='\r') {carriage=true;return false;}
    if(uint8_t(c)<32 || uint8_t(c)>126) {bad=true;return false;}
    if(!bad) {if(size<N-1) data[size++]=c;else bad=true;}
    return false;
  }
};
struct Telemetry {
  char boot[33],event[25];float u1,u2;Zone z1,z2;State state;
  uint32_t uptime,arrivals,completed,raw,vibration,sequence,integrated;
};
inline bool distance(const char* s,float& value) {
  if(!strcmp(s,"null")) {value=-1;return true;}
  size_t n=strlen(s);
  if(n<3 || n>5 || s[n-2]!='.' || s[n-1]<'0' || s[n-1]>'9') return false;
  for(size_t i=0;i<n-2;++i) if(s[i]<'0'||s[i]>'9') return false;
  value=float(atof(s));return value>=2 && value<=400;
}
inline bool telemetry(char* text,Telemetry& t) {
  char* f[15];if(split(text,f,15)!=15 || strcmp(f[0],"G2") || !hex(f[1],32)) return false;
  strcpy(t.boot,f[1]);
  if(!decimal(f[2],t.uptime)||!distance(f[3],t.u1)||!distance(f[4],t.u2)
      ||!decimal(f[8],t.arrivals)||!decimal(f[9],t.completed)||!decimal(f[10],t.raw)
      ||!decimal(f[11],t.vibration)||!decimal(f[12],t.sequence)||!decimal(f[14],t.integrated)
      ||t.completed>t.arrivals || t.raw>1 || t.integrated>1) return false;
  int z1=-1,z2=-1,st=-1;
  for(int z=UNKNOWN;z<=DETECTED;++z) {if(!strcmp(f[5],zoneName(Zone(z)))) z1=z;if(!strcmp(f[6],zoneName(Zone(z)))) z2=z;}
  for(int s=BOOT;s<=HOLD;++s) if(!strcmp(f[7],stateName(State(s)))) st=s;
  if(z1<0||z2<0||st<0 || strlen(f[13])>=sizeof(t.event)) return false;
  for(const char* p=f[13];*p;++p) if(!((*p>='a'&&*p<='z')||*p=='_')) return false;
  t.z1=Zone(z1);t.z2=Zone(z2);t.state=State(st);strcpy(t.event,f[13]);
  if((t.u1<0 && t.z1!=UNKNOWN)||(t.u2<0 && t.z2!=UNKNOWN)) return false;
  if((t.z1==DETECTED && t.u1>18.05f)||(t.z2==DETECTED && t.u2>18.05f)
      ||(t.z1==CLEAR && t.u1<14.95f)||(t.z2==CLEAR && t.u2<14.95f)) return false;
  if(t.state==AUTH_WAIT && !t.integrated) return false;
  if((t.state==AUTH_WAIT||t.state==OPEN_WAIT||t.state==PASSING||t.state==CLOSING) && t.arrivals<=t.completed) return false;
  if(t.state==CLOSING && !(t.z1==CLEAR && t.z2==CLEAR && t.u1>=18 && t.u2>=18)) return false;
  return true;
}
}
