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

## Async projection/alert path

Flow: `EventsTable` stream → `sll-stream-consumer-<stage>` → SNS
`sll-event-stored-<stage>` → {`sll-projection-<stage>` SQS →
`sll-projection-consumer-<stage>` writes `sll-projection-<stage>` table} and
{`sll-alerter-<stage>` emits the `SmartLivingLedger/AnomalyDetected` metric}.
Delivery guarantees are in [adr/0004](adr/0004-delivery-semantics.md).

**Telling the paths apart first.** The synchronous ingest path degrading shows up
as `POST /events` 5xx and the ingest alarms. The async path degrading shows up as
**stale projections or missing alerts while the ingest path is healthy** — the
source table is fine, only the derived work is behind. The projection is
eventually consistent by design, so a few seconds of lag is normal.

### Stream consumer erroring — alarm `sll-stream-consumer-errors-<stage>`

The CDC→SNS bridge is failing (usually an SNS publish problem). Downstream
projections and alerts stop updating; the write path is unaffected.

```bash
aws logs filter-log-events --log-group-name /aws/lambda/sll-stream-consumer-dev \
  --filter-pattern '"event_published"'
```

No `event_published` lines while writes are landing ⇒ the bridge is stuck. Failed
batches are retried, bisected, then parked in `sll-stream-consumer-dlq-<stage>`.

### Rising iterator age — alarm `sll-stream-iterator-age-<stage>`

The stream consumer is falling behind (or repeatedly failing a batch and
retrying). Growing iterator age = growing lag between a write and its
projection/alert. Look for a poison record causing repeated batch failures, or an
SNS problem. `BisectBatchOnFunctionError` narrows a bad batch down to the offending
record, which eventually lands in `sll-stream-consumer-dlq-<stage>`.

### Projection consumer erroring — alarm `sll-projection-consumer-errors-<stage>`

The sole projection writer is failing. The read model goes stale while the source
table and the alerter are fine.

```bash
aws logs filter-log-events --log-group-name /aws/lambda/sll-projection-consumer-dev \
  --filter-pattern '"projection_write_failed"'
```

A `ConditionalCheckFailedException` is **not** an error here — it's a duplicate or
out-of-order message being correctly skipped (logged as
`projection_skipped_stale_or_duplicate`). Only non-conditional errors page.

### Messages in a DLQ — alarms `sll-projection-dlq-depth-<stage>` / `sll-stream-consumer-dlq-depth-<stage>`

A record failed past its retry budget and was parked. **Inspect before redriving.**

```bash
# Peek (does not delete): see what's parked
aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 10 \
  --visibility-timeout 0

# Redrive back to the source queue once the cause is fixed (projection DLQ):
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:<region>:<acct>:sll-projection-dlq-<stage>
```

A DLQ message is usually a poison payload (a shape the consumer can't handle) or a
transient downstream outage that has since cleared. Redrive only after confirming
the cause is gone; because every consumer is idempotent on `ts`, redriving
already-applied records is safe (they no-op). Queue URLs/ARNs are stack outputs
(`ProjectionQueueUrl`, `ProjectionDLQUrl`, `StreamConsumerDLQUrl`).

> A poison message takes ~`maxReceiveCount` × the queue visibility timeout
> (3 × 60s ≈ up to ~3 min) to reach the projection DLQ.

## Escalation / rollback

- The DynamoDB table is `DeletionPolicy: Retain` with point-in-time recovery on,
  so redeploying or tearing down the stack does not lose event history.
- To roll back a bad deploy, redeploy the previous known-good template revision
  (`./deploy.sh <stage>` from that revision); the table is untouched by stack
  replacement of the Lambdas/API.
- `./teardown.sh <stage>` removes the stack but retains the table by design.
</content>
