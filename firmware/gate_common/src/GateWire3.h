#pragma once
#include <GateBench.h>
namespace gatewire3 {
inline bool lcdDecode(const char* hex,char* out) {
  size_t n=strlen(hex);if(n<2 || n>32 || n%2) return false;
  for(size_t i=0;i<n;i+=2) {
    uint8_t byte=0;
    for(size_t j=0;j<2;++j) {
      char c=hex[i+j];if(c>='0'&&c<='9') byte=byte*16+c-'0';
      else if(c>='a'&&c<='f') byte=byte*16+c-'a'+10;else return false;
    }
    if(byte<32 || byte>126) return false;
    out[i/2]=char(byte);
  }
  out[n/2]=0;return true;
}
inline bool vehicle(const char* s) {return !strcmp(s,"car")||!strcmp(s,"sportcar")||!strcmp(s,"supercar");}
inline bool deadline(uint32_t now,uint32_t end) {int32_t left=int32_t(end-now);return left>0 && left<=20000;}
struct Telemetry {
  char mode;char boot[33];float u1,u2;gatev2::Zone z1,z2;
  uint32_t uptime,phase,lane,cycle,raw,vibration,reason,minimum,started;
};
inline bool telemetry(char* text,Telemetry& t) {
  char* f[15];if(gatev2::split(text,f,15)!=15 || (strcmp(f[0],"G3") && strcmp(f[0],"A3") && strcmp(f[0],"P3")) || !gatev2::hex(f[1],32)) return false;
  t.mode=f[0][0];strcpy(t.boot,f[1]);
  if(!gatev2::decimal(f[2],t.uptime)||!gatev2::distance(f[3],t.u1)||!gatev2::distance(f[4],t.u2)
    ||!gatev2::decimal(f[7],t.phase)||!gatev2::decimal(f[8],t.lane)||!gatev2::decimal(f[9],t.cycle)
    ||!gatev2::decimal(f[10],t.raw)||!gatev2::decimal(f[11],t.vibration)||!gatev2::decimal(f[12],t.reason)
    ||!gatev2::decimal(f[13],t.minimum)||!gatev2::decimal(f[14],t.started)
    ||t.phase>5||t.lane>3||t.raw>1||t.reason>17||t.minimum<5000||t.minimum>60000) return false;
  int a=-1,b=-1;
  for(int z=0;z<=2;++z) {if(!strcmp(f[5],gatev2::zoneName(gatev2::Zone(z)))) a=z;if(!strcmp(f[6],gatev2::zoneName(gatev2::Zone(z)))) b=z;}
  if(a<0||b<0||(t.u1<0&&a!=0)||(t.u2<0&&b!=0)) return false;
  t.z1=gatev2::Zone(a);t.z2=gatev2::Zone(b);return true;
}
}
