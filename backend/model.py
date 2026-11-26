"""Telemetry validation and current-state projection; no I/O or external dependencies."""
import json
import math
from dataclasses import dataclass, field

TOPICS = {
    "parking/node/telemetry": "uno",
    "parking/gateway/telemetry": "esp32",
    "parking/camera/result": "camera",
}
RANGES = {
    "uno": {"a1_distance_cm": (2, 400), "m1_distance_cm": (2, 400)},
    "esp32": {"temperature_c": (-40, 80), "humidity_pct": (0, 100),
              "light_raw": (0, 4095), "gas_raw": (0, 4095)},
    "camera": {"confidence": (0, 1)},
}
SCHEMAS = {
    "uno": {"node", "a1_distance_cm", "m1_distance_cm", "a1_occupied", "m1_occupied",
            "vibration", "vibration_count", "vibration_status"},
    "esp32": {"node", "temperature_c", "humidity_pct", "light_raw", "gas_raw", "gas_status"},
    "camera": {"node", "slot", "occupied", "confidence"},
}

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

def validate(topic, payload):
    source = TOPICS.get(topic)
    if source is None:
        raise ValueError("unexpected topic")
    if len(payload) > 2048:
        raise ValueError("payload exceeds 2048 bytes")
    message = json.loads(payload, object_pairs_hook=unique_object,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(message, dict) or message.get("node") != source:
        raise ValueError("source/topic mismatch")
    if set(message) != SCHEMAS[source]:
        raise ValueError("schema keys differ")
    for name, (low, high) in RANGES[source].items():
        value = message[name]
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"invalid {name}")
        if name.endswith("_raw") and type(value) is not int:
            raise ValueError(f"{name} must be an integer")
    if source == "uno":
        for slot in ("a1", "m1"):
            occupied = message[f"{slot}_occupied"]
            distance = message[f"{slot}_distance_cm"]
            if occupied is not None and type(occupied) is not bool:
                raise ValueError("occupancy must be boolean or null")
            if distance is None and occupied is not None:
                raise ValueError("occupancy without valid distance")
            # Firmware uses 15/18 cm hysteresis and prints one decimal place.
            # Inside the band either prior state is legitimate. Allow half a
            # display unit at each threshold for wire-format rounding.
            if distance is not None and ((occupied is False and distance < 14.95)
                                         or (occupied is True and distance > 18.05)):
                raise ValueError("occupancy contradicts distance thresholds")
        if message["m1_distance_cm"] is not None or message["m1_occupied"] is not None:
            raise ValueError("M1 is not installed in this deployment")
        if (message["vibration"] is not None or message["vibration_count"] is not None
                or message["vibration_status"] != "not_installed"):
            raise ValueError("vibration is not installed")
    elif source == "camera":
        if message["slot"] not in ("A1", "M1"):
            raise ValueError("camera slot must be A1 or M1")
        if message["occupied"] is not None and type(message["occupied"]) is not bool:
            raise ValueError("camera occupancy must be boolean or null")
    elif message["gas_status"] != "unconditioned_or_uncalibrated":
        raise ValueError("unsupported gas status")
    return source, message

@dataclass
class Source:
    name: str
    message: dict = field(default_factory=dict)
    last_valid: float | None = None
    last_received: float | None = None
    payload_valid: bool = False

    def accept(self, message, now):
        if self.last_received is not None and now <= self.last_received:
            return False
        self.message = dict(message)
        self.last_valid = now
        self.last_received = now
        self.payload_valid = True
        return True

    def reject(self, now):
        if self.last_received is not None and now <= self.last_received:
            return False
        # Invalidate the current view immediately; never keep displaying an old valid reading.
        self.message = {}
        self.last_received = now
        self.payload_valid = False

    def snapshot(self, now, stale_after=10):
        age = None if self.last_valid is None else max(0.0, now - self.last_valid)
        fresh = age is not None and age < stale_after
        usable = fresh and self.payload_valid
        result = {"fresh": fresh, "payload_valid": self.payload_valid,
                  "availability_state": 1 if usable else 0,
                  "received_recently": self.last_received is not None and now - self.last_received < stale_after}
        if age is not None:
            result["age_seconds"] = float(age)
        for name in RANGES[self.name]:
            value = self.message.get(name)
            valid = usable and value is not None
            result[f"{name}_valid"] = bool(valid)
            if valid:
                result[name] = int(value) if name.endswith("_raw") else float(value)
        if self.name == "uno":
            value = self.message.get("a1_occupied")
            valid = usable and value is not None and result["a1_distance_cm_valid"]
            result["a1_occupied_valid"] = bool(valid)
            result["a1_state"] = (2 if value else 1) if valid else 0
            result["a1_allocation_eligible"] = bool(valid and not value)
            if valid:
                result["a1_occupied"] = value
            result.update(m1_state=3, m1_installed=False, m1_occupied_valid=False,
                          m1_allocation_eligible=False, vibration_installed=False,
                          vibration_status="not_installed")
        elif self.name == "camera":
            occupied = self.message.get("occupied")
            valid = usable and occupied is not None
            result["occupied_valid"] = bool(valid)
            result["camera_state"] = (2 if occupied else 1) if valid else 0
            result["slot"] = self.message.get("slot", "Unknown")
            if valid:
                result["occupied"] = occupied
            result["allocation_eligible"] = False  # advisory only; no fusion with ultrasonic
        else:
            result["gas_status"] = "unconditioned_or_uncalibrated"
        return result
