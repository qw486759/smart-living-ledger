# Cost Model

> Companion to [`architecture.md`](architecture.md). The point is capacity planning
> and knowing which dials matter — not a precise invoice. us-east-1 on-demand;
> figures are order-of-magnitude and move with usage and current pricing.

## Assumptions

An outdoor cat generates **low, bursty** volume — nothing like the original
simulator's continuous stream:

- ~150 motion triggers/day, most dropped by the edge gate.
- ~20 candidate frames/day reach the cloud → ~**600 recognition calls/month**.
- ~20 sightings + a handful of feedings/day → ~**1,000 events/month** stored.
- ~1 daily + 1 weekly welfare summary → ~**37 summary calls/month**.
- ~10K dashboard polls/month.

## Monthly cost

| Service | Usage | Monthly (USD) |
|---|---|---|
| API Gateway | ~1K ingest + ~10K query requests | < $0.05 |
| Lambda (ingest, stream, projection, query, rollup) | low invocation counts, small memory | < $0.10 |
| Lambda (enrichment) | ~600 invocations | < $0.05 |
| DynamoDB (event log + projection) | ~1K writes, ~10K reads, TTL-capped storage | < $0.20 |
| S3 (candidate frames) | ~600 PUT, 7-day retention (~tens of MB) | < $0.05 |
| **Bedrock — recognition** | ~600 vision calls | **$1–7** (Nova Lite ~$1–2 · Claude Sonnet ~$7 · cascade in between) |
| Bedrock — welfare summary | ~37 calls | ~$1 |
| SNS / SQS | ~1K messages | < $0.05 |
| CloudWatch (logs + alarms) | ~1 GB logs | ~$0.50 |
| **Total** | | **~$3–10 / month** |

## What dominates, and the dials

- **Bedrock recognition is >70% of a bill that is otherwise near-zero.** The dials,
  in order of leverage:
  1. **Model choice** — Nova Lite vs Claude Sonnet vs cascade (biggest single lever).
  2. **Prompt caching** — the fixed Zeus reference photos + system prompt are a cached
     prefix (~0.1× on reads); this is what keeps per-call cost low.
  3. **Edge gate strictness** — fewer candidate frames = fewer vision calls.
  4. **De-duplication** — collapse repeat sightings of Zeus within a short window into
     one recognition call.
- **Everything else scales with event rate** (API GW + DynamoDB writes), which stays
  tiny for one cat. The `ts` TTL keeps event-log storage flat; the 7-day S3 lifecycle
  keeps frame storage flat.

## Contrast with the original

The original simulator-driven design was ~$17/month, dominated by API Gateway
requests and DynamoDB writes at a synthetic ~3.5M events/month. The real Zeus
workload is *far* lower volume, so the entire non-LLM pipeline drops to near-zero and
the bill is now dominated by a genuinely useful line — recognition — that you can
tune from ~$1 to ~$7 by choosing the model.
