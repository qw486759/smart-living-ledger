# Runbook — Smart Living Ledger

On-call procedures for the ingest/query pipeline. Resource names use the `dev`
stage; substitute the stage you're operating (`sll-ingest-<stage>`, etc.).

## First: which half is broken?

The system has an independent **write path** and **read path**. Decide which one
is degraded before digging — they fail for different reasons.

| Symptom | Likely half | First check |
|---|---|---|
| Dashboard panels show `--` or the error banner | Read path | `sll-query-errors` alarm, query Lambda logs |
| Dashboard is stale but not erroring (timestamps not advancing) | Write path | Is the simulator/device source running? Ingest logs for `event_stored` |
| `POST /events` returns 5xx | Write path | `sll-ingest-errors` alarm, ingest Lambda logs |
| Everything 5xx, both paths | API Gateway / DynamoDB / account-level | API Gateway access logs, DynamoDB console, Service Health |

A quick way to confirm the write path is alive:

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/sll-ingest-dev \
  --filter-pattern '"event_stored"' \
  --start-time $(( ($(date +%s) - 300) * 1000 ))
```

No `event_stored` lines in the last few minutes with a running source ⇒ writes
are failing upstream of DynamoDB (validation, throttle, or API Gateway).

## Alarms and what they mean

Defined in `infra/template.yaml`; threshold rationale is in
[`adr/0001-alarm-thresholds-and-slos.md`](adr/0001-alarm-thresholds-and-slos.md).

### `sll-ingest-errors` (Lambda Errors ≥ 5 in 5 min)

The ingest Lambda is throwing (not returning 4xx — those are handled and don't
count as Lambda errors). Usual causes:

1. **DynamoDB access denied / table missing** — check the Lambda's role still has
   `PutItem` on the table ARN and that the stack didn't half-deploy.
2. **Unhandled exception in the handler** — grep logs for a stack trace:
   ```bash
   aws logs filter-log-events --log-group-name /aws/lambda/sll-ingest-dev \
     --filter-pattern '"dynamodb_write_failed"'
   ```
   The `aws_error_code` field tells you which DynamoDB error it was.
3. **Throttling** — `ProvisionedThroughputExceededException` is mapped to HTTP 429
   (`WRITE_THROTTLED`), not a Lambda error, but a burst of them signals capacity
   pressure. The table is `PAY_PER_REQUEST`, so this is rare; if you see it,
   check for a partition hot-spot (one `device_id` taking all the traffic).

Note: a validation failure returns **422** and a duplicate returns **409**. Those
are expected client outcomes, not incidents. If the error alarm is quiet but
clients complain, look at the 4xx rate in the API Gateway access logs instead.

### `sll-ingest-p95-latency` (p95 Duration ≥ 3000 ms for 2 periods)

Ingest is slow. Almost always either cold starts (a burst after idle) or
DynamoDB latency. Cross-check the p95 with the Logs Insights query in the README.
Sustained (not just a cold-start spike) p95 near the alarm means look at DynamoDB
first, then Lambda memory (currently 256 MB).

### `sll-query-errors` (Lambda Errors ≥ 5 in 5 min)

The read path is throwing. The most common real cause is the `Scan` branch under
load or a malformed query param. Check:

```bash
aws logs filter-log-events --log-group-name /aws/lambda/sll-query-dev \
  --filter-pattern '"dynamodb_query_failed"'
```

`INVALID_LIMIT` / `INVALID_TIME_RANGE` are 400s (client error), not incidents.

## Common scenarios

### Dashboard is blank / error banner

1. Confirm `dashboard/config.js` points at the right `SLL_API_BASE` for the stage.
2. Hit the query API directly: `curl "$SLL_API_BASE/events?type=temp&limit=5"`.
   - 200 with items ⇒ front-end/config issue, not backend.
   - 5xx ⇒ query Lambda; see `sll-query-errors` above.
   - CORS error in the browser only ⇒ the response is fine but the origin isn't
     allowed; today CORS is `*`, so a CORS failure usually means the request
     never reached the Lambda (check the URL/stage).

### Writes accepted but data not appearing in the dashboard

The dashboard's per-type panels read via `Scan` and sort in memory. If writes are
landing (you see `event_stored`) but panels lag, it's the read side: check the
query Lambda isn't erroring and that `limit` is high enough to include recent
events for that type.

### Simulator can't deliver

The simulator retries 3× with backoff, then appends to
`simulator/dead_letter.jsonl`. If that file is growing:

```bash
wc -l simulator/dead_letter.jsonl
tail -n 5 simulator/dead_letter.jsonl
```

Each line is a full event that never got a 200. Once the endpoint is healthy you
can replay them by POSTing each line to `/events` (they're idempotent on
`device_id`+`ts`, so replaying an already-stored event just returns 409 — safe).

## Async projection/alert path (planned)

> This path is on the roadmap (DynamoDB Streams → projection consumer + anomaly
> consumer) and is **not deployed yet**. The procedures below are the intended
> operating model and take effect once the stack includes it. See the roadmap in
> the README and the forthcoming ADRs under `docs/adr/`.

- **Projection consumer failing (stream Lambda erroring):** the read model stops
  updating while the synchronous write path keeps working — so the source table
  is correct but derived views go stale. Check the stream consumer's error metric
  and logs first; the fix is almost never on the write side.
- **Rising DynamoDB Streams iterator age:** the consumer is falling behind the
  stream (or failing and retrying the same batch). Growing iterator age means
  increasing lag between a write and its projection/alert. Look for a poison
  record causing repeated batch failures, or a downstream (SNS/SQS) that's
  rejecting. Bisecting the batch on error isolates a poison record.
- **Messages sitting in the DLQ:** a record failed processing past its retry
  budget and was parked. Inspect it before redriving — a DLQ message is usually
  either a poison payload (a schema the consumer can't handle) or a transient
  downstream outage that has since cleared. Redrive only after confirming the
  cause is gone; because the projection write is idempotent on `device_id`+`ts`,
  redriving already-applied records is safe.
- **Telling the paths apart:** the synchronous ingest path degrading shows up as
  `POST /events` 5xx and the ingest alarms. The async path degrading shows up as
  stale projections / missing alerts with a **healthy** ingest path — the table
  is fine, only the derived work is behind.

## Escalation / rollback

- The DynamoDB table is `DeletionPolicy: Retain` with point-in-time recovery on,
  so redeploying or tearing down the stack does not lose event history.
- To roll back a bad deploy, redeploy the previous known-good template revision
  (`./deploy.sh <stage>` from that revision); the table is untouched by stack
  replacement of the Lambdas/API.
- `./teardown.sh <stage>` removes the stack but retains the table by design.
</content>
