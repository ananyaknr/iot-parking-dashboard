#include <GateWire3.h>
#include <assert.h>
#include <stdio.h>
int main() {
  char lcd[17];assert(gatewire3::lcdDecode("544553547c504c415445",lcd));assert(!strcmp(lcd,"TEST|PLATE"));
  assert(!gatewire3::lcdDecode("00",lcd));assert(!gatewire3::lcdDecode("7f",lcd));assert(!gatewire3::lcdDecode("abc",lcd));
  assert(gatewire3::vehicle("sportcar"));assert(!gatewire3::vehicle("unknown"));
  assert(gatewire3::deadline(0xffffff00UL,1000));assert(!gatewire3::deadline(1000,1000));assert(!gatewire3::deadline(1001,1000));
  gatewire3::Telemetry t;
  char good[]="G3|0123456789abcdef0123456789abcdef|10000|10.0|40.0|detected|clear|2|1|1|1|0|2|5000|9900";
  assert(gatewire3::telemetry(good,t));assert(t.phase==2 && t.lane==1 && t.cycle==1);
  char bad[]="G3|0123456789abcdef0123456789abcdef|10000|10.0|null|detected|clear|2|1|1|1|0|2|5000|9900";
  assert(!gatewire3::telemetry(bad,t));
  puts("PASS G3: wire schema, sportcar, printable ASCII encoding, invalid bytes, expiry/wrap");
}
