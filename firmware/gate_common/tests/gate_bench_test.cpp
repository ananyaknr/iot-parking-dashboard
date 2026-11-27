#include <GateBench.h>
#include <assert.h>
#include <stdio.h>
using namespace gatebench;
void set(gatev2::Reading& r,float cm) {r.sample(cm);r.sample(cm);}
struct Rig {
  Controller c;gatev2::Reading a,b;
  Rig() {set(a,40);set(b,40);c.update(a,b,0);c.update(a,b,800);assert(c.phase==CLOSED);}
};
int main() {
  {Rig r;set(r.a,10);r.c.update(r.a,r.b,1000);assert(r.c.phase==AUTH);
   assert(!r.c.authorize(2,1001));assert(r.c.authorize(1,1001));assert(!r.c.authorize(1,1002));
   set(r.a,40);r.c.update(r.a,r.b,1100);assert(!r.c.close(9000));
   assert(r.c.confirm(1));r.c.update(r.a,r.b,2000);assert(!r.c.close(6000));
   assert(r.c.close(6001));r.c.update(r.a,r.b,6501);assert(r.c.phase==CLOSED);}
  {Rig r;set(r.b,10);r.c.update(r.a,r.b,1000);assert(r.c.phase==OPEN && r.c.lane==EXIT);
   assert(!r.c.start(ENTRANCE,1001));assert(!r.c.confirm(2));r.c.update(r.a,r.b,120999);
   assert(r.c.phase==OPEN);r.c.update(r.a,r.b,121000);assert(r.c.phase==HOLD);}
  {Rig r;set(r.a,10);set(r.b,10);r.c.update(r.a,r.b,1000);assert(r.c.phase==HOLD);}
  {Rig r;assert(r.c.start(MANUAL,1000));set(r.a,-1);r.c.update(r.a,r.b,1100);assert(r.c.phase==HOLD);}
  {Rig r;assert(r.c.start(MANUAL,1000));r.c.update(r.a,r.b,1100);assert(r.c.confirm(1));
   r.c.update(r.a,r.b,6000);assert(r.c.close(6000));r.a.sample(10);
   r.c.update(r.a,r.b,6001);assert(r.c.phase==HOLD);}
  {Rig r;set(r.a,10);r.c.update(r.a,r.b,1000);assert(!r.c.authorize(1,21000));
   r.c.update(r.a,r.b,21000);assert(r.c.phase==HOLD);}
  {Rig r;uint32_t start=UINT32_MAX-1000;assert(r.c.start(MANUAL,start));
   r.c.update(r.a,r.b,start+1);assert(r.c.confirm(1));r.c.update(r.a,r.b,3998);
   assert(!r.c.close(3998));assert(r.c.close(3999));}
  puts("PASS bench: authorized entrance, automatic local exit, min-open, explicit confirmation, conflict, obstruction, expiry, wrap");
}
