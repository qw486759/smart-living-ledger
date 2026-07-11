from __future__ import annotations

import time
from typing import Any

VALID_TYPES = {"motion", "plug", "temp", "voice"}
VALID_VOICE_COMMANDS = {"turn on lights", "set temperature", "status check"}
MAX_CLOCK_SKEW_SECONDS = 300
MAX_EVENT_AGE_SECONDS = 30 * 86400


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

    validators = {
        "motion": _validate_motion,
        "plug": _validate_plug,
        "temp": _validate_temp,
        "voice": _validate_voice,
    }
    validators[event_type](payload)
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
