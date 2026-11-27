#pragma once
#include <GateBench.h>
namespace gatebench {
enum Motion { NO_MOTION, MOVE_OPEN, MOVE_CLOSE, REOPEN };
// Commanded movement only; an SG90 provides no measured position.
struct Actuator {
  Phase previous=BOOT;
  Motion update(Phase next) {
    Motion motion=NO_MOTION;
    if(next!=previous) {
      if(next==OPEN) motion=MOVE_OPEN;
      else if(next==CLOSING) motion=MOVE_CLOSE;
      else if(next==HOLD && previous==CLOSING) motion=REOPEN;
      previous=next;
    }
    return motion;
  }
};
}
