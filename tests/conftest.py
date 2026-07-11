import os
import time

import pytest

@pytest.fixture
def api_url():
    url = os.environ.get("SLL_API_URL")
    if not url:
        pytest.skip(
            "SLL_API_URL not set — skipping integration/load tests. "
            "Run with: $env:SLL_API_URL='https://your-api-url/dev'"
        )
    return url.rstrip("/")


@pytest.fixture
def ingest_url(api_url):
    return f"{api_url}/events"


@pytest.fixture
def valid_motion_payload():
    return {
        "device_id": "test-motion-001",
        "type": "motion",
        "payload": {"detected": True},
        "ts": int(time.time()),
    }


@pytest.fixture
def valid_temp_payload():
    return {
        "device_id": "test-temp-001",
        "type": "temp",
        "payload": {"celsius": 22.5, "humidity": 55.0},
        "ts": int(time.time()),
    }


@pytest.fixture
def valid_plug_payload():
    return {
        "device_id": "test-plug-001",
        "type": "plug",
        "payload": {"watt": 450.0},
        "ts": int(time.time()),
    }


@pytest.fixture
def valid_voice_payload():
    return {
        "device_id": "test-voice-001",
        "type": "voice",
        "payload": {"command": "turn on lights"},
        "ts": int(time.time()),
    }


@pytest.fixture(autouse=True)
def cleanup_test_items():
    """Delete any DynamoDB items written by tests after each test."""
    yield
    table_name = os.environ.get("TABLE_NAME", "sll-events-dev")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    if not table_name:
        return
    try:
        import boto3
        table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        test_prefixes = ("test-", "inttest-", "e2e-test-", "loadtest-")
        scan_kwargs = {}
        while True:
            resp = table.scan(**scan_kwargs)
            with table.batch_writer() as batch:
                for item in resp["Items"]:
                    did = str(item.get("device_id", ""))
                    if any(did.startswith(p) for p in test_prefixes):
                        batch.delete_item(
                            Key={"device_id": item["device_id"], "ts": item["ts"]}
                        )
            if "LastEvaluatedKey" not in resp:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    except Exception:
        pass