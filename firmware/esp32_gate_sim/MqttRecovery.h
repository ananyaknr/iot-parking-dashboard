#pragma once
#include <stdint.h>

// PubSubClient negative states are transport failures, positive states are
// broker refusals. Reassociating Wi-Fi cannot fix credentials or permissions.
struct MqttRecovery {
  uint8_t failures=0;
  void connected() { failures=0; }
  bool failed(int state) {
    if(state>=0) {failures=0;return false;}
    if(++failures<6) return false;
    failures=0;return true;
  }
};
