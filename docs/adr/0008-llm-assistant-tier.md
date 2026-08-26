# 0008 — Where the LLM is used, and where it is not

- **Status:** Accepted
- **Date:** 2026-08-21
- **Applies to:** the Enrichment Lambda (`enrichment/`), the rollup/summary path, the alerter

## Context

Claude appears in the platform for two jobs. This ADR is the map of *where* the LLM
is used, *where it is deliberately not*, and the boundaries that keep it from
undermining the deterministic parts of the system. (The recognition architecture
itself — two-stage, edge gate + cloud vision — is ADR-0005; this ADR records the
LLM-usage decision that sits on top of it.)

## Decision

Call models through **Amazon Bedrock** (so the LLM lives in the same AWS account as
the rest of the platform — one IAM/VPC/billing surface), using the **Converse API**
so the model is a swappable config value. Used in exactly two places:

1. **Recognition (primary) — vision, in the Enrichment tier.** A model-agnostic
   recognizer does few-shot "is this Zeus?" on candidate frames, returning structured
   output. Model is config-switchable between `amazon.nova-lite-v1:0` (cheapest) and
   `anthropic.claude-sonnet-4-6` (stronger), with an optional confidence cascade
   (Nova first, escalate uncertain frames to Claude). Full rationale in ADR-0005.
2. **Welfare summary (bonus) — text, in the Analytics/serving side.** After the daily
   rollup, a Bedrock Claude model (Sonnet, or Haiku `anthropic.claude-haiku-4-5` to
   save) turns the computed aggregates (sighting counts, intake totals, 7-day
   baselines, deltas) into a short welfare summary via **structured output** (a
   validated schema, not free text), delivered through the notification path.

**Where the LLM is deliberately *not*:**

- **Not in anomaly detection.** Welfare rules (`no_sighting`, `feeding_drop`,
  `night_intrusion`) stay deterministic threshold logic in `alerter/`. Fast,
  predictable, auditable, free.
- **Not in the synchronous ingest write path.** `POST /events` → validate →
  conditional `PutItem` never calls an LLM.

**What is sent to Claude, minimised:**

- Recognition: only edge-gated *candidate* frames plus the fixed Zeus reference
  photos — never the full motion stream.
- Summary: only computed aggregate numbers and timestamps — never camera frames
  (they don't reach this tier) and never a bulk dump of the event log.

## Consequences

- **The LLM touches an async pre-ingest step (recognition), but never a blocking
  one.** Recognition sits on the async motion → S3 → Lambda → Claude → `sighting`
  chain, so a slow/failed call delays one sighting (retry / DLQ the frame), not the
  pipeline. The summary is serving-side and even more isolated. Neither can delay a
  write already in flight or a welfare alert on an event already stored.
- **Cost ≈ $2–16/month, set by the vision model choice** (Nova Lite ~$1–2, Claude
  Sonnet ~$7, cascade in between); the summary adds ~$1. Prompt caching on the fixed
  reference photos + system prompts is the main lever (see ADR-0005).
- **Prompt-injection surface is small.** Recognition input is an *image*, not
  user-authored instructions; the summary input is our own aggregates. No LLM path
  exposes a write tool.
- **New external dependency + a pinned model.** We depend on the Anthropic API and
  pin `claude-opus-4-8` so behaviour doesn't drift; a model upgrade is a deliberate,
  tested change.
- **Structured output keeps both paths machine-usable.** Recognition returns
  `{is_zeus, confidence}`; the summary returns typed fields (headline, concern level,
  per-metric notes). The LLM writes judgement/words; the surrounding system stays
  typed.
- **Rejected / deferred:** LLM for alerting (rules are better — faster, deterministic,
  free); and the natural-language query agent (a read-only tool-use agent over the
  query API) — a good future addition, deferred to keep scope focused on the two jobs
  above.
