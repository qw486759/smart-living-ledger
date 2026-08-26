"""Pure anomaly rules.

Rules use only fields already present in ingest/schema.py payloads, so no new
device state is invented. (A "motion-while-armed" rule was considered but there
is no armed/disarmed state in the current payloads, so it is intentionally
omitted rather than faked.)
"""
from __future__ import annotations

from typing import Any, Optional

# Safe indoor range; validation accepts -50..100C, but readings outside this
# band are operationally interesting.
TEMP_SAFE_MIN_C = 0.0
TEMP_SAFE_MAX_C = 40.0
# Validation caps watt at 2400 (breaker rating); alert as it approaches that.
PLUG_ALERT_WATT = 2000.0

# --- Cat-welfare thresholds (stateful; state comes from the entity projection /
# daily rollup, passed in by the caller — see docs/adr/0006). ---
NO_SIGHTING_ALERT_HOURS = 24.0
FEEDING_DROP_RATIO = 0.5            # today below (1 - ratio) x the 7-day baseline
FEEDING_DROP_MIN_BASELINE_G = 20.0  # baselines below this are too noisy to judge
NIGHT_INTRUSION_MULTIPLIER = 3.0    # night sightings above this x the night baseline
NIGHT_INTRUSION_MIN_COUNT = 3       # need a minimum count to be meaningful
# A camera sighting this long after the last one starts a *new visit*. Continuous
# sightings (the edge heartbeat fires ~every 60s while Zeus is around) stay inside
# this window, so only the first sighting of a visit sends an "arrival" notice.
ARRIVAL_GAP_SECONDS = 1800          # 30 minutes


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(event_type: str, payload: dict) -> Optional[dict]:
    """Return {"rule", "detail"} if the reading is anomalous, else None."""
    if event_type == "temp":
        celsius = payload.get("celsius")
        if _is_number(celsius):
            if celsius > TEMP_SAFE_MAX_C:
                return {"rule": "temp_over_max", "detail": f"{celsius}C > {TEMP_SAFE_MAX_C}C"}
            if celsius < TEMP_SAFE_MIN_C:
                return {"rule": "temp_under_min", "detail": f"{celsius}C < {TEMP_SAFE_MIN_C}C"}
    elif event_type == "plug":
        watt = payload.get("watt")
        if _is_number(watt) and watt > PLUG_ALERT_WATT:
            return {"rule": "plug_over_rated", "detail": f"{watt}W > {PLUG_ALERT_WATT}W"}
    elif event_type == "sighting":
        # Zeus in frame with another animal — possible confrontation. Per-event
        # and stateless: the vision step reports others_present on the payload.
        if payload.get("others_present") is True:
            detail = "Zeus in frame with another animal"
            count = payload.get("animal_count")
            if _is_number(count):
                detail += f" ({int(count)} animals)"
            return {"rule": "co_presence", "detail": detail}
    elif event_type == "intrusion":
        # A non-Zeus animal with Zeus not in frame — the bully cat at the door.
        # Per-event and stateless; the handler dedupes so a lingering cat doesn't spam.
        detail = "Another animal at the door, Zeus not in frame"
        count = payload.get("animal_count")
        if _is_number(count):
            detail += f" ({int(count)} animals)"
        return {"rule": "intruder_solo", "detail": detail}
    return None


# --- Welfare rules (stateful). These are pure functions of already-computed
# state (last-seen, baselines, counts); reading that state from the projection /
# rollup is the caller's job, so the rules stay unit-testable with no AWS. ---


def evaluate_no_sighting(
    now_ts: int,
    last_sighting_ts: Optional[int],
    threshold_hours: float = NO_SIGHTING_ALERT_HOURS,
) -> Optional[dict]:
    """Alert if the subject hasn't been seen for longer than the threshold.
    `last_sighting_ts` comes from the entity-state projection; None = never seen
    yet, which is not an alert condition."""
    if last_sighting_ts is None:
        return None
    gap_hours = (now_ts - last_sighting_ts) / 3600.0
    if gap_hours > threshold_hours:
        return {
            "rule": "no_sighting",
            "detail": f"not seen for {gap_hours:.1f}h > {threshold_hours}h",
        }
    return None


def is_new_arrival(
    prev_seen_ts: Optional[int],
    now_ts: int,
    gap_seconds: int = ARRIVAL_GAP_SECONDS,
) -> bool:
    """True if `now_ts` begins a new visit: Zeus was either never seen before, or
    the gap since he was last seen exceeds `gap_seconds`. The caller owns the
    state (last-seen timestamp) so this stays a pure, unit-testable decision."""
    if prev_seen_ts is None:
        return True
    return (now_ts - prev_seen_ts) > gap_seconds


def evaluate_feeding_drop(
    today_grams: float,
    baseline_grams: float,
    drop_ratio: float = FEEDING_DROP_RATIO,
    min_baseline: float = FEEDING_DROP_MIN_BASELINE_G,
) -> Optional[dict]:
    """Alert if today's intake is a large drop vs the 7-day baseline (an early
    illness signal). `baseline_grams` comes from the daily rollup."""
    if not _is_number(today_grams) or not _is_number(baseline_grams):
        return None
    if baseline_grams < min_baseline:
        return None
    threshold = baseline_grams * (1.0 - drop_ratio)
    if today_grams < threshold:
        return {
            "rule": "feeding_drop",
            "detail": (
                f"{today_grams:.0f}g < {threshold:.0f}g "
                f"({int(drop_ratio * 100)}% below 7d avg {baseline_grams:.0f}g)"
            ),
        }
    return None


def evaluate_night_intrusion(
    night_sighting_count: float,
    baseline_night_avg: float,
    multiplier: float = NIGHT_INTRUSION_MULTIPLIER,
    min_count: int = NIGHT_INTRUSION_MIN_COUNT,
) -> Optional[dict]:
    """Alert on an unusual spike in night-time sightings (possible territory
    intrusion by another animal). Counts/baseline come from the rollup."""
    if not _is_number(night_sighting_count) or not _is_number(baseline_night_avg):
        return None
    if night_sighting_count < min_count:
        return None
    # With an established baseline, alert on a multiplier-fold spike; with no
    # baseline yet, a burst above the minimum count is itself notable.
    if baseline_night_avg <= 0 or night_sighting_count > baseline_night_avg * multiplier:
        detail = f"{int(night_sighting_count)} night sightings" + (
            f" > {multiplier}x baseline {baseline_night_avg:.1f}"
            if baseline_night_avg > 0
            else ", no baseline yet"
        )
        return {"rule": "night_intrusion", "detail": detail}
    return None


# Human-readable headlines for each alert rule (no emoji — see user preference).
_ALERT_HEADLINES = {
    "arrival": "Zeus is here",
    "co_presence": "Zeus is in frame with another animal",
    "intruder_solo": "Another animal at the door (Zeus not around)",
    "no_sighting": "Zeus hasn't been seen recently",
    "feeding_drop": "Zeus's food intake has dropped",
    "night_intrusion": "Unusual night-time activity in the territory",
    "temp_over_max": "Temperature above safe range",
    "temp_under_min": "Temperature below safe range",
    "plug_over_rated": "Plug wattage near breaker rating",
}


def format_alert_message(anomaly: dict, device_id: str = "") -> str:
    """Turn an anomaly {rule, detail} into a human-readable notification line."""
    rule = anomaly.get("rule", "unknown")
    head = _ALERT_HEADLINES.get(rule, f"Alert: {rule}")
    msg = f"[Zeus] {head}"
    detail = anomaly.get("detail")
    if detail:
        msg += f" - {detail}"
    if device_id:
        msg += f" (device {device_id})"
    return msg
