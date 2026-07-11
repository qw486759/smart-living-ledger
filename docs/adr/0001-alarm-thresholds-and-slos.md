# 0001 — CloudWatch alarm thresholds and SLOs

- **Status:** Accepted
- **Date:** 2026-07-11
- **Applies to:** `infra/template.yaml` (`IngestErrorAlarm`, `IngestLatencyAlarm`, `QueryErrorAlarm`)

## Context

The pipeline has three CloudWatch alarms. The question this ADR answers is not
"should we have alarms" but "why these thresholds," because a badly-tuned
threshold is worse than none: too tight and it pages on normal noise until people
mute it; too loose and a real outage never fires.

Two facts about the workload set the tuning:

1. **Volume is low and bursty.** At the default rate the pipeline sees ~80
   events/minute from four devices. A handful of errors is a meaningful fraction
   of a 5-minute window, so thresholds can be low without being noisy.
2. **4xx is expected traffic, not failure.** Validation failures (422) and
   duplicate writes (409) are handled responses, not Lambda errors — they do not
   increment the `Errors` metric. So the error alarms only fire on genuine
   unhandled failures (bad IAM, DynamoDB unavailable, a code bug), which should be
   near-zero in steady state.

## Decision

### Error alarms — `Errors` Sum ≥ 5 over one 5-minute period

Both the ingest and query error alarms use `Statistic: Sum`, `Period: 300`,
`EvaluationPeriods: 1`, threshold `5`, `ComparisonOperator: GreaterThanOrEqualToThreshold`.

- **Why 5 and not 1:** in steady state genuine Lambda errors are ~0, so a
  threshold of 1 would page on a single transient (a one-off cold-start timeout, a
  brief DynamoDB blip). Five errors in five minutes is a rate a healthy system
  does not produce by accident, so it separates "noise" from "something is
  actually broken" while still being sensitive given the low volume.
- **Why one evaluation period, not several:** errors are a "something is wrong
  now" signal; we want it fast. Requiring multiple consecutive periods would delay
  paging by 5+ minutes for no benefit — unlike latency, error count doesn't
  oscillate around a threshold.

### Ingest latency — `Duration` p95 ≥ 3000 ms over two 5-minute periods

`ExtendedStatistic: p95`, `Period: 300`, `EvaluationPeriods: 2`, threshold `3000`.

- **Why p95 and not max or average:** `max` fires on every cold start (a single
  slow invocation), which is expected for a low-traffic Lambda and would be pure
  noise. `average` hides tail latency behind a mass of fast warm invocations —
  the pipeline could be intermittently painful and the average would stay flat.
  p95 tracks "the experience most requests are actually getting" while tolerating
  the occasional cold-start outlier.
- **Why 3000 ms:** a warm ingest invocation is tens of milliseconds; a Python cold
  start plus a DynamoDB round-trip is comfortably under 3s. A *sustained* p95 near
  3s therefore means real degradation (DynamoDB latency, memory pressure), not
  normal cold-start behaviour. It is deliberately generous so it doesn't chase
  cold starts.
- **Why two evaluation periods, not one:** latency naturally spikes for a single
  window (a burst after idle warms several containers at once). Requiring the p95
  to stay high across two consecutive 5-minute windows filters those transients
  and pages only on a persistent problem — the opposite trade-off from the error
  alarms, and on purpose.

### `TreatMissingData: notBreaching` on all three

Low, bursty traffic means some 5-minute windows legitimately have no invocations
and therefore no data. Treating missing data as breaching would fire alarms during
quiet periods (nights, idle demos) when nothing is wrong. `notBreaching` means "no
traffic is not an incident," which matches how this workload actually behaves.

## Consequences

- **Accepted false negatives:** fewer than 5 real errors in a 5-minute window
  won't page. For a low-volume telemetry pipeline that's the right trade — a
  trickle of errors is caught by log review, not a 2am page. If this became a
  higher-stakes path (command/control), the error threshold should drop and the
  latency alarm should probably move to a tighter percentile.
- **Accepted detection delay on latency:** the two-period requirement means a real
  latency regression takes up to ~10 minutes to page. That's acceptable for a
  polling dashboard; it would not be for a synchronous control API.
- **Implicit SLO:** these thresholds encode a rough objective of "unhandled error
  rate ≈ 0 and ingest p95 < 3s in steady state." There is no formal error budget
  yet; if one is introduced, these alarms are the enforcement points and should be
  re-derived from the budget rather than left at these hand-picked values.
- **What would change this:** adding the async projection/alert path introduces new
  failure surfaces (stream consumer errors, iterator age, DLQ depth) that need
  their own alarms; those will be recorded in a later ADR and should reuse the same
  reasoning (fast on errors, patient on latency-like signals, tolerant of idle).
</content>
