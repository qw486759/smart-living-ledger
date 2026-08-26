"""Pure logic for the projection writer.

Sole writer of the projection table (single-writer design). Two kinds of item live
in the same `(pk, device_id)` table:

- **Entity state** (the welfare platform): one item per monitored subject, keyed
  `{pk: "ENTITY#<entity>", device_id: "STATE"}`, holding the current last-sighting /
  last-feeding fields the welfare rules read. Multiple devices resolve to one entity
  (ADR-0006) — adding a sensor is a mapping entry, not a read change.
- **Legacy device state**: the original per-`(type, device)` last-value item, keyed
  `{pk: "TYPE#<type>", device_id}`, kept so nothing regresses.

Writes are idempotent AND order-tolerant via a per-field ts-versioned condition:

    attribute_not_exists(<ts_field>) OR <ts_field> < :ts

A duplicate or out-of-order (older) delivery fails the condition -> harmless no-op.
Each field group (sighting, feeding) carries its own ts stamp, since a subject's
last-sighting and last-feeding are independent timelines. Aggregate stats (today's
intake, 7-day baselines, night counts) are the rollup Lambda's job, not this
writer's.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

# Single-subject platform for now; every sensor maps to Zeus (ADR-0006).
DEVICE_ENTITY_MAP = {
    "tapo-cam-porch": "zeus",
    "feeder-scale-01": "zeus",
    "manual": "zeus",
}
DEFAULT_ENTITY = "zeus"

_ENTITY_STATE_SK = "STATE"
_WELFARE_TYPES = ("sighting", "feeding")


def entity_for(device_id: str) -> str:
    return DEVICE_ENTITY_MAP.get(device_id, DEFAULT_ENTITY)


def projection_key(message: dict) -> dict[str, str]:
    """Entity-scoped key for welfare events; legacy device-scoped key otherwise."""
    event_type = message["type"]
    if event_type in _WELFARE_TYPES:
        return {
            "pk": f"ENTITY#{entity_for(message['device_id'])}",
            "device_id": _ENTITY_STATE_SK,
        }
    return {"pk": f"TYPE#{event_type}", "device_id": message["device_id"]}


def projection_update_params(message: dict) -> dict[str, Any]:
    event_type = message["type"]
    ts = int(message["ts"])
    payload = message.get("payload", {})

    if event_type == "sighting":
        return {
            "Key": projection_key(message),
            "UpdateExpression": (
                "SET last_sighting_ts = :ts, last_sighting_zone = :zone, "
                "last_sighting_source = :source, last_sighting_confidence = :conf"
            ),
            "ConditionExpression": (
                "attribute_not_exists(last_sighting_ts) OR last_sighting_ts < :ts"
            ),
            "ExpressionAttributeValues": {
                ":ts": ts,
                ":zone": payload.get("zone"),
                ":source": payload.get("source"),
                ":conf": _floats_to_decimal(payload.get("confidence")),
            },
        }

    if event_type == "feeding":
        return {
            "Key": projection_key(message),
            "UpdateExpression": "SET last_feeding_ts = :ts, last_feeding_grams = :grams",
            "ConditionExpression": (
                "attribute_not_exists(last_feeding_ts) OR last_feeding_ts < :ts"
            ),
            "ExpressionAttributeValues": {
                ":ts": ts,
                ":grams": _floats_to_decimal(payload.get("grams")),
            },
        }

    # Legacy device types (motion/plug/temp/voice): original per-(type, device)
    # last-value behaviour, unchanged.
    return {
        "Key": projection_key(message),
        "UpdateExpression": "SET #ts = :ts, payload = :payload",
        "ConditionExpression": "attribute_not_exists(#ts) OR #ts < :ts",
        "ExpressionAttributeNames": {"#ts": "ts"},
        "ExpressionAttributeValues": {
            ":ts": ts,
            ":payload": _floats_to_decimal(payload),
        },
    }


def _floats_to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {key: _floats_to_decimal(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(value) for value in obj]
    return obj
