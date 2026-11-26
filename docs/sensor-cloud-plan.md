# Sensor cloud storage decision record — proposed, not deployed

The supplied rubric items 11–13 require an on-premise/cloud receiver, time-series storage/retrieval and a live/history dashboard. The existing native deployment addresses these locally. Issue 1 additionally requests sensor cloud sync; there is no approved provider, account, region, spend cap or credential available for deployment in this task.

## Options and recommendation

| Option | Fit / tradeoff | Decision |
| --- | --- | --- |
| Keep native InfluxDB OSS 2.x only | Smallest local change and current Flux dashboard works; no off-site archive | Current deployed architecture, does not claim cloud sync |
| Managed InfluxDB Cloud Serverless free plan | Time-series destination and v2-compatible writes; separate SQL/InfluxQL retrieval adapter required, not a drop-in Flux history endpoint | Preferred candidate for a small demonstration after account/region/limits approval |
| Remote team-managed InfluxDB OSS 2.x | Reuses schema and Flux queries; team must provide server, TLS, backups, patching and disk budget | Alternative if an approved existing server is available |

As checked 2026-11-26, the [official Serverless limits](https://docs.influxdata.com/influxdb3/cloud-serverless/admin/billing/limits/) describe free-plan write/read quotas, two buckets and 30-day retention; the [signup documentation](https://docs.influxdata.com/influxdb3/cloud-serverless/sign-up/) describes free-plan signup. New [Cloud signups use the InfluxDB 3 engine](https://docs.influxdata.com/influxdb/cloud/sign-up/); do not assume Flux compatibility. Availability and quotas must be rechecked for the selected account. No cost estimate is asserted without measured bytes/day, selected region and plan. Paid upgrades/resources require approval before provisioning.

## Proposed sync design, pending implementation

Only actual accepted `parking_node` and `parking_gateway` telemetry is eligible for cloud export. Preserve original backend UTC receipt timestamp, source identity, measurement and fields. Do not export one-second status projections, legacy camera data, plates, photos or session records. Source sample timestamps/boot IDs/sequences require a future compatible protocol; backend receipt time is not acquisition time.

Use a separate worker with a disk-backed bounded outbox, capped by both record count and byte budget (proposed 10,000 records / 16 MiB, approval after footprint measurement). Key each record by measurement/source/original timestamp; persist enqueue and acknowledgement atomically. Retry timeout/429/5xx with capped exponential backoff and jitter, retain original IDs/timestamps and honor Retry-After. Isolate permanent schema/auth failures and report them; never retry a malformed record forever. Drop policy on capacity must be explicit, counted and visible; no unbounded filesystem spool. Retain bounded dedup state across restart and verify provider overwrite/idempotency semantics before relying on it.

Cloud write/read credentials stay server-side with least privilege, HTTPS certificate validation and short request deadlines. No external call on MQTT receive, availability or gate paths. Cloud health/backlog/drop counts must be separate from local storage and sensor freshness. Cloud history must identify its origin and gap intervals; never merge delayed archive readings into live state or relabel upload time as acquisition time.

## Approval and acceptance still required

Choose account/provider/region, approve spend cap (including a decision to stay on a free plan), retention, privacy/access and measured outbox budget. Then implement disabled-by-default sync and a provider-specific retrieval adapter. Test offline capacity, restart durability, partial writes, retry duplicates, ordering, invalid credentials, retrieval gaps and local monitoring during cloud failure in a dedicated synthetic bucket. Finally demonstrate actual sensor cloud retrieval and dashboard display. **No cloud sync, durability, retrieval or visualization acceptance is claimed in this PR.**
