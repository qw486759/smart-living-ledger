from __future__ import annotations

import time
from typing import Any

VALID_TYPES = {"motion", "plug", "temp", "voice", "sighting", "feeding", "intrusion"}
VALID_VOICE_COMMANDS = {"turn on lights", "set temperature", "status check"}
MAX_CLOCK_SKEW_SECONDS = 300
# Keep in step with the DynamoDB TTL on the event log (expire_at ≈ 30 days in
# ingest/handler.py): rejecting events older than the TTL avoids writing rows that
# would be deleted almost immediately.
MAX_EVENT_AGE_SECONDS = 30 * 86400

# Cat-welfare event bounds (see docs/adr/0005 recognition, 0006 entity model).
SIGHTING_MIN_CONFIDENCE = 0.0
SIGHTING_MAX_CONFIDENCE = 1.0
FEEDING_MAX_GRAMS = 2000.0  # sane upper bound; a feeder-bowl delta never exceeds this


class ValidationError(ValueError):
    pass


def validate_event(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    _require_str(data, "device_id")
    _require_str(data, "type")
    _require_int(data, "ts", min_value=1)

    event_type = data["type"]
    if event_type not in VALID_TYPES:
        allowed = ", ".join(sorted(VALID_TYPES))
        raise ValidationError(f"'type' must be one of [{allowed}], got '{event_type}'")

    payload = data.get("payload")
    if not isinstance(payload, dict):
        raise ValidationError("'payload' is required and must be a JSON object")

    VALIDATORS[event_type](payload)
    return data


def _validate_motion(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("detected"), bool):
        raise ValidationError("motion payload requires boolean field 'detected'")


def _validate_plug(payload: dict[str, Any]) -> None:
    watt = payload.get("watt")
    if not _is_number(watt):
        raise ValidationError("plug payload requires numeric field 'watt'")
    if not 0.0 <= float(watt) <= 2400.0:
        raise ValidationError(
            f"plug payload field 'watt' must be between 0 and 2400, got {watt}"
        )


def _validate_temp(payload: dict[str, Any]) -> None:
    celsius = payload.get("celsius")
    humidity = payload.get("humidity")

    if not _is_number(celsius):
        raise ValidationError("temp payload requires numeric field 'celsius'")
    if not -50.0 <= float(celsius) <= 100.0:
        raise ValidationError(
            f"temp payload field 'celsius' must be between -50 and 100, got {celsius}"
        )

    if not _is_number(humidity):
        raise ValidationError("temp payload requires numeric field 'humidity'")
    if not 0.0 <= float(humidity) <= 100.0:
        raise ValidationError(
            f"temp payload field 'humidity' must be between 0 and 100, got {humidity}"
        )


def _validate_voice(payload: dict[str, Any]) -> None:
    command = payload.get("command")
    if not isinstance(command, str):
        raise ValidationError("voice payload requires string field 'command'")
    if command not in VALID_VOICE_COMMANDS:
        allowed = ", ".join(sorted(VALID_VOICE_COMMANDS))
        raise ValidationError(
            f"voice payload field 'command' must be one of [{allowed}]"
        )


def _require_zone_source_confidence(payload: dict[str, Any], kind: str) -> None:
    """Shared checks for the vision/manual observation types (sighting, intrusion):
    a non-empty `zone` and `source`, and a `confidence` in [0, 1]."""
    zone = payload.get("zone")
    if not isinstance(zone, str) or not zone.strip():
        raise ValidationError(f"{kind} payload requires non-empty string field 'zone'")

    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValidationError(f"{kind} payload requires non-empty string field 'source'")

    confidence = payload.get("confidence")
    if not _is_number(confidence):
        raise ValidationError(f"{kind} payload requires numeric field 'confidence'")
    if not SIGHTING_MIN_CONFIDENCE <= float(confidence) <= SIGHTING_MAX_CONFIDENCE:
        raise ValidationError(
            f"{kind} payload field 'confidence' must be between 0 and 1, got {confidence}"
        )


def _validate_sighting(payload: dict[str, Any]) -> None:
    """A confirmed observation of the monitored subject. `source` distinguishes a
    manual check-in ("manual") from a vision-confirmed one ("vision"); `confidence`
    is the recognizer's score (1.0 for a manual check-in). See docs/adr/0005."""
    _require_zone_source_confidence(payload, "sighting")

    # Optional co-presence fields set by the vision step: how many animals are in
    # frame, and whether any non-Zeus animal is present (possible confrontation).
    animal_count = payload.get("animal_count")
    if animal_count is not None and (
        not isinstance(animal_count, int)
        or isinstance(animal_count, bool)
        or animal_count < 1
    ):
        raise ValidationError(
            "sighting payload field 'animal_count', if present, must be an integer >= 1"
        )

    others_present = payload.get("others_present")
    if others_present is not None and not isinstance(others_present, bool):
        raise ValidationError(
            "sighting payload field 'others_present', if present, must be a boolean"
        )


def _validate_intrusion(payload: dict[str, Any]) -> None:
    """A non-Zeus animal seen with Zeus NOT in frame — a possible intruder at the
    door (see docs/adr/0005). Same shape as a vision sighting, but `animal_count`
    is required (there must be an animal) and there is no Zeus to co-locate."""
    _require_zone_source_confidence(payload, "intrusion")

    animal_count = payload.get("animal_count")
    if (
        not isinstance(animal_count, int)
        or isinstance(animal_count, bool)
        or animal_count < 1
    ):
        raise ValidationError(
            "intrusion payload requires integer field 'animal_count' >= 1"
        )


def _validate_feeding(payload: dict[str, Any]) -> None:
    """How much the subject ate, from a weighing feeder. `duration_s` is optional."""
    grams = payload.get("grams")
    if not _is_number(grams):
        raise ValidationError("feeding payload requires numeric field 'grams'")
    if not 0.0 <= float(grams) <= FEEDING_MAX_GRAMS:
        raise ValidationError(
            f"feeding payload field 'grams' must be between 0 and {FEEDING_MAX_GRAMS}, got {grams}"
        )

    duration_s = payload.get("duration_s")
    if duration_s is not None:
        if not _is_number(duration_s):
            raise ValidationError(
                "feeding payload field 'duration_s', if present, must be numeric"
            )
        if float(duration_s) < 0.0:
            raise ValidationError(
                f"feeding payload field 'duration_s' must be >= 0, got {duration_s}"
            )


# Dispatch table: event type -> its payload validator. Defined at module load
# (not rebuilt per request) since it never changes.
VALIDATORS = {
    "motion": _validate_motion,
    "plug": _validate_plug,
    "temp": _validate_temp,
    "voice": _validate_voice,
    "sighting": _validate_sighting,
    "feeding": _validate_feeding,
    "intrusion": _validate_intrusion,
}


def _require_str(data: dict[str, Any], field: str) -> None:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"'{field}' is required and must be a non-empty string")


def _require_int(data: dict[str, Any], field: str, min_value: int = 0) -> None:
    value = data.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(
            f"'{field}' is required and must be an integer Unix timestamp"
        )
    if value < min_value:
        raise ValidationError(f"'{field}' must be >= {min_value}, got {value}")

    now = int(time.time())
    if value > now + MAX_CLOCK_SKEW_SECONDS:
        raise ValidationError(
            f"'{field}' cannot be more than {MAX_CLOCK_SKEW_SECONDS} seconds in the future"
        )
    if value < now - MAX_EVENT_AGE_SECONDS:
        raise ValidationError(
            f"'{field}' cannot be older than {MAX_EVENT_AGE_SECONDS} seconds"
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
