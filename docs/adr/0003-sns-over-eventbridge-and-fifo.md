# 0003 — SNS for fan-out (not EventBridge), standard (not FIFO)

- **Status:** Accepted
- **Date:** 2026-07-11
- **Applies to:** `EventStoredTopic`, the SNS→SQS subscription, the alerter subscription

## Context

The stream consumer needs a fan-out point so multiple independent consumers can
react to an event-stored notification without knowing about each other. Today
there are two consumers — the projection writer (via SQS) and the anomaly alerter
— and we want adding a third to require no change to the producer.

Two axes of choice: **which fan-out service** (SNS vs EventBridge) and **ordering
mode** (standard vs FIFO).

## Decision

Use a **standard SNS topic**, fanning out to an SQS queue (projection writer) and
a Lambda subscription (alerter).

### SNS over EventBridge

EventBridge offers richer routing (content-based rules), a schema registry, and
archive/replay, and with Pipes could even source the DynamoDB stream directly.
Those are genuinely useful at larger scale. We chose SNS because:

- The routing need here is trivial — every consumer wants every event-stored
  message. Content-based rules would be unused machinery.
- SNS→SQS and SNS→Lambda are the most legible, widely-understood fan-out
  primitives, which keeps the system easy for a teammate to reason about.
- EventBridge remains the right move if/when we need routing, replay, or a schema
  registry; this decision is explicitly revisitable on those triggers.

### Standard over FIFO

The projection is a "latest reading per device" view, so **ordering matters**:
an out-of-order delivery could overwrite a newer reading with an older one.
Standard SNS and standard SQS do **not** preserve order. FIFO (SNS FIFO → SQS
FIFO with `MessageGroupId = device_id`) would preserve per-device order, but:

- FIFO has throughput caps and more configuration surface.
- It only solves ordering, not idempotency — we'd still need dedup.

Instead we make the **consumer** order-tolerant with the same `ts`-versioned
conditional write that gives us idempotency (`attribute_not_exists(ts) OR ts <
:incoming_ts`; see ADR-0004). One mechanism solves both duplicate delivery and
out-of-order delivery, so standard SNS/SQS is sufficient and simpler.

## Consequences

- **No ordering guarantee on the wire**, by design; correctness comes from the
  conditional write, not from the transport. This is the key thing to explain when
  someone asks "how do you handle out-of-order events?"
- **Adding a consumer is a one-line subscription** with no producer change.
- **Rejected:** EventBridge (routing/replay we don't need yet) and FIFO (solves
  only ordering, at a cost, when a conditional write solves ordering *and*
  idempotency together).
</content>
