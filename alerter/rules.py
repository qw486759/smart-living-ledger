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
    return None
