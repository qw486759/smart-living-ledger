# 0007 — Image privacy and retention

- **Status:** Accepted
- **Date:** 2026-08-21
- **Applies to:** the candidate-frame S3 bucket, Edge Bridge, `enrichment/`, IAM

## Context

Two-stage recognition (ADR-0005) means camera frames now leave the home and land in
S3 for the Enrichment step. Camera footage is sensitive — and an *outdoor* camera can
incidentally capture people, neighbours, and the street, not just Zeus. Once frames
are in the cloud they are a real data-protection surface, so how they are minimised,
stored, retained, and accessed has to be a deliberate decision, not a default.

## Decision

Treat frames as sensitive-by-default and minimise their exposure at every step.

- **Minimise what is uploaded.** Only edge-gated **candidate** frames go up (ADR-0005),
  never the full motion stream. The edge gate is the first privacy control, not just a
  cost control.
- **Encrypt and lock the bucket.** SSE-KMS encryption at rest; S3 Block Public Access
  on; a bucket policy that grants read/write only to the Enrichment Lambda's role
  (least privilege); TLS in transit.
- **Retain briefly, then delete.** A short S3 lifecycle (default **7 days**) expires
  candidate frames automatically; the steady state keeps almost no footage. The
  recognition result (`{is_zeus, confidence}` + a frame reference) is what persists,
  as a `sighting` event — **the image itself is never written to DynamoDB.**
- **No image data in the event log or the LLM summary path.** The event log and the
  welfare-summary tier see metadata only (ADR-0008). Frames exist solely for the
  recognition call.
- **Reference photos are managed, minimal, non-incidental.** The handful of Zeus
  reference photos are version-controlled, deliberately chosen (only Zeus), and stored
  with the same bucket controls — they are not third-party PII.
- **Audit access.** CloudTrail data events on the bucket; the only principal with
  access is the Enrichment role. Any human/debug access is exceptional and logged.
- **Don't build face/person recognition.** The pipeline recognises *one cat*.
  Incidental people in a frame are never the subject, never enrolled, and are deleted
  with the frame on the lifecycle. No facial analysis is performed.

## Consequences

- **The attack/exposure surface is one short-lived, encrypted bucket** — bounded by
  minimisation (edge gate), encryption, least-privilege IAM, a 7-day lifecycle, and
  audit. That is a defensible privacy posture to describe, and the reasoning is
  recorded rather than implicit.
- **Storage cost is negligible** because retention is days, not forever.
- **A real tension: retention vs debuggability.** Deleting frames fast is best for
  privacy but means a misclassification can't always be reviewed after the fact. The
  resolution: keep the default short, and if recognition tuning needs examples, use a
  *separate*, even shorter-lived, access-restricted sample bucket with explicit opt-in
  — don't lengthen retention on the main path.
- **Region/data-residency is a knob.** Bucket, KMS key, and Bedrock calls should sit
  in one chosen region so frames don't cross boundaries unexpectedly.
- **Rejected:** retaining all frames long-term (a standing privacy, cost, and
  compliance liability for no operational need), and any person/face recognition
  (out of scope and a much larger privacy obligation).
