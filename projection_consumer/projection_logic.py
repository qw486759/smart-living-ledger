"""Pure logic for the projection writer.

This is the SOLE writer of the projection table (single-writer design). The
write is idempotent AND order-tolerant through one conditional expression:

    attribute_not_exists(ts) OR ts < :incoming_ts

- A duplicate delivery of the same ts fails the condition -> harmless no-op.
- An out-of-order (older) ts fails the condition -> stale write rejected.

No separate dedup table is needed; ts doubles as the version stamp.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


def projection_key(message: dict) -> dict[str, str]:
    return {"pk": f"TYPE#{message['type']}", "device_id": message["device_id"]}


def projection_update_params(message: dict) -> dict[str, Any]:
    return {
        "Key": projection_key(message),
        "UpdateExpression": "SET #ts = :ts, payload = :payload",
        "ConditionExpression": "attribute_not_exists(#ts) OR #ts < :ts",
        "ExpressionAttributeNames": {"#ts": "ts"},
        "ExpressionAttributeValues": {
            ":ts": int(message["ts"]),
            ":payload": _to_decimal(message.get("payload", {})),
        },
    }


def _to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {key: _to_decimal(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(value) for value in obj]
    return obj
