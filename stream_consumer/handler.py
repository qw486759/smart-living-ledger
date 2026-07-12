import json
import logging
import os
from typing import Any

import boto3
from stream_logic import build_event_stored_message, is_insert, new_image_to_item

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOPIC_ARN = os.environ["EVENT_STORED_TOPIC_ARN"]
STAGE = os.environ.get("STAGE", "dev")

sns = boto3.client("sns")


def lambda_handler(event: dict, context: Any) -> dict:
    """Read INSERT stream records and republish each as an event-stored message
    on SNS. Failures propagate so the event source mapping can retry, bisect,
    and finally route the poison batch to the stream-consumer DLQ."""
    records = event.get("Records", [])
    published = 0
    skipped = 0

    for record in records:
        if not is_insert(record):
            skipped += 1
            continue

        message = build_event_stored_message(new_image_to_item(record))
        sns.publish(
            TopicArn=TOPIC_ARN,
            Message=json.dumps(message, sort_keys=True),
            MessageAttributes={
                "type": {"DataType": "String", "StringValue": message["type"]}
            },
        )
        published += 1
        _log(
            "info",
            "event_published",
            device_id=message["device_id"],
            event_type=message["type"],
            ts=message["ts"],
        )

    _log("info", "stream_batch_processed", published=published, skipped=skipped)
    return {"published": published, "skipped": skipped}


def _log(level: str, event: str, **context: Any) -> None:
    payload = {"event": event, **{k: v for k, v in context.items() if v is not None}}
    getattr(logger, level)(json.dumps(payload, sort_keys=True))
