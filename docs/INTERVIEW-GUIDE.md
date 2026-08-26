# Interview Guide — Event-Driven IoT Platform (Cat-Welfare Monitoring)

A study sheet for presenting this project in system-design and coding interviews.
Two lenses: **Architect** (system design, trade-offs, NFRs) and **SDE** (code,
correctness, testing). Everything here maps to real code and real decisions in
this repo — see `docs/adr/` for the decision records.

---

## 1. Elevator pitch (say this first)

> An **event-driven, serverless platform on AWS** that ingests real camera events,
> runs **LLM vision recognition asynchronously** to identify a specific subject,
> maintains a **real-time state projection**, and drives **rule-based alerts**.
> It is built on **event sourcing + CQRS**, **DynamoDB Streams for CDC fan-out**,
> **SNS/SQS decoupling with DLQs**, and **least-privilege Infrastructure as Code**
> (AWS SAM / CloudFormation). It started as a random-data simulator demo and was
> re-pointed at a real data source (a home camera watching an outdoor cat), which
> turned it into a system with a genuine sense-decide-act loop.

Keywords the interviewer will latch onto: *event-driven, serverless, CQRS, CDC,
idempotency, LLM/VLM, IaC, least privilege.* Be ready to expand each.

---

## 2. Architecture (be able to draw this from memory)

```
Tapo camera ──RTSP──> Edge Bridge (local: frame-diff motion gate + periodic heartbeat)
                          │ candidate frame
                          ▼
                    S3 (candidate frames; SSE, 7-day lifecycle, public access blocked)
                          │ ObjectCreated event
                          ▼
              Enrichment Lambda ──Bedrock Converse (VLM)──> {is_zeus, confidence, animal_count, others_present}
                          │ HTTP POST sighting / intrusion
                          ▼
   API GW ──> Ingest Lambda ──(schema validation)──> DynamoDB event log  (write model / source of truth)
                                                          │ DynamoDB Streams (CDC)
                                                          ▼
                                                Stream Consumer Lambda ──> SNS (event-stored topic)
                                                          ├──> SQS ──> Projection Lambda ──> DynamoDB projection (read model)
                                                          └──> Alerter Lambda ──(rules + dedupe)──> SNS Alert Topic ──> Email
   API GW ──> Query Lambda ──> projection (/state) + event-log GSI (/events, /sightings, /intrusions + presigned S3 URLs)
                          ▲
                    Dashboard (static HTML/CSS/JS)
```

**One-sentence summary:** the write path (synchronous, fast) is separated from
the read path (a projection updated asynchronously); the LLM runs on a side path,
so its latency or failure never blocks ingestion or real-time alerting.

### Components
- **Edge Bridge** (`edge/`) — polls the camera over RTSP, gates frames locally
  with an OpenCV frame-diff, uploads only candidate frames to S3, buffers to disk
  when offline.
- **Ingest** (`ingest/`) — API Gateway + Lambda; validates payloads against a
  schema; appends to the DynamoDB event log.
- **CDC fan-out** (`stream_consumer/`) — DynamoDB Streams → Lambda → SNS.
- **Projection** (`projection_consumer/`) — SQS → Lambda → current-state read model.
- **Enrichment** (`enrichment/`) — S3 trigger → Bedrock VLM → posts derived events.
- **Alerter** (`alerter/`) — SNS → Lambda → rules + stateful dedupe → email.
- **Query** (`query/`) — API Gateway + Lambda; serves the dashboard.
- **Infra** (`infra/template.yaml`) — one SAM template; all resources + IAM.

---

## 3. Key technical decisions & trade-offs

| Decision | Why | Trade-off / alternative |
|---|---|---|
| **Event sourcing** (append-only event log is the source of truth) | Full history, replayable, can derive many read models | Reads need a projection; eventual consistency |
| **CQRS** (write log vs read projection) | Simple fast writes; reads hit a pre-aggregated projection | Two models to maintain; sync lag |
| **DynamoDB Streams for CDC** | No synchronous side effects in ingest; add consumers without touching upstream | Stream ordering/retry semantics to handle |
| **SNS→SQS fan-out + DLQ** | Projection and alerting scale and retry independently; poison messages isolated | Extra infrastructure |
| **ts-versioned conditional writes** | `attribute_not_exists OR last_ts < :ts` → duplicate/out-of-order deliveries can't clobber newer state | Every entity carries a version timestamp |
| **Two-tier recognition** (edge gate + cloud VLM) | Edge cheaply drops empty frames; only candidates go to the cloud → cost/privacy/bandwidth win | Edge over-admits (cloud is the second filter) |
| **LLM async** (in enrichment, not ingest) | VLM is slow and can fail; keep it off the write and real-time-alert paths | Recognition is delayed (~10s) |
| **Model-agnostic Bedrock** (env-switch Nova ↔ Claude) | Start cheap on Nova Lite; upgrade to Claude with one env change if accuracy demands | Must abstract prompt/schema |
| **Tool-use for structured output** | VLM returns strict JSON `{is_zeus, confidence, ...}` — no natural-language parsing downstream | Depends on model's tool-calling |
| **Rule-based alerting, not LLM** | Real-time, predictable, unit-testable; LLM only senses, rules decide | Rules are less flexible |
| **Least-privilege IaC** | Per-Lambda roles, resource-level ARNs, minimal actions | More verbose template |

---

## 4. Deep-dive topics (pick 2–3, know them cold)

### 4.1 Idempotency & out-of-order delivery
SNS/SQS are **at-least-once**; messages can duplicate and arrive out of order.
The projection stores a `ts` per item and updates with a conditional expression
`attribute_not_exists(last_ts) OR last_ts < :ts`. Duplicates fail the condition and
are skipped; stale (older) messages never overwrite newer state. The same trick
powers alert dedupe — a conditional `UpdateItem` atomically advances `last_seen_ts`
so only the record that actually moves the timestamp forward can fire a notice,
which also makes concurrent deliveries safe (no double-fire).

### 4.2 LLM structured output + prompt engineering (human-in-the-loop)
Recognition uses Bedrock Converse **tool-use** to force a fixed JSON schema, so
the downstream code never parses prose. The interesting story is the failure mode
(see Challenge #1): a weak model, anchored by few-shot reference photos, will
confidently hallucinate the target in empty frames — and a confidence threshold
does **not** save you, because the model reports high confidence on garbage. The
fix was prompt engineering driven by real ground truth, verified in both
directions (true positives still detected, false positives eliminated), keeping
the cheaper model.

### 4.3 Cost-aware design
- Two-tier recognition keeps most frames off the LLM.
- **Per-record failure isolation** in enrichment: one failed POST must not fail the
  whole S3 batch, or the async retry re-runs Bedrock on every frame and *re-pays*.
- Cost levers are parameterized: heartbeat interval, motion threshold, and (future)
  prompt caching of the static reference images (~4–5× cheaper).
- Concrete cost model: ~$1/day for 24h continuous, hard-capped ~$2.9/day by the
  poll rate (at most one frame per 15s poll).

### 4.4 IaC & deployment
- SAM **S3-event circular dependency** (Bucket→Function→Role→Bucket) broken with a
  hard-coded bucket ARN.
- New API route not exposed until the stage is redeployed → explicit
  `create-deployment`.

---

## 5. Non-functional requirements (architect lens)

- **Reliability** — DLQs on the async path; CloudWatch alarms (error count, p95
  latency); X-Ray tracing.
- **Security** — IAM least privilege (per-function roles, resource-scoped ARNs);
  S3 encrypted + public access blocked + time-limited presigned URLs; secrets via
  environment variables, never in code.
- **Scalability** — fully serverless auto-scaling; DynamoDB on-demand.
- **Testability** — core logic extracted into **pure functions** (schema
  validation, alert rules, recognition mapping, projection logic) that unit-test
  with no AWS → 100 unit tests in CI.
- **Observability** — structured JSON logs, custom metric (`AnomalyDetected`),
  API access logs.

---

## 6. Challenges & how I handled them (STAR — the "how you cope" stories)

Each is framed **Context → Symptom → Root cause → Fix → Lesson**. These are the
questions interviewers dig into ("tell me about a bug you found", "a time you were
wrong", "a hard trade-off").

### Challenge 1 — VLM hallucinating the target in empty frames *(flagship story)*
- **Context:** first hour of a real 24-hour test, recognition running on Nova Lite.
- **Symptom:** the dashboard filled with high-confidence "sightings" (0.90–0.98).
  Comparing against the live camera by eye, they were an **empty porch with moving
  tree shadows** — no cat. People and a dog-walker were also mislabeled.
- **Root cause:** two compounding issues. (1) The prompt fed five reference photos
  of the target and then asked "is it here?" — this **anchored a weak model toward
  yes**. (2) The `CONFIDENCE_MIN=0.6` gate was useless because the model reported
  high confidence on hallucinations.
- **Fix:** I downloaded the actual frames, confirmed they were empty, then rewrote
  the system prompt to anchor the *negative* case — "the frame is usually EMPTY;
  railings/shadows/leaves are NEVER animals; only say yes if you clearly see a
  cat's body." I validated with a local harness: three known-empty frames flipped
  to `is_zeus=false, count=0`, and a positive control (a real cat photo) still
  returned `is_zeus=true`. Kept the cheap model; Claude remained the fallback.
- **Lesson:** VLM few-shot recognition must state the negative/empty case
  explicitly, or reference examples bias a weak model. A confidence threshold is
  not a substitute for a correct prompt. Ground-truth-driven debugging beats
  guessing.

### Challenge 2 — a "safety net" that didn't actually catch anything
- **Context:** a periodic poll was meant to catch a subject the camera's motion
  detector misses.
- **Symptom:** a cat sitting still on the porch produced **no detections** — the
  exact blind spot the feature was supposed to cover.
- **Root cause:** the "periodic poll" only controlled *how often we sampled*; every
  sample still had to pass the frame-diff motion gate. A stationary subject
  produces ~zero frame diff, so nothing was ever uploaded.
- **Fix:** added a true **heartbeat** — upload a frame at least every N seconds
  *regardless of motion*, plus upload the first frame immediately on start. Motion
  gating stays for responsiveness between heartbeats.
- **Lesson:** verify that a safeguard actually exercises the path it claims to
  cover; naming a feature "safety net" doesn't make it one.

### Challenge 3 — CloudFormation circular dependency
- **Context:** wiring the S3 → Enrichment trigger in SAM.
- **Symptom:** `cfn-lint` error E3004: Bucket → Function → Role → Bucket cycle.
- **Root cause:** the bucket's notification config depends on the function; the
  function's role referenced the bucket ARN via `!GetAtt`, closing the loop.
- **Fix:** replaced `!GetAtt Bucket.Arn` with a hard-coded ARN pattern
  (`arn:aws:s3:::<name>-${Stage}-${AWS::AccountId}`) to break the edge. Applied the
  same pattern later when the query and alerter functions needed the bucket.
- **Lesson:** in IaC, an intentional constant can be the cleanest way to break a
  reference cycle; know when `!GetAtt` is worth the coupling and when it isn't.

### Challenge 4 — CORS preflight 403 on the dashboard
- **Context:** the browser check-in page POSTing to API Gateway.
- **Symptom:** preflight `OPTIONS` returned 403 even with SAM `Cors` configured.
- **Root cause:** for this configuration (explicit `AWS::Serverless::Api` +
  function events via `RestApiId`), SAM does not generate the `OPTIONS` responder.
- **Fix:** made the POST a **CORS simple request** by sending
  `Content-Type: text/plain` (body still JSON; the handler ignores content type),
  which skips preflight entirely.
- **Lesson:** understand *why* a request triggers preflight; sometimes the simplest
  fix is to stay within the simple-request rules rather than fight the platform.

### Challenge 5 — per-record failure that re-pays for the LLM
- **Context:** enrichment processes S3 notification batches.
- **Symptom (anticipated in review):** one failed ingest POST threw out of the
  handler, failing the whole batch; S3's async retry re-invoked the function and
  **re-ran Bedrock on every frame in the batch**, paying twice.
- **Fix:** wrapped per-record processing in try/except so one bad frame is logged
  and skipped; the batch continues. Added an explicit non-2xx check in the POST.
- **Lesson:** with at-least-once retries and a paid downstream, isolate failures at
  the smallest unit so a retry doesn't multiply cost.

### Challenge 6 — alert spam vs. dedupe (and generalizing it)
- **Context:** "subject arrived" / "another animal at the door" notifications.
- **Symptom:** with a heartbeat every ~60s, a subject that lingers would generate a
  notification on every frame.
- **Fix:** introduced a per-visit dedupe using a conditional `UpdateItem` on an
  alerter-owned state item — only the first sighting of a visit (gap > 30 min)
  notifies. I then **generalized** it: "another animal present" is one concept
  whether or not the tracked subject is also there, so co-presence and solo-intruder
  share one dedupe path instead of two special cases.
- **Lesson:** prefer generalizing the underlying mechanism over layering special
  cases; it also fixed a latent spam bug in the pre-existing co-presence rule.

### Challenge 7 — trusting an edit / a deploy that didn't take
- **Context:** editing the SAM template for the enrichment function.
- **Symptom:** a change I believed I'd made wasn't actually in the file, so a
  deploy shipped nothing — twice.
- **Fix:** adopted a rule of **grep-verifying** the change is on disk before
  build/deploy, and smoke-testing the deployed endpoint after. Later caught a
  related issue where a new API route needed an explicit stage redeploy
  (`create-deployment`) to be exposed.
- **Lesson:** never assume an infra change landed — verify the artifact and the
  live behavior, not your intent.

### Challenge 8 — cost from environmental noise
- **Context:** the porch faces trees; wind moves shadows all day.
- **Symptom:** shadows tripped the motion gate constantly, uploading empty frames
  that each cost a recognition call.
- **Fix:** after confirming the cloud model correctly ignores them (so no false
  alerts, only wasted spend), raised the motion threshold to drop small-area
  shadow flutter while still admitting a real animal, with the heartbeat as backup.
  Quantified the trade-off (missing a very small/distant subject) before changing it.
- **Lesson:** separate "correctness" cost from "efficiency" cost — the shadows were
  harmless to accuracy, purely a spend optimization, so the fix could be tuned
  aggressively without risking missed detections.

### Challenge 9 — Making VLM recognition actually accurate: model choice, precision/recall & few-shot design *(flagship LLM story — the full arc)*
Challenge 1 fixed the worst empty-frame hallucinations with a prompt change; a real
24-hour test then surfaced deeper accuracy problems that became the project's richest
engineering thread. Told as stages:
- **Stage 1 — residual hallucination on a weak model.** Even after the prompt fix,
  Nova Lite still occasionally labeled an empty, shadow-heavy porch as the target at
  0.9+ confidence, non-deterministically. A confidence threshold can't fix a model
  that is confidently wrong.
- **Stage 2 — switching models revealed a precision/recall inversion.** The design was
  model-agnostic (one env var), so I switched to Claude. It stopped hallucinating on
  empty frames — but a leave-one-out test on known-target photos showed it now
  recognized the target only **1 of 5 times** (false negatives). Root cause: the
  anti-hallucination prompt demanded strict identity matching, which a careful model
  honors by refusing to claim identity it isn't sure of, while a loose model says yes
  to everything. Nova = high recall / low precision; Claude = high precision / low
  recall — *with the same prompt*.
- **Stage 3 — separating presence from identity.** I relaxed the identity bar: "the
  target is the cat that regularly appears here; a cat consistent in size/build/color
  counts, partial and rear views included; only flag a clearly different animal as an
  intruder." Claude went to **5/5 recall with no empty-frame hallucination**.
- **Stage 4 — a static distractor a single frame can't reason about.** Both models
  then flagged a fixed pile of dead leaves as an "animal." The tell that it isn't one
  is temporal — it never moves — which single-frame recognition cannot use. Describing
  the leaves in words didn't work. The fix was **few-shot with a negative exemplar**:
  adding one "empty porch (no animals)" reference image alongside the positive target
  photos. That eliminated the false positive while keeping recall at 5/5.
- **Stage 5 — reference quality over quantity.** The original reference set was five
  frames from a single burst with the cat barely in the corner — near-empty images
  labeled "target," which actively fought the negative exemplar. I replaced them with
  two clear full-body shots; a regression (recognize each new photo using the other;
  verify recent real frames stay negative) passed 2/2 recall and 6/6 precision.
- **Lessons (LLM engineering):**
  - Model choice is a precision/recall lever, not just "better/worse" — validate both directions.
  - A prompt tuned to suppress false positives can suppress true positives on a stronger
    model; separate *presence* ("is there a cat?") from *identity* ("is it the target?").
  - Few-shot needs **negative** exemplars, not only positive ones; for a fixed-scene
    distractor, a negative image beats any text description.
  - Reference quality > quantity — and every reference image costs tokens on every call.
  - Single-frame recognition can't use temporal cues ("it never moves"); a
    background/temporal signal is the deeper fix.
  - Validate with a local harness against human ground truth — and zoom in before
    trusting a low-res eyeball call (I mislabeled the leaves as an animal myself once).
- **Cost note:** Claude is ~50× Nova per token; the model-agnostic design makes this a
  one-line, reversible trade of accuracy for cost — a decision to make explicitly.

---

## 7. Honest limitations & next steps (shows maturity)

- Eventual consistency: the projection lags; not for strongly-consistent reads.
- VLM accuracy depends on prompt/model and needs ongoing calibration on real data
  (the human-in-the-loop loop is established but manual).
- Not yet built: daily rollups (to power stateful "not seen for N hours" and
  "food intake dropped" alerts), an LLM natural-language welfare summary,
  multi-subject / multi-camera support, a real negative-example benchmark.
- Strong unit coverage; end-to-end/integration tests could be expanded.

---

## 8. Anticipated Q&A (quick recall)

- **"Why not recognize synchronously in ingest?"** — the LLM is slow and can fail;
  synchronous recognition would stall writes and real-time alerts. Keep it on an
  async side path.
- **"How do you handle duplicate messages?"** — ts-versioned conditional writes;
  idempotent.
- **"How do you control cost?"** — two-tier recognition, cheap model first,
  per-record isolation to avoid re-paying, parameterized levers.
- **"How is this different from a production system?"** — honestly: single-tenant,
  no rollups, test coverage, multi-camera scaling. But the skeleton (event
  sourcing / CQRS / CDC / DLQ / least-privilege IaC) is a production pattern.
- **"What if the LLM is wrong?"** — sensing and deciding are separated (LLM senses,
  rules decide) + confidence gate + anti-hallucination prompt + upgradable model.
- **"What would you build next?"** — daily rollup for stateful health alerts, then
  an LLM welfare summary; add a negative-example benchmark to track accuracy.
