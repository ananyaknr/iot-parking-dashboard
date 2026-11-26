#include <GateCommon.h>
#include <assert.h>
#include <stdio.h>
using namespace gatev2;
void set(Reading& r,float value) {r.sample(value);r.sample(value);}
Machine ready() {Machine m;m.ready=true;set(m.u1,40);set(m.u2,40);m.update(0);m.update(801);assert(m.state==CLOSED);return m;}
Machine opened() {Machine m=ready();set(m.u1,10);m.update(1000);assert(m.state==OPEN_WAIT && m.arrivals==1);return m;}
int main() {
  {Machine m=ready();m.u1.sample(10);m.update(900);assert(m.state==CLOSED && m.u1.visible()==UNKNOWN);m.u1.sample(10);m.update(1000);assert(m.state==OPEN_WAIT);set(m.u1,40);m.update(1100);m.u2.sample(10);m.update(1200);assert(m.state==OPEN_WAIT);m.u2.sample(10);m.update(1300);assert(m.state==PASSING);set(m.u2,40);m.update(1400);m.update(2199);assert(m.state==PASSING);m.update(2200);assert(m.state==CLOSING && m.completed==0);m.update(2700);assert(m.state==CLOSED && m.completed==1);}
  {Machine m=opened();m.u2.sample(-1);m.update(1100);assert(m.state==HOLD);m.update(99999);assert(m.state==HOLD);assert(!m.reset());set(m.u1,40);set(m.u2,40);assert(m.reset());assert(m.state==BOOT);}
  {Machine m=opened();set(m.u1,40);m.update(1100);set(m.u2,10);m.update(1200);set(m.u1,10);m.update(1300);assert(m.state==HOLD && !strcmp(m.event,"second_vehicle"));}
  {Machine m=opened();set(m.u1,40);set(m.u2,10);m.update(1200);set(m.u2,40);m.update(1300);m.update(2100);assert(m.state==CLOSING);m.u2.sample(10);m.update(2150);assert(m.state==HOLD && m.completed==0);}
  {Machine m=opened();m.cycleStart=UINT32_MAX-100;m.update(20000);assert(m.state==HOLD);}
  {Machine m=ready();m.integrated=true;set(m.u1,10);m.update(1000);assert(m.state==AUTH_WAIT);assert(!m.authorize(2,true,1001));assert(m.authorize(1,false,1001));assert(m.state==HOLD);}
  {Machine m=ready();m.integrated=true;set(m.u1,10);m.update(1000);assert(m.authorize(1,true,1001));assert(m.state==OPEN_WAIT);assert(!m.authorize(1,true,1002));}
  {Frame<8> f;for(const char* p="123456789\n";*p;++p) assert(!f.feed(*p));assert(!f.feed('O'));assert(!f.feed('K'));assert(f.feed('\n'));assert(!strcmp(f.data,"OK"));}
  {uint32_t value;assert(decimal("4294967295",value) && value==UINT32_MAX);assert(!decimal("4294967296",value));assert(!plate("bad|plate"));assert(!vehicle("motorcycle"));}
  {Telemetry t;char good[]="G2|0123456789abcdef0123456789abcdef|100|40.0|40.0|clear|clear|closing|1|0|1|3|4|clearance_confirmed|0";assert(telemetry(good,t));char bad[]="G2|0123456789abcdef0123456789abcdef|100|null|40.0|clear|clear|closing|1|0|1|3|4|clearance_confirmed|0";assert(!telemetry(bad,t));}
  puts("PASS compiled firmware core: cycle, debounce, clearance, obstruction, second vehicle, unknown, timeout/wrap, authorization, frames and validation");
}
