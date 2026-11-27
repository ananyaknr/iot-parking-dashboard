#include "../MqttRecovery.h"
#include <assert.h>
int main() {
  MqttRecovery r;
  for(int i=0;i<5;++i) assert(!r.failed(-2));
  assert(r.failed(-2));
  assert(!r.failed(-2));
  r.connected();
  for(int i=0;i<5;++i) assert(!r.failed(-4));
  assert(!r.failed(4)); // Bad credentials must not cause Wi-Fi churn.
  for(int i=0;i<5;++i) assert(!r.failed(-2));
  assert(r.failed(-3));
  r.connected();
  assert(r.failures==0);
}
