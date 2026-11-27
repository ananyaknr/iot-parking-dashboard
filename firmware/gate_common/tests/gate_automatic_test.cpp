#include <GateActuator.h>
#include <assert.h>
#include <stdio.h>
using namespace gatebench;
void set(gatev2::Reading& r,float cm) {r.sample(cm);r.sample(cm);}
struct Rig {
  Controller c;gatev2::Reading a,b;
  Rig() {c.automatic=true;set(a,25);set(b,25);c.update(a,b,0);c.update(a,b,2000);assert(c.phase==CLOSED);}
  void exit() {set(b,10);c.update(a,b,2100);assert(c.phase==OPEN && c.lane==EXIT);}
};
int main() {
  {Rig r;set(r.a,10);r.c.update(r.a,r.b,2100);assert(r.c.phase==AUTH);
   assert(!r.c.authorize(2,2200));assert(r.c.authorize(1,2200));assert(!r.c.authorize(1,2201));
   assert(!r.c.start(EXIT,2201));assert(r.c.cycle==1);
   set(r.a,25);r.c.update(r.a,r.b,2300);r.c.update(r.a,r.b,7199);assert(r.c.phase==OPEN);
   r.c.update(r.a,r.b,7200);assert(r.c.phase==CLOSING);
   r.c.update(r.a,r.b,7700);assert(r.c.phase==CLOSED && r.c.reason==R_UNVERIFIED && !r.c.confirmed);}
  {Rig r;r.exit();r.c.update(r.a,r.b,9000);assert(r.c.phase==OPEN);
   set(r.b,25);r.c.update(r.a,r.b,9100);r.c.update(r.a,r.b,11099);assert(r.c.phase==OPEN);
   r.c.update(r.a,r.b,11100);assert(r.c.phase==CLOSING);
   r.b.sample(10);r.c.update(r.a,r.b,11101);assert(r.c.phase==HOLD);}
  {Rig r;r.exit();set(r.b,25);r.c.update(r.a,r.b,8000);
   set(r.b,-1);r.c.update(r.a,r.b,9999);assert(r.c.phase==OPEN && !r.c.clearTiming);
   set(r.b,25);r.c.update(r.a,r.b,10000);r.c.update(r.a,r.b,11999);assert(r.c.phase==OPEN);
   r.c.update(r.a,r.b,12000);assert(r.c.phase==CLOSING);
   set(r.a,-1);r.c.update(r.a,r.b,12001);assert(r.c.phase==HOLD);}
  {Rig r;r.exit();set(r.b,-1);r.c.update(r.a,r.b,122100);assert(r.c.phase==HOLD && r.c.reason==R_TIMEOUT);}
  {Rig r;set(r.a,10);r.c.update(r.a,r.b,2100);assert(!r.c.authorize(1,22100));
   r.c.update(r.a,r.b,22100);assert(r.c.phase==HOLD);}
  {Actuator a;assert(a.update(BOOT)==NO_MOTION);assert(a.update(CLOSED)==NO_MOTION);
   assert(a.update(AUTH)==NO_MOTION);assert(a.update(OPEN)==MOVE_OPEN);assert(a.update(OPEN)==NO_MOTION);
   assert(a.update(CLOSING)==MOVE_CLOSE);assert(a.update(HOLD)==REOPEN);assert(a.update(HOLD)==NO_MOTION);
   Actuator restarted;assert(restarted.update(BOOT)==NO_MOTION);assert(restarted.update(CLOSED)==NO_MOTION);}
  {Rig r;r.exit();assert(r.c.confirm(1));set(r.b,25);r.c.update(r.a,r.b,8000);
   r.c.update(r.a,r.b,10000);r.c.update(r.a,r.b,10500);assert(r.c.reason==R_UNVERIFIED);}
  {Rig r;uint32_t start=UINT32_MAX-1000;assert(r.c.start(MANUAL,start));
   r.c.update(r.a,r.b,start+1);r.c.update(r.a,r.b,3998);assert(r.c.phase==OPEN);
   r.c.update(r.a,r.b,3999);assert(r.c.phase==CLOSING);}
  puts("PASS autonomous: entrance authorization/dedup, local exit, min-open/clearance, obstruction/invalid, timeout, restart actuator safety, ambiguous passage, millis wrap");
}
