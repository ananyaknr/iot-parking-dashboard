#pragma once
#include <GateCommon.h>

// Local-only entrance/exit preparation. Never encoded as historical G2 passage.
namespace gatebench {
enum Phase { BOOT, CLOSED, AUTH, OPEN, CLOSING, HOLD };
enum Lane { NONE, ENTRANCE, EXIT, MANUAL };
enum Reason { R_BOOT,R_READY,R_ENTRANCE,R_EXIT,R_MANUAL,R_AUTHORIZED,R_CLOSING,
  R_UNKNOWN,R_CONFLICT,R_TIMEOUT,R_OPPOSITE,R_AUTH_TIMEOUT,R_OBSTRUCTION,R_COMPLETE,R_RESET,R_STOP };
struct Controller {
  Phase phase=BOOT;
  Lane lane=NONE;
  uint32_t cycle=0,openedAt=0,startedAt=0,clearAt=0,closingAt=0;
  uint32_t minimumOpenMs=5000,timeoutMs=120000;
  bool clearTiming=false,confirmed=false;
  Reason reason=R_BOOT;
  bool clear(const gatev2::Reading& a,const gatev2::Reading& b,uint32_t now) {
    if(!a.clear() || !b.clear()) {clearTiming=false;return false;}
    if(!clearTiming) {clearTiming=true;clearAt=now;}
    return uint32_t(now-clearAt)>=800;
  }
  void hold(Reason why) {phase=HOLD;reason=why;confirmed=false;clearTiming=false;}
  bool start(Lane which,uint32_t now) {
    if(phase!=CLOSED || cycle==UINT32_MAX) return false;
    ++cycle;lane=which;startedAt=now;confirmed=false;clearTiming=false;
    phase=which==ENTRANCE?AUTH:OPEN;openedAt=now;
    reason=which==ENTRANCE?R_ENTRANCE:which==EXIT?R_EXIT:R_MANUAL;
    return true;
  }
  bool authorize(uint32_t id,uint32_t now) {
    if(phase!=AUTH || cycle!=id || uint32_t(now-startedAt)>=20000) return false;
    phase=OPEN;openedAt=now;reason=R_AUTHORIZED;return true;
  }
  bool confirm(uint32_t id) {
    if(phase!=OPEN || id!=cycle) return false;
    confirmed=true;return true;
  }
  bool close(uint32_t now) {
    if(phase!=OPEN || !confirmed || !clearTiming || uint32_t(now-clearAt)<800
       || uint32_t(now-openedAt)<minimumOpenMs) return false;
    phase=CLOSING;closingAt=now;reason=R_CLOSING;return true;
  }
  void update(const gatev2::Reading& a,const gatev2::Reading& b,uint32_t now) {
    const bool safe=clear(a,b,now);
    if(phase==BOOT) {if(safe) {phase=CLOSED;reason=R_READY;}return;}
    if(phase==HOLD) return;
    if(phase==CLOSED) {
      if(a.cm<0 || b.cm<0) hold(R_UNKNOWN);
      else if(a.detected() && b.detected()) hold(R_CONFLICT);
      else if(a.detected() && b.clear()) start(ENTRANCE,now);
      else if(b.detected() && a.clear()) start(EXIT,now);
      return;
    }
    if(a.cm<0 || b.cm<0) {hold(R_UNKNOWN);return;}
    if(uint32_t(now-startedAt)>=timeoutMs) {hold(R_TIMEOUT);return;}
    if((lane==ENTRANCE && b.detected()) || (lane==EXIT && a.detected())) {
      hold(R_OPPOSITE);return;
    }
    if(phase==AUTH && uint32_t(now-startedAt)>=20000) {hold(R_AUTH_TIMEOUT);return;}
    if(phase==CLOSING) {
      if(!a.clear() || !b.clear()) hold(R_OBSTRUCTION);
      else if(uint32_t(now-closingAt)>=500) {
        phase=CLOSED;lane=NONE;reason=R_COMPLETE;confirmed=false;
      }
    }
    // CLOSE is always an explicit operator step. No timer-only passage claim.
  }
  bool reset() {
    if(phase!=HOLD || !clearTiming) return false;
    phase=BOOT;lane=NONE;confirmed=false;clearTiming=false;reason=R_RESET;return true;
  }
};
}
