# 0004 — Delivery semantics across the pipeline

- **Status:** Accepted
- **Date:** 2026-07-11
- **Applies to:** ingest write path, `stream_consumer/`, `projection_consumer/`, the anomaly alerter

## Context

The system now spans a synchronous write path and an asynchronous fan-out path.
"What are your delivery guarantees?" needs one crisp, correct answer, including
where consistency is traded for decoupling.

## Decision — the guarantees, hop by hop

### Write path (unchanged)

- **Transport (simulator → API Gateway → ingest):** at-least-once. The simulator
  retries with backoff, so the same event can arrive more than once.
- **Storage (conditional `PutItem`):** effectively-once, at **one-second
  granularity**. The key is `(device_id, ts)` with `ts` in whole seconds and the
  write is conditional on that key not existing. A retried duplicate is a no-op
  (409). Two genuinely distinct events from the same device within the same second
  would collide; acceptable at this event rate.

### Async path (new)

- **Stream (committed write → stream consumer):** at-least-once, `INSERT` only.
  A committed write is guaranteed to appear (ADR-0002); the consumer can see a
  record more than once (batch retries).
- **SNS → SQS / SNS → Lambda:** at-least-once, and **unordered** (standard, not
  FIFO — ADR-0003).
- **Projection write (sole writer, via SQS):** effectively-once **and**
  order-tolerant, through one conditional expression:

  ```
  attribute_not_exists(ts) OR ts < :incoming_ts
  ```

  Duplicate delivery of the same `ts` → condition fails → no-op. An older `ts`
  arriving after a newer one → condition fails → stale write rejected. `ts` is the
  version stamp; no separate dedup table is needed.

- **Anomaly alerter:** at-least-once and idempotent in effect — it emits a
  CloudWatch count metric, and a duplicate delivery would at worst double-count a
  single anomaly datapoint, which is tolerable for an observability signal.

## The projection is an eventually-consistent read model (deliberate trade-off)

The projection is written by a **single** writer (the SQS consumer), reached only
after `write → stream → stream consumer → SNS → SQS`. So the projection reflects a
write after a short, extra async delay rather than synchronously — it is
**eventually consistent**, not read-your-writes.

This is a chosen trade-off. We considered also writing the projection directly in
the stream consumer (a second, redundant writer) so the read model would update
one hop sooner and survive a bug in either writer. We rejected that:

- **Single writer keeps responsibilities crisp.** The stream consumer's only job
  is change-data-capture → bus; the projection has exactly one thing that writes
  it. That is far easier to reason about, test, and debug than two writers racing
  on the same item (even though the conditional write makes the race safe).
- **The cost we accept:** there is no redundant writer, so a bug in the projection
  consumer means the projection stops updating (the source table and the alerter
  are unaffected — see the runbook for telling the paths apart). We judge "one
  obvious writer" more valuable than "a spare writer for resilience," because a
  spare writer mostly buys resilience against our own bugs, which is better spent
  on tests and the DLQ than on a second code path.

The extra latency is small and bounded, and it only affects the derived
current-state view; the system of record (`EventsTable`) is still updated
synchronously and read consistently by the device-scoped query path.

## Consequences

- **One-sentence answer:** at-least-once transport throughout; effectively-once,
  order-tolerant storage on both the source table (per-second) and the projection
  (per-`ts` conditional write); the projection is eventually consistent by design.
- **Every consumer is idempotent**, so retries and redrives are always safe —
  including replaying `simulator/dead_letter.jsonl` or redriving the projection
  DLQ.
- **The 1-second collision caveat** on the source table is the one sharp edge; a
  finer `ts` or a client-supplied event id would remove it if ever needed.
</content>
