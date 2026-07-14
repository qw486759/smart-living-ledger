# Extending Event-Driven IoT Platform

## Adding a new device type

Device types are enum-driven on purpose: `ingest/schema.py` is the single source
of truth for what types exist and what their payloads must look like. Adding a
type is a small, ordered change across a few files. Do them in this order so the
tests you write can drive the rest.

Worked example: adding a `door` sensor that reports `{"open": true|false}`.

### 1. `ingest/schema.py` — define the type and its payload rules

This is the only place the contract is defined, and it has no AWS imports, so it's
where you can iterate fastest.

- Add the type to the `VALID_TYPES` set:
  ```python
  VALID_TYPES = {"motion", "plug", "temp", "voice", "door"}
  ```
- Write a payload validator mirroring the existing ones:
  ```python
  def _validate_door(payload: dict[str, Any]) -> None:
      if not isinstance(payload.get("open"), bool):
          raise ValidationError("door payload requires boolean field 'open'")
  ```
- Register it in the `validators` dispatch dict inside `validate_event`:
  ```python
  validators = {..., "door": _validate_door}
  ```

For numeric payloads, copy the range-check pattern from `_validate_plug` /
`_validate_temp` (use `_is_number` and reject out-of-range values explicitly)
rather than trusting the value. That range check is what protects the store from
sensor glitches (e.g. the negative-wattage meter-rollover case in the tests).

### 2. `tests/test_schema.py` — lock the contract

Add at minimum: one accepted-payload test, one rejected-payload test, and a
boundary case if the payload has ranges. These run in CI on every push with no
AWS, so they're your fast feedback loop. Follow the existing naming style
(`test_accepts_...`, `test_rejects_...`).

### 3. `simulator/simulator.py` — emit the new type

- Add a payload factory:
  ```python
  def make_door_payload() -> dict[str, bool]:
      return {"open": random.choice([True, False])}
  ```
- Add a `DEVICE_CONFIG` entry:
  ```python
  {"device_id": "door-sensor-001", "type": "door", "payload_fn": make_door_payload},
  ```
  The simulator spins up one thread per config entry automatically — no other
  change needed.

### 4. `infra/template.yaml` — usually nothing

The ingest/query Lambdas and the table are type-agnostic (the type is just an
attribute), so a new device type needs **no infrastructure change**. You only
touch the template if the new type needs a different access pattern (e.g. its own
index) or a different alarm.

### 5. `dashboard/` — only if you want a panel for it

The dashboard is hand-wired panels, not generated from the schema. To surface the
new type:

- `dashboard/index.html`: add a `<article class="panel ...">` following the motion
  or voice status-card pattern (or a chart panel following temp/plug).
- `dashboard/app.js`: add a `fetchEvents({ type: 'door', ... })` call in
  `refreshDashboard`, and an `update...Status`/chart function to render it.

If you skip this, the new events are still ingested, stored, and queryable via the
API (`GET /events?type=door`) — they just won't have a dedicated panel.

### Checklist

- [ ] Type added to `VALID_TYPES` and a validator registered (`schema.py`)
- [ ] Accept + reject (+ boundary) tests added and passing (`test_schema.py`)
- [ ] Payload factory and `DEVICE_CONFIG` entry added (`simulator.py`)
- [ ] Infra reviewed — change only if a new access pattern/alarm is needed
- [ ] Dashboard panel added (optional)

## Why the enum-driven shape

Keeping types and payload rules in one AWS-free module is what makes the above
cheap: validation is unit-testable without deploying, the same rules back both the
Lambda and the local FastAPI app (so "works locally" means "works in the Lambda"),
and the storage/query layer never needs to know which types exist. The cost is
that the dashboard is not auto-generated from the schema — panels are added by
hand — which is a deliberate trade for a small, dependency-free UI.

## Changing validation limits

Payload ranges (plug wattage, temperature bounds), the voice command set, and the
timestamp skew/age windows are constants at the top of `schema.py`
(`VALID_VOICE_COMMANDS`, `MAX_CLOCK_SKEW_SECONDS`, `MAX_EVENT_AGE_SECONDS`, and the
inline range checks). Change them there and update the corresponding boundary test
so the intended limit is pinned.
</content>
