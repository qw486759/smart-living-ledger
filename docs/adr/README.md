# Architecture Decision Records

Short records of decisions that are expensive to reverse or easy to
misremember. Each one captures the context at the time, the decision, and the
consequences we accepted — so the next person changing this can see *why*, not
just *what*.

Format follows Michael Nygard's lightweight ADR template. New records are
append-only; if a decision changes, add a new ADR that supersedes the old one
rather than editing history.

| # | Title | Status |
|---|---|---|
| [0001](0001-alarm-thresholds-and-slos.md) | CloudWatch alarm thresholds and SLOs | Accepted |
| [0002](0002-cdc-via-streams-not-dual-write.md) | CDC via DynamoDB Streams, not an in-Lambda dual write | Accepted |
| [0003](0003-sns-over-eventbridge-and-fifo.md) | SNS for fan-out (not EventBridge), standard (not FIFO) | Accepted |
| [0004](0004-delivery-semantics.md) | Delivery semantics across the pipeline | Accepted |
| [0005](0005-edge-vs-cloud-inference.md) | Two-stage sighting recognition: edge gate + Bedrock VLM | Accepted |
| [0006](0006-entity-vs-device-modeling.md) | Entity vs device: model Zeus as an observed subject | Accepted |
| [0007](0007-image-privacy-and-retention.md) | Image privacy and retention | Accepted |
| [0008](0008-llm-assistant-tier.md) | Where the LLM is used, and where it is not | Accepted |
</content>
