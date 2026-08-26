import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
PROJECTION_TABLE_NAME = os.environ.get("PROJECTION_TABLE_NAME")
FRAMES_BUCKET = os.environ.get("FRAMES_BUCKET")
TYPE_TS_INDEX = "type-ts-index"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
DEFAULT_ENTITY = "zeus"
ENTITY_STATE_SK = "STATE"
GALLERY_DEFAULT_LIMIT = 12
GALLERY_MAX_LIMIT = 60
FRAME_URL_TTL_SECONDS = 3600  # presigned image URL lifetime

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
projection_table = dynamodb.Table(PROJECTION_TABLE_NAME) if PROJECTION_TABLE_NAME else None
s3 = boto3.client("s3")

ERROR_CODES = {
    "invalid_limit": "INVALID_LIMIT",
    "invalid_time_range": "INVALID_TIME_RANGE",
    "database_error": "DATABASE_ERROR",
}


class InvalidLimitError(ValueError):
    pass


def lambda_handler(event: dict, context: Any) -> dict:
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    request_id = event.get("requestContext", {}).get("requestId", "local")

    # GET /state → current entity-state projection (the welfare dashboard's read).
    path = (
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("resourcePath")
        or ""
    )
    if path.rstrip("/").endswith("/state"):
        return _entity_state_response(query_params, request_id)

    # GET /sightings and /intrusions → recent events of that type, each with a
    # presigned photo URL, for the dashboard's visual timelines (Zeus visits /
    # other animals at the door).
    if path.rstrip("/").endswith("/sightings"):
        return _events_with_photos_response("sighting", query_params, request_id)
    if path.rstrip("/").endswith("/intrusions"):
        return _events_with_photos_response("intrusion", query_params, request_id)

    device_id = path_params.get("device_id") or query_params.get("device_id")

    _log(
        "info",
        "query_start",
        request_id=request_id,
        device_id=device_id,
        params=query_params,
    )

    try:
        limit = _parse_limit(query_params.get("limit"))
        if device_id:
            result = _query_device(device_id, query_params, limit)
        elif query_params.get("type"):
            # Dashboard per-type panels: Query the type-ts GSI, not a full Scan.
            result = _query_by_type(query_params["type"], query_params, limit)
        else:
            result = _scan_recent(limit)
    except InvalidLimitError as exc:
        _log(
            "warning",
            "query_validation_failed",
            request_id=request_id,
            device_id=device_id,
            detail=str(exc),
        )
        return _error_response(400, "invalid_limit", str(exc))
    except ValueError as exc:
        _log(
            "warning",
            "query_validation_failed",
            request_id=request_id,
            device_id=device_id,
            detail=str(exc),
        )
        return _error_response(400, "invalid_time_range", str(exc))
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        _log(
            "error",
            "dynamodb_query_failed",
            request_id=request_id,
            device_id=device_id,
            aws_error_code=error_code,
        )
        return _error_response(
            500,
            "database_error",
            f"DynamoDB query failed with {error_code}.",
        )

    return _response(200, result)


def _entity_state_response(query_params: dict, request_id: str) -> dict:
    """Return the current welfare state for one entity (default: zeus) from the
    projection table — one item keyed {pk: ENTITY#<entity>, device_id: STATE}."""
    if projection_table is None:
        return _error_response(
            500, "database_error", "Projection table is not configured."
        )
    entity_id = (query_params or {}).get("entity") or DEFAULT_ENTITY
    try:
        response = projection_table.get_item(
            Key={"pk": f"ENTITY#{entity_id}", "device_id": ENTITY_STATE_SK}
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        _log(
            "error",
            "entity_state_query_failed",
            request_id=request_id,
            entity=entity_id,
            aws_error_code=error_code,
        )
        return _error_response(
            500, "database_error", f"DynamoDB get failed with {error_code}."
        )

    item = response.get("Item")
    return _response(
        200, {"entity": entity_id, "state": _serialize(item) if item else None}
    )


def _events_with_photos_response(
    event_type: str, query_params: dict, request_id: str
) -> dict:
    """Return the most recent events of `event_type` (newest first), each enriched
    with a presigned URL to its camera frame so the dashboard can show the actual
    photo. Events without a vision frame (e.g. manual check-ins) get a null
    `image_url`."""
    raw_limit = (query_params or {}).get("limit")
    limit = GALLERY_DEFAULT_LIMIT
    if raw_limit is not None:
        try:
            limit = max(1, min(int(raw_limit), GALLERY_MAX_LIMIT))
        except ValueError:
            return _error_response(400, "invalid_limit", "'limit' must be an integer")

    try:
        response = table.query(
            IndexName=TYPE_TS_INDEX,
            KeyConditionExpression=Key("type").eq(event_type),
            Limit=limit,
            ScanIndexForward=False,  # newest first
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        _log(
            "error",
            "events_with_photos_query_failed",
            request_id=request_id,
            event_type=event_type,
            aws_error_code=error_code,
        )
        return _error_response(
            500, "database_error", f"DynamoDB query failed with {error_code}."
        )

    items = []
    for raw in response["Items"]:
        item = _serialize(raw)
        item["image_url"] = _frame_url(item)
        items.append(item)

    return _response(
        200,
        {
            "count": len(items),
            "items": items,
            "has_more": "LastEvaluatedKey" in response,
        },
    )


def _frame_url(item: dict) -> str | None:
    """Presigned GET URL for a vision sighting's camera frame. The frame's S3 key
    is derivable from the sighting itself — the edge uploads `frames/<zone>/<ts>.jpg`
    and the sighting carries that same zone + ts (see enrichment/recognition.py)."""
    if FRAMES_BUCKET is None:
        return None
    payload = item.get("payload") or {}
    if payload.get("source") != "vision":  # manual check-ins have no photo
        return None
    zone = payload.get("zone")
    ts = item.get("ts")
    if not zone or ts is None:
        return None
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": FRAMES_BUCKET, "Key": f"frames/{zone}/{ts}.jpg"},
            ExpiresIn=FRAME_URL_TTL_SECONDS,
        )
    except ClientError:
        return None


def _parse_limit(raw_limit: str | None) -> int:
    if raw_limit is None:
        return DEFAULT_LIMIT
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise InvalidLimitError("'limit' must be an integer between 1 and 500") from exc
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidLimitError("'limit' must be between 1 and 500")
    return limit


def _apply_time_range(key_condition, params: dict):
    from_ts = params.get("from")
    to_ts = params.get("to")
    if from_ts is None and to_ts is None:
        return key_condition
    if from_ts is None or to_ts is None:
        raise ValueError("'from' and 'to' must be provided together")
    try:
        from_value = int(from_ts)
        to_value = int(to_ts)
    except ValueError as exc:
        raise ValueError("'from' and 'to' must be integer Unix timestamps") from exc
    if from_value > to_value:
        raise ValueError("'from' must be less than or equal to 'to'")
    return key_condition & Key("ts").between(from_value, to_value)


def _query_device(device_id: str, params: dict, limit: int) -> dict:
    key_condition = _apply_time_range(Key("device_id").eq(device_id), params)

    response = table.query(
        KeyConditionExpression=key_condition,
        Limit=limit,
        ScanIndexForward=False,
    )

    return {
        "device_id": device_id,
        "count": len(response["Items"]),
        "items": [_serialize(item) for item in response["Items"]],
        "has_more": "LastEvaluatedKey" in response,
    }


def _query_by_type(event_type: str, params: dict, limit: int) -> dict:
    key_condition = _apply_time_range(Key("type").eq(event_type), params)

    response = table.query(
        IndexName=TYPE_TS_INDEX,
        KeyConditionExpression=key_condition,
        Limit=limit,
        ScanIndexForward=False,
    )

    return {
        "type": event_type,
        "count": len(response["Items"]),
        "items": [_serialize(item) for item in response["Items"]],
        "has_more": "LastEvaluatedKey" in response,
    }


def _scan_recent(limit: int) -> dict:
    # Reached only when there's no device_id and no type (both are routed to a
    # Query above), so this is an unfiltered best-effort "latest events" scan.
    collected = []
    scan_kwargs: dict[str, Any] = {}

    while len(collected) < limit:
        # Over-fetch so the newest `limit` items are likely present before the
        # client-side sort below (Scan order is not by ts).
        scan_kwargs["Limit"] = limit * 3
        response = table.scan(**scan_kwargs)
        collected.extend(response["Items"])

        if "LastEvaluatedKey" not in response:
            break
        if len(collected) >= limit:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    collected.sort(key=lambda item: item.get("ts", 0), reverse=True)
    items = collected[:limit]

    return {
        "count": len(items),
        "items": [_serialize(item) for item in items],
        "has_more": len(collected) > limit,
    }


def _serialize(item: dict) -> dict:
    result = {}
    for key, value in item.items():
        if isinstance(value, Decimal):
            result[key] = int(value) if value % 1 == 0 else float(value)
        elif isinstance(value, dict):
            result[key] = _serialize(value)
        else:
            result[key] = value
    return result


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


def _log(level: str, event: str, **context: Any) -> None:
    payload = {"event": event, **{k: v for k, v in context.items() if v is not None}}
    getattr(logger, level)(json.dumps(payload, sort_keys=True))
