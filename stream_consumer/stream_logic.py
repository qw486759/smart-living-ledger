"""Pure, AWS-free logic for the stream consumer.

Kept import-light (only boto3's TypeDeserializer, which does no I/O) so it can
be unit-tested without a live stream. The stream consumer is a change-data-
capture bridge: it turns committed DynamoDB writes into a stable domain event
on SNS. It does NOT write the projection (that is the SQS consumer's job).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

# Versioned so downstream consumers can evolve without silent breakage.
SCHEMA_VERSION = "1"

_deserializer = TypeDeserializer()


def is_insert(record: dict) -> bool:
    """Only brand-new items matter. MODIFY and REMOVE (incl. TTL deletes) are
    ignored. The event source mapping also filters to INSERT; this is defence
    in depth so the handler is correct even if that filter is misconfigured."""
    return record.get("eventName") == "INSERT"


def new_image_to_item(record: dict) -> dict[str, Any]:
    image = record.get("dynamodb", {}).get("NewImage")
    if not image:
        raise ValueError("stream record has no NewImage")
    item = {key: _deserializer.deserialize(value) for key, value in image.items()}
    return _jsonable(item)


def build_event_stored_message(item: dict) -> dict[str, Any]:
    """The pinned SNS contract. Shape is asserted by tests/test_sns_contract.py.
    Adding fields is safe; renaming/removing requires a schema_version bump."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event": "event_stored",
        "device_id": item["device_id"],
        "type": item["type"],
        "ts": int(item["ts"]),
        "payload": item.get("payload", {}),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {key: _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_jsonable(inner) for inner in value]
    return value
