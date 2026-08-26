import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError
from projection_logic import projection_update_params

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PROJECTION_TABLE_NAME = os.environ["PROJECTION_TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
projection = dynamodb.Table(PROJECTION_TABLE_NAME)


def lambda_handler(event: dict, context: Any) -> dict:
    """Materialize the current-state projection from event-stored messages
    delivered via SQS. Idempotent + order-tolerant conditional write; a
    ConditionalCheckFailedException means duplicate/stale and is a no-op. Any
    other error propagates so SQS can retry and eventually route to the DLQ."""
    written = 0
    stale = 0

    for record in event.get("Records", []):
        message = json.loads(record["body"])
        try:
            projection.update_item(**projection_update_params(message))
            written += 1
            _log(
                "info",
                "projection_updated",
                device_id=message["device_id"],
                event_type=message["type"],
                ts=message["ts"],
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                stale += 1
                _log(
                    "info",
                    "projection_skipped_stale_or_duplicate",
                    device_id=message.get("device_id"),
                    ts=message.get("ts"),
                )
                continue
            _log(
                "error",
                "projection_write_failed",
                device_id=message.get("device_id"),
                aws_error_code=exc.response["Error"]["Code"],
            )
            raise

    _log("info", "projection_batch_processed", written=written, stale=stale)
    return {"written": written, "stale": stale}


def _log(level: str, event: str, **context: Any) -> None:
    payload = {"event": event, **{k: v for k, v in context.items() if v is not None}}
    getattr(logger, level)(json.dumps(payload, sort_keys=True))
