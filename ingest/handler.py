import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError
from schema import ValidationError, validate_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
TTL_DAYS = int(os.environ.get("TTL_DAYS", "30"))
STAGE = os.environ.get("STAGE", "dev")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

ERROR_CODES = {
    "invalid_json": "INVALID_JSON",
    "validation_failed": "VALIDATION_ERROR",
    "duplicate_event": "DUPLICATE_EVENT",
    "write_throttled": "WRITE_THROTTLED",
    "storage_error": "STORAGE_ERROR",
}


def lambda_handler(event: dict, context: Any) -> dict:
    request_id = event.get("requestContext", {}).get("requestId", "local")
    _log("info", "ingest_start", request_id=request_id, stage=STAGE)

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        _log("warning", "invalid_json", request_id=request_id, detail=str(exc))
        return _error_response(
            400,
            "invalid_json",
            f"Request body must be valid JSON: {exc.msg}",
        )

    try:
        validated = validate_event(body)
    except ValidationError as exc:
        device_id = body.get("device_id") if isinstance(body, dict) else None
        event_type = body.get("type") if isinstance(body, dict) else None
        _log(
            "warning",
            "validation_failed",
            request_id=request_id,
            device_id=device_id,
            event_type=event_type,
            detail=str(exc),
        )
        return _error_response(422, "validation_failed", str(exc))

    validated["expire_at"] = validated["ts"] + (TTL_DAYS * 86400)
    item = _floats_to_decimal(validated)

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(device_id) AND attribute_not_exists(ts)",
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        _log(
            "error",
            "dynamodb_write_failed",
            request_id=request_id,
            device_id=validated["device_id"],
            event_type=validated["type"],
            ts=validated["ts"],
            aws_error_code=error_code,
        )
        if error_code == "ConditionalCheckFailedException":
            return _error_response(
                409,
                "duplicate_event",
                "An event with this device_id and ts already exists.",
            )
        if error_code == "ProvisionedThroughputExceededException":
            return _error_response(
                429,
                "write_throttled",
                "DynamoDB write capacity was exceeded; retry with exponential backoff.",
            )
        return _error_response(
            500,
            "storage_error",
            f"DynamoDB put_item failed with {error_code}.",
        )

    _log(
        "info",
        "event_stored",
        request_id=request_id,
        device_id=validated["device_id"],
        event_type=validated["type"],
        ts=validated["ts"],
    )
    return _response(
        200,
        {
            "status": "ok",
            "device_id": validated["device_id"],
            "ts": validated["ts"],
        },
    )


def _error_response(status_code: int, code_key: str, message: str) -> dict:
    return _response(status_code, {"error": message, "code": ERROR_CODES[code_key]})


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def _floats_to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {key: _floats_to_decimal(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(value) for value in obj]
    return obj


def _log(level: str, event: str, **context: Any) -> None:
    payload = {"event": event, **{k: v for k, v in context.items() if v is not None}}
    getattr(logger, level)(json.dumps(payload, sort_keys=True))
