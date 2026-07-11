import importlib
import json
import os
import sys
from decimal import Decimal

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("PROJECTION_TABLE_NAME", "unit-test-projection")
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "projection_consumer"))

from botocore.exceptions import ClientError  # noqa: E402

from projection_consumer import logic  # noqa: E402


def test_update_params_are_ts_versioned_and_decimal():
    message = {"type": "temp", "device_id": "d1", "ts": 100, "payload": {"celsius": 22.5}}
    params = logic.projection_update_params(message)

    assert params["Key"] == {"pk": "TYPE#temp", "device_id": "d1"}
    assert params["ConditionExpression"] == "attribute_not_exists(#ts) OR #ts < :ts"
    assert params["ExpressionAttributeNames"] == {"#ts": "ts"}
    assert params["ExpressionAttributeValues"][":ts"] == 100
    # Floats must be Decimal for DynamoDB.
    assert params["ExpressionAttributeValues"][":payload"]["celsius"] == Decimal("22.5")


class _StubTable:
    def __init__(self, raise_exc=None):
        self.calls = []
        self.raise_exc = raise_exc

    def update_item(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return {}


def _sqs_event(message):
    return {"Records": [{"body": json.dumps(message)}]}


def _conditional_failed():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
        "UpdateItem",
    )


def _load_handler(monkeypatch, table):
    handler = importlib.import_module("projection_consumer.handler")
    monkeypatch.setattr(handler, "projection", table)
    return handler


def test_new_write_succeeds(monkeypatch):
    table = _StubTable()
    handler = _load_handler(monkeypatch, table)
    msg = {"type": "temp", "device_id": "d1", "ts": 100, "payload": {"celsius": 20.0}}

    result = handler.lambda_handler(_sqs_event(msg), None)

    assert result == {"written": 1, "stale": 0}
    assert len(table.calls) == 1


def test_duplicate_or_out_of_order_is_swallowed_as_noop(monkeypatch):
    # Both duplicate (same ts) and stale (older ts) surface as the same
    # ConditionalCheckFailedException; the writer must treat it as a no-op.
    table = _StubTable(raise_exc=_conditional_failed())
    handler = _load_handler(monkeypatch, table)
    msg = {"type": "temp", "device_id": "d1", "ts": 50, "payload": {"celsius": 19.0}}

    result = handler.lambda_handler(_sqs_event(msg), None)

    assert result == {"written": 0, "stale": 1}  # no exception raised


def test_non_conditional_error_propagates(monkeypatch):
    boom = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}},
        "UpdateItem",
    )
    table = _StubTable(raise_exc=boom)
    handler = _load_handler(monkeypatch, table)
    msg = {"type": "temp", "device_id": "d1", "ts": 100, "payload": {}}

    with pytest.raises(ClientError):
        handler.lambda_handler(_sqs_event(msg), None)
