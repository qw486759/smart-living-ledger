import importlib
import json
import os
import sys
import time

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("TABLE_NAME", "unit-test-table")
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "ingest"))


def test_ingest_error_response_uses_stable_error_contract():
    handler = importlib.import_module("ingest.handler")

    response = handler._error_response(
        422, "validation_failed", "device_id is required"
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 422
    assert body == {"error": "device_id is required", "code": "VALIDATION_ERROR"}


def test_query_error_response_uses_stable_error_contract():
    handler = importlib.import_module("query.handler")

    response = handler._error_response(
        400, "invalid_limit", "limit must be between 1 and 500"
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body == {"error": "limit must be between 1 and 500", "code": "INVALID_LIMIT"}


def test_local_and_lambda_success_contracts_match(tmp_path, monkeypatch):
    """The local FastAPI ingest and the Lambda ingest must emit the same
    success-response contract, so the two paths can't silently drift apart."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ingest import local_app

    ingest_handler = importlib.import_module("ingest.handler")

    # Stub DynamoDB so the Lambda success path runs without AWS.
    class _StubTable:
        def put_item(self, **kwargs):
            return {}

    monkeypatch.setattr(ingest_handler, "table", _StubTable())
    monkeypatch.setattr(local_app, "EVENTS_FILE", tmp_path / "local_events.jsonl")

    valid_event = {
        "device_id": "contract-check-001",
        "type": "motion",
        "payload": {"detected": True},
        "ts": int(time.time()),
    }

    lambda_response = ingest_handler.lambda_handler(
        {"body": json.dumps(valid_event)}, None
    )
    lambda_body = json.loads(lambda_response["body"])

    local_body = TestClient(local_app.app).post("/events", json=valid_event).json()

    assert lambda_response["statusCode"] == 200
    assert set(lambda_body) == set(local_body) == {"status", "device_id", "ts"}
    assert lambda_body["status"] == local_body["status"] == "ok"
    assert lambda_body["device_id"] == local_body["device_id"] == "contract-check-001"
