# Infrastructure status

The active architecture uses native Windows processes. Run `scripts/start-native.ps1` and `scripts/stop-native.ps1` from the project root. Mosquitto uses the tracked ACL here and a generated runtime configuration under `.runtime`.

`compose.yaml` and `grafana/` are preserved from the earlier, superseded proposal. They are inactive reference files. Do not start or download their images for the native deployment.

No Docker resources with Compose project label `parking-monitoring` were found during the native revision inventory. No project Docker builds or pulls were running. Unrelated Docker resources were not deleted or stopped.
