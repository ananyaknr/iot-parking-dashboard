#include <GateBench.h>
#include <assert.h>
#include <stdio.h>
using namespace gatebench;
void set(gatev2::Reading& r,float value) {r.sample(value);r.sample(value);}
struct Rig {
  Controller c;gatev2::Reading a,b;
  Rig() {c.automatic=c.inferredPolicy=true;set(a,25);set(b,25);c.update(a,b,0);c.update(a,b,2000);}
  void open(bool exit=false) {
    set(exit?b:a,10);c.update(a,b,2100);
    if(!exit) {assert(!c.eligible);assert(!c.authorize(2,2101));assert(c.authorize(1,2200));}
    assert(c.phase==OPEN && c.eligible);assert(!c.authorize(1,2201));
  }
  void finish(uint32_t clearAt=8000) {
    set(a,25);set(b,25);c.update(a,b,clearAt);c.update(a,b,clearAt+1999);assert(c.phase==OPEN);
    c.update(a,b,clearAt+2000);assert(c.phase==CLOSING);
    c.update(a,b,clearAt+2499);assert(c.phase==CLOSING);
    c.update(a,b,clearAt+2500);assert(c.phase==CLOSED);
  }
};
int main() {
  for(int i=0;i<2;++i) {
    bool exit=i==1;
    Rig r;r.open(exit);r.c.update(r.a,r.b,7000);assert(r.c.eligible); // normal own-lane presence
    assert(!r.c.start(exit?ENTRANCE:EXIT,7001));r.finish();assert(r.c.reason==R_INFERRED);
  }
  {Rig r;r.open();set(r.a,-1);r.c.update(r.a,r.b,3000);assert(r.c.disqualified);
   r.finish();assert(r.c.reason==R_UNVERIFIED && !r.c.eligible);}
  {Rig r;r.open();set(r.a,25);r.c.update(r.a,r.b,3000);
   set(r.a,10);r.c.update(r.a,r.b,3100);assert(r.c.disqualified);
   r.finish();assert(r.c.reason==R_UNVERIFIED);}
  {Rig r;r.open();r.c.hold(R_STOP);assert(r.c.disqualified && !r.c.eligible);
   set(r.a,25);r.c.update(r.a,r.b,4000);assert(r.c.reset());assert(!r.c.eligible && r.c.disqualified);}
  {Rig r;r.open();set(r.b,10);r.c.update(r.a,r.b,3000);assert(r.c.phase==HOLD && !r.c.eligible);}
  {Rig r;r.open();set(r.a,25);r.c.update(r.a,r.b,3000);r.c.update(r.a,r.b,7200);
   assert(r.c.phase==CLOSING);set(r.a,-1);r.c.update(r.a,r.b,7300);
   assert(r.c.phase==HOLD && r.c.disqualified && !r.c.eligible);}
  {Rig r;r.open();Controller restart;restart.automatic=restart.inferredPolicy=true;
   assert(!restart.authorize(r.c.cycle,3000) && !restart.eligible);}
  {Rig r;r.c.inferredPolicy=false;r.open();r.finish();assert(r.c.reason==R_UNVERIFIED);}
  puts("PASS inferred controller: clean entrance/exit, initial presence, permanent fault latch, STOP/reset/conflict, closing fault, duplicate/restart, policy off");
}
