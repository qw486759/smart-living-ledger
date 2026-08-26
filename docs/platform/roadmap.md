# Implementation Roadmap

> Companion to [`architecture.md`](architecture.md). Build order, phased so the
> platform has real data and a story early, with hardware and the LLM added once the
> pipeline is proven. Each phase lists the concrete files it touches.

## Phase 0 — pipeline + real data, no hardware (a weekend)

Get real Zeus data flowing through the existing pipeline using manual check-ins, so
the narrative and the data exist before any device or model work.

| Work | Files |
|---|---|
| Add `sighting` / `feeding` event types + validators | `ingest/schema.py`, `tests/test_schema.py` |
| Manual check-in source (iOS Shortcut or a one-page web button → `POST /events`) | small static page / shortcut (no repo change to the API) |
| Zeus welfare rules (`no_sighting_Nh`, `feeding_drop`, `night_intrusion`, `co_presence`) | `alerter/rules.py`, `alerter/handler.py`, tests |
| Entity-state projection (per-entity aggregate, not per-device last value) | `projection_consumer/projection_logic.py`, tests |
| Dashboard → Zeus panels (last-seen, intake trend, sighting heatmap, alert state) | `dashboard/*` |
| Device → entity mapping ([ADR-0006](../adr/0006-entity-vs-device-modeling.md)) | config in projection consumer |

**Exit:** real sightings/feedings you enter by hand show up on a Zeus dashboard and
can trigger a `feeding_drop` alert. Fully working system, zero hardware.

## Phase 1 — real sensors (~$10 hardware)

Replace manual check-ins with the Tapo camera and a feeder scale; stand up the Edge
Bridge and the candidate-frame path.

| Work | Files |
|---|---|
| Edge Bridge: ONVIF motion subscribe + RTSP frame capture + local buffer | `edge/` (new) |
| Edge gate: motion events + periodic poll (catch in-view misses) + coarse animal detection | `edge/` |
| Upload candidate frames to encrypted S3 | `edge/`, `infra/template.yaml` (bucket, KMS, lifecycle, policy — [ADR-0007](../adr/0007-image-privacy-and-retention.md)) |
| Feeder scale (ESP32 + HX711) → `feeding` events | firmware + existing `/events` contract |
| API key for the edge client | `infra/template.yaml` |

**Exit:** the camera drives real candidate frames into S3; the scale reports real
intake. (Frames aren't yet classified — that's Phase 2.)

## Phase 2 — recognition + LLM + notification (the headline)

Turn candidate frames into confirmed Zeus sightings, add the welfare summary, and
close the alert loop to a real channel.

| Work | Files |
|---|---|
| Enrichment Lambda: Bedrock Converse VLM, `{is_zeus, confidence, animal_count, others_present}` structured output | `enrichment/` (new), `infra/template.yaml` (S3→Lambda trigger, Bedrock IAM) |
| Model-agnostic recognizer, config-switch Nova Lite ↔ Claude Sonnet ([ADR-0005](../adr/0005-edge-vs-cloud-inference.md)) | `enrichment/` |
| Recognition benchmark on real Zeus photos (+ optional confidence cascade) | `enrichment/`, `tests/` |
| Daily rollup Lambda (trends + 7-day baselines) | `analytics/` (new), scheduled in `infra/template.yaml` |
| Welfare summary via Bedrock Claude, structured output ([ADR-0008](../adr/0008-llm-assistant-tier.md)) | `analytics/` |
| Notification: SNS → LINE/SMS/email (reuse LINE webhook experience) | `notification/` (new) |
| Deploy LLM calls on Bedrock (region model access, inference profiles) | `infra/template.yaml` |

**Exit:** the camera sees Zeus → Bedrock confirms it's him → `sighting` stored →
dashboard + daily welfare summary + an alert to your phone when something's off. All
four capabilities — coding, architecture, LLM, cloud — demonstrably wired together.

## Later (recorded, not scheduled)

- Auth story (API keys / Cognito / IoT Core certs) + CORS lock-down before leaving a
  trusted account.
- NL query agent (read-only tool-use over the query API) — deferred in
  [ADR-0008](../adr/0008-llm-assistant-tier.md).
- Multi-subject support (`entity` as a partition + authz dimension).
- Fine-tuned/self-hosted vision model if cost/privacy/volume ever demand it.
