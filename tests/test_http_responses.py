import importlib
import json
import os
import sys

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
