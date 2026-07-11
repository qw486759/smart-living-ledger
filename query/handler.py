import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

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
        result = (
            _query_device(device_id, query_params, limit)
            if device_id
            else _scan_recent(query_params, limit)
        )
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


def _query_device(device_id: str, params: dict, limit: int) -> dict:
    key_condition = Key("device_id").eq(device_id)
    from_ts = params.get("from")
    to_ts = params.get("to")

    if from_ts is not None or to_ts is not None:
        if from_ts is None or to_ts is None:
            raise ValueError("'from' and 'to' must be provided together")
        try:
            from_value = int(from_ts)
            to_value = int(to_ts)
        except ValueError as exc:
            raise ValueError("'from' and 'to' must be integer Unix timestamps") from exc
        if from_value > to_value:
            raise ValueError("'from' must be less than or equal to 'to'")
        key_condition &= Key("ts").between(from_value, to_value)

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


def _scan_recent(params: dict, limit: int) -> dict:
    event_type = params.get("type")
    collected = []
    scan_kwargs: dict[str, Any] = {}

    if event_type:
        scan_kwargs["FilterExpression"] = Attr("type").eq(event_type)

    while len(collected) < limit:
        scan_kwargs["Limit"] = limit * 3  # over-fetch to account for filter
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
