# Non-Functional Requirements, SLOs & Boundaries

> Companion to [`architecture.md`](architecture.md). What the platform must be, not
> just what it does. Targets are deliberately modest — this is an internal welfare
> monitor for one subject, and the numbers are set so the alarms in the SAM template
> mean something rather than to hit a vanity SLA.

## Availability

| Path | Target | Rationale |
|---|---|---|
| Ingest write (`POST /events`) | best-effort, retried | Serverless; edge buffer covers short outages (nothing dropped silently). |
| Recognition (Enrichment) | best-effort, async | A failed vision call retries / dead-letters the frame; delays one sighting, never the pipeline. |
| Welfare alerting | should fire within minutes of the triggering event | A late safety/health signal is the one thing that actually matters here. |
| Dashboard / query | best-effort | A polling monitor; brief unavailability is cosmetic. |

There is no hard uptime SLA. The design goal is **no silent data loss** (edge buffer
+ DLQs) and **timely alerts**, not five-nines.

## Latency budgets

| Stage | Budget | Notes |
|---|---|---|
| Edge gate (motion → candidate decision) | < ~1 s | Local, cheap. |
| Recognition (S3 → Bedrock VLM → `sighting`) | seconds–low minutes, **async** | Off the critical path; cascade adds a second hop only for uncertain frames. |
| Ingest write (validate → `PutItem`) | p95 < ~500 ms | Existing CloudWatch p95 alarm. |
| Event → welfare alert | minutes | CDC + SQS + rule eval; acceptable for a "hasn't been seen / eating less" signal. |
| Dashboard query | p95 < ~1 s | Single-partition `Query` via GSI, not `Scan`. |

**Command/control is out of scope.** There is no sub-100 ms path here; if one were
added (a lock, a feeder trigger), it would get its own warm path and budget.

## Data retention

| Data | Retention | Mechanism |
|---|---|---|
| Event log (DynamoDB) | 30 days | `ts`-based TTL (`expire_at`) |
| Candidate frames (S3) | **7 days** | S3 lifecycle ([ADR-0007](../adr/0007-image-privacy-and-retention.md)) |
| Entity-state projection | current only | overwritten per entity-field |
| Daily/weekly rollups | longer (months) | small aggregates; establishes "normal" |
| CloudWatch logs | per log-group policy | structured JSON |

## Privacy

Governed by [ADR-0007](../adr/0007-image-privacy-and-retention.md): minimise what
leaves the home (edge gate), encrypt at rest (SSE-KMS), least-privilege access,
short retention, metadata-only in the event log and the LLM summary path, no
person/face recognition. Region-pinned so frames don't cross data-residency
boundaries.

## Security

| Concern | Now | Boundary (where it must move) |
|---|---|---|
| Device identity | API key for the edge client | IoT Core certs / device registry as sensors multiply |
| API auth | none yet, CORS `*` | Cognito/IAM + CORS locked to dashboard origin before it leaves a trusted account |
| Cloud LLM access | Bedrock via least-privilege IAM role | — (in-account already) |
| Frame access | Enrichment role only, CloudTrail audited | — |
| Multi-tenant isolation | none (single subject) | `entity` as authz boundary if multi-subject ([ADR-0006](../adr/0006-entity-vs-device-modeling.md)) |

These are the same honest shortcuts the README's roadmap lists — recorded so they're
chosen, not forgotten.

## Capacity & scaling

- Event volume is **low** (an outdoor cat, not continuous telemetry) — a few dozen
  sightings + feedings per day, well within on-demand serverless.
- The dials that scale with load: **candidate-frame volume** (→ S3 + Bedrock cost)
  and **event rate** (→ API GW + DynamoDB writes). The edge gate is the primary lever
  on the first; both are quantified in [`cost-model.md`](cost-model.md).
- Recognition cost scales with model choice (Nova ↔ Claude ↔ cascade), not with
  re-architecture.

## Observability

- **CloudWatch alarms**: ingest errors, ingest p95 duration, query errors (existing);
  add DLQ depth (recognition + projection) and Bedrock error/throttle rate.
- **Structured JSON logs** with `event`, `device_id`, `entity_id`, `event_type`,
  `request_id`, `confidence`, `model_id` — shaped for Logs Insights aggregation.
- **Recognition health**: track the `confidence` distribution and cascade-escalation
  rate — both a quality signal (is the primary model good enough?) and a cost signal.
- **Cost**: a budget alarm on Bedrock spend, since that's the one line that isn't
  near-zero.
