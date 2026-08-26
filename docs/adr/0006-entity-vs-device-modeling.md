# 0006 — Entity vs device: model Zeus as an observed subject, not a device

- **Status:** Accepted
- **Date:** 2026-08-21
- **Applies to:** the event contract, the projection table, `projection_consumer/`, the query API

## Context

The original system had a single identity: `device_id`, used both as the DynamoDB
event-log partition key and as the thing the dashboard grouped by. That worked when
"device" and "subject" were the same — a temperature sensor *is* the thing you care
about.

The welfare platform breaks that assumption. Zeus is observed by **several**
sensors — a Tapo camera today, a feeder scale tomorrow — and **Zeus is not himself a
device**. The questions the platform must answer ("has Zeus been seen in the last
18h?", "how much did Zeus eat today?") are about the *subject*, and their answers
have to fuse evidence from *whichever* sensor saw him. Keying everything on
`device_id` can't express "any sensor observed Zeus"; it can only express "this
camera fired."

## Decision

Model **two identities**:

- **Device** — a physical sensor (`tapo-cam-porch`, `feeder-scale-01`). It owns the
  raw event stream and stays the event-log partition key: the proven
  `PK=device_id, SK=ts` shape with TTL is unchanged (ADR from the original design
  still holds). Devices are where data *comes from*.
- **Entity** — the subject being monitored (`zeus`). It exists only in the
  **projection table**, materialised as current state + rolling baselines. Multiple
  devices' events resolve to one entity via a small **device → entity mapping**
  (config today: both sensors map to `zeus`).

Events carry enough to resolve to an entity (the mapping is applied by the
projection consumer, so the event log stays device-native and the entity view is a
*derived* projection — consistent with the CDC-derived-state stance in ADR-0002).

## Consequences

- **"Has Zeus been seen?" is answerable across sensors.** Last-seen is a property of
  the `zeus` entity, updated by a `sighting` from the camera *or* a `feeding` from the
  scale — no query has to know which device produced it.
- **Adding a sensor is a mapping change, not a read rewrite.** A new device maps to
  `zeus` and its events start feeding the same entity aggregate; the dashboard and
  rules don't change. This is the payoff that justifies the second identity.
- **The projection consumer changes shape.** It moves from "write this device's last
  value" to "fold this event into the entity's aggregate" (counts, intake totals,
  last-seen, baselines). The `ts`-versioned conditional write (ADR-0004) still guards
  idempotency/ordering — now per entity-field rather than per device.
- **`sighting` has two identities in play.** The device is the camera; the *subject*
  the Enrichment step confirmed is `zeus` (ADR-0005). Both are recorded: the event is
  device-native in the log, entity-native in the projection.
- **Single entity today, partition dimension tomorrow.** Only `zeus` exists now, kept
  deliberately simple. If the platform ever monitors more than one subject, `entity`
  becomes a partition dimension in the projection and an authorization boundary on
  reads — the model already names the seam, so that growth doesn't require a
  re-modelling.
- **Rejected:** overloading `device_id` to mean Zeus. It cannot express multi-sensor
  fusion, and it would break the moment a second sensor observes the same cat.
