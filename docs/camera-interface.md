# Camera teammate integration

Publish UTF-8 newline-free JSON to `parking/camera/result`, MQTT TCP 1883 at the PC's current LAN IP from `.env`. Authentication is required; share the MQTT credentials privately, never in source control. The broker ACL permits this topic. Use a unique client ID and non-retained messages. QoS 1 is supported. A repeated observation must represent a new camera result; do not replay cached results as new detections.

Required schema (example only, not measured camera data):

```json
{"node":"camera","slot":"A1","occupied":true,"confidence":0.93}
```

- `node`: exactly `camera`.
- `slot`: `A1` or `M1`.
- `occupied`: JSON boolean, or null when unknown.
- `confidence`: number in [0,1], or null when unavailable.
- No additional keys in this initial contract. Capture timestamps are assigned in UTC by the receiving backend. Source capture timestamps can be added in a coordinated schema revision.

The backend stores camera results as `parking_camera`, retains history for seven days, and marks camera data stale after ten seconds without a valid new message. Dashboard/API camera results are advisory and do not override ultrasonic occupancy or enable M1 allocation. The current interface represents one camera source and its latest slot result, not a multi-camera tracker.

For synthetic tests use `parking/test/camera/result` with the isolated test backend and `sensor_test` bucket. No actual camera implementation or physical camera test is claimed.
