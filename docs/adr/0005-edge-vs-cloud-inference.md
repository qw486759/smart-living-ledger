# 0005 — Two-stage sighting recognition: edge motion-gating, cloud Claude vision

- **Status:** Accepted
- **Date:** 2026-08-21
- **Applies to:** Edge Bridge (`edge/`), the Enrichment Lambda (`enrichment/`), the `sighting` event path, image handling

## Context

The platform ingests real observations of a specific outdoor cat ("Zeus") from a
Tapo camera. The camera exposes RTSP video and ONVIF motion events but no
third-party cloud API. A motion trigger alone cannot tell Zeus apart from another
cat, a raccoon, wind, or a shadow, so the system needs a recognition step that
answers "is this Zeus?" before a `sighting` event is emitted.

There were three shapes for that step:

1. **Cloud recognition, every frame.** Upload every motion frame to S3 and classify
   in the cloud. Simple, but every frame leaves the home and the bill scales with
   raw motion volume.
2. **On-device custom model.** Train a small CNN on the edge; nothing leaves the
   home. Best for privacy, but identity resolution ("is this *Zeus*?") requires a
   labelled training set and a model artifact to maintain — and it keeps the LLM out
   of the design entirely.
3. **Two-stage: edge motion-gating + cloud Claude vision.** A cheap on-device gate
   decides whether a frame is even worth looking at; only candidate frames go to the
   cloud, where Claude's vision model does few-shot identity resolution.

The unlock for option 3 is that **Claude is a vision-language model**. Off-the-shelf
label APIs (Rekognition) stop at "Cat" and can't distinguish an individual, and a
custom CNN needs a training set — but Claude can be given a handful of reference
photos of Zeus **in-context** alongside a candidate frame and asked "is this the same
cat?", doing few-shot identity resolution with **no training set to build or
maintain**. That capability is worth exercising, and it only exists in the cloud —
so recognition is where the LLM and the cloud naturally meet.

## Decision

Use **two-stage recognition**.

- **Stage 1 — edge motion-gating (on the always-on home machine).** The Edge Bridge
  pulls a frame from RTSP and runs a *lightweight* local check — a coarse "is there
  an animal-shaped foreground object?" filter. Its only job is to decide **whether a
  frame is worth sending to the cloud**, not to identify Zeus. Most frames (wind,
  light, empty scenes) are dropped here and never leave the home. It runs on **two
  triggers**: ONVIF motion events (immediate) **and a periodic poll** (grab a frame
  every N seconds regardless of motion), so a cat that is *in view but didn't trip
  Tapo's motion detector* — a real gap with small, slow, or distant animals — is
  still caught. What the gate cannot recover is a cat that isn't in the camera's view
  at all; that's a physical limit, not a software one, and it's why "not seen for N
  hours" is a soft signal, not proof of absence.
- **Stage 2 — cloud VLM recognition via Bedrock (AWS).** A candidate frame is
  uploaded to an encrypted S3 bucket; the S3 event triggers an Enrichment Lambda that
  calls a vision-language model through the **Bedrock Converse API** with a system
  prompt carrying a few reference photos of Zeus plus the rules, and the candidate
  frame as the user image. It returns **structured output**
  `{is_zeus, confidence, animal_count, others_present}` (via a Converse tool schema) —
  not just whether it's Zeus, but how many animals are in frame and whether any
  non-Zeus animal is present. `is_zeus == true` produces a `sighting` event (entering
  the existing ingest pipeline); when Zeus shares the frame with another animal
  (`others_present`), that drives a `co_presence` alert (a possible confrontation —
  the rival-cat case). Recognising a *specific* rival needs no extra reference photos:
  "is there a non-Zeus animal here" is zero-shot.

  The recognizer is **model-agnostic**. Because both Amazon Nova and Claude are on
  Bedrock and share the Converse request shape, the model is a **config value**,
  switched by changing one model ID. Two are wired in — `amazon.nova-lite-v1:0`
  (cheapest) and `anthropic.claude-sonnet-4-6` (stronger; a Bedrock deployment may
  need a region inference profile, e.g. `us.anthropic.claude-sonnet-4-6`) — so we can
  A/B them on real Zeus photos and fall back to Claude if Nova's per-individual
  accuracy isn't good enough. Optionally a **confidence cascade** runs Nova first and
  escalates only low-confidence frames to Claude, so most frames pay the cheap price
  and only the uncertain ones pay for the stronger model.

The deciding factors:

- **Few-shot beats training.** Claude's in-context reference-photo comparison removes
  the training-set-and-model-artifact burden that on-device identity resolution would
  carry. Maintenance becomes "keep a few good photos of Zeus," not "retrain a CNN."
- **The edge gate keeps privacy and cost bounded.** Recognition needs frames in the
  cloud, which breaks a strict "footage never leaves the home" stance — but the gate
  means only a small number of *candidate* frames go up, not the full motion stream.
  This is a deliberate privacy/cost ↔ capability trade, not an accident (see
  ADR-0007 for the image-handling controls that follow from it).
- **It is the point where the four capabilities meet.** Coding (edge bridge +
  Enrichment Lambda), architecture (edge/cloud split + S3 + event-driven), LLM
  (Claude vision, few-shot), and cloud (AWS + Claude API) all land on this one path.

## Consequences

- **Some footage now goes to the cloud** — no longer zero. Candidate frames land in
  an encrypted S3 bucket with a bucket policy, a short lifecycle, and access
  auditing; the edge gate keeps the volume minimal. The full image-privacy story is
  ADR-0007.
- **Recognition is asynchronous, so the LLM is never on a blocking path.** The chain
  is motion → S3 → Lambda → Claude → `sighting` event. A slow or failed Claude call
  delays *that one sighting* (retry, or dead-letter the candidate frame); it cannot
  delay any other write, and welfare alerting runs on events already in the pipeline,
  so it is unaffected.
- **Model choice is the main cost dial.** At expected candidate volume: Nova Lite
  ~**$1–2/month**, Claude Sonnet ~**$7/month**, a Nova→Claude cascade lands between
  the two (mostly Nova price). All are far below the rejected Rekognition Custom
  Labels path (billed per inference-unit-hour, ~$120+/month). Prompt caching on the
  fixed reference photos + system prompt stacks on top; further tunable by tightening
  the edge gate or de-duplicating repeat sightings within a short window.
- **`confidence` travels with the event** so downstream rules and the dashboard can
  treat a 0.55 detection differently from a 0.98 one, and the identity threshold can
  be tuned without redeploying.
- **A reference-photo set replaces a training set.** We maintain a small folder of
  Zeus photos instead of a labelled dataset and model artifact — a real but small
  maintenance cost, accepted because it is what makes few-shot recognition work.
- **The edge gate is deliberately dumb.** It does motion + coarse foreground/animal
  detection only — cheap, no per-individual identity. Keeping it simple is what makes
  it free to run and easy to reason about; all the hard judgement is Claude's.
- **Rejected:** every-frame cloud recognition (unbounded footage upload and cost) and
  on-device custom model (training-set burden, and it forgoes the LLM capability this
  project deliberately wants to show).
