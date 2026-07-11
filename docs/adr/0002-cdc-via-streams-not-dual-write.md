# 0002 — Change data capture via DynamoDB Streams, not an in-Lambda dual write

- **Status:** Accepted
- **Date:** 2026-07-11
- **Applies to:** `stream_consumer/`, `EventsTable` StreamSpecification, `EventStoredTopic`

## Context

The async fan-out path needs to notify downstream consumers (projection writer,
anomaly alerter) whenever an event is stored. There are two ways to emit that
notification from the write path:

1. **In-Lambda dual write:** after `PutItem` succeeds in the ingest Lambda, call
   `SNS.publish()` in the same handler.
2. **Change data capture (CDC):** enable a DynamoDB Stream on the table and have a
   separate consumer republish stream records.

## Decision

Use CDC via DynamoDB Streams. The ingest Lambda is unchanged; a new
`stream_consumer` reads the stream and publishes to SNS.

The deciding factor is the **dual-write problem**. Option 1 performs two
independent operations with no shared transaction: the DynamoDB write and the SNS
publish. If the write succeeds but the publish fails (Lambda timeout, SNS
throttle, a crash between the two calls), the event is durably stored but
downstream consumers never learn it exists — a silent, permanent inconsistency
that is invisible until someone notices missing projections. The failure is also
hard to recover from because the ingest response has already been returned.

With CDC the stream is derived from the committed write, so a successful write is
*guaranteed* to appear on the stream. The publish becomes a separate, retriable
step owned by the stream consumer, with the event source mapping's retry / bisect
/ DLQ machinery behind it (see ADR-0004).

## Consequences

- **The conditional `PutItem` composes well with this.** A rejected conditional
  write (the duplicate/409 case) produces **no** stream record, so the stream only
  carries genuinely new events — the write-time idempotency guard doubles as a
  stream-level de-noiser.
- **Delivery becomes at-least-once again past the table.** "Appears on the stream"
  is not "delivered exactly once to a consumer": stream→Lambda is at-least-once
  with batch retries, and SNS/SQS add their own at-least-once. Consumers must be
  idempotent (see ADR-0004); they are, via the `ts`-versioned conditional write.
- **We filter to `INSERT`.** The stream also carries `MODIFY` and TTL-driven
  `REMOVE` records; the consumer (and the event source mapping's `FilterCriteria`)
  ignore everything except `INSERT`, because only new events should fan out.
- **Cost/latency:** one extra Lambda and a stream. At this event rate the cost is
  negligible; the latency is the price of decoupling (quantified in ADR-0004).
- **Rejected:** the in-Lambda dual write. It is simpler by one component but trades
  a correctness hole (lost notifications) for that simplicity, which is the wrong
  trade for anything that downstream state depends on.
</content>
