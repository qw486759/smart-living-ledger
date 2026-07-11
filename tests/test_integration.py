import os
import time

import boto3
import requests

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
TABLE_NAME = os.environ.get("SLL_TABLE_NAME", "sll-events-dev")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def make_ts():
    return int(time.time())


def post_event(ingest_url, payload):
    return requests.post(ingest_url, json=payload, timeout=10)


def test_ingests_motion_event(ingest_url):
    ts = make_ts()
    payload = {
        "device_id": "inttest-motion-001",
        "type": "motion",
        "payload": {"detected": True},
        "ts": ts,
    }
    response = post_event(ingest_url, payload)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"


def test_ingests_temperature_event(ingest_url):
    ts = make_ts()
    payload = {
        "device_id": "inttest-temp-001",
        "type": "temp",
        "payload": {"celsius": 21.0, "humidity": 60.0},
        "ts": ts,
    }
    response = post_event(ingest_url, payload)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"


def test_ingests_plug_event(ingest_url):
    ts = make_ts()
    payload = {
        "device_id": "inttest-plug-001",
        "type": "plug",
        "payload": {"watt": 300.0},
        "ts": ts,
    }
    response = post_event(ingest_url, payload)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"


def test_ingests_voice_command_event(ingest_url):
    ts = make_ts()
    payload = {
        "device_id": "inttest-voice-001",
        "type": "voice",
        "payload": {"command": "status check"},
        "ts": ts,
    }
    response = post_event(ingest_url, payload)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"


def test_persists_accepted_event_to_dynamodb(ingest_url):
    ts = make_ts()
    device_id = f"inttest-verify-{ts}"
    payload = {
        "device_id": device_id,
        "type": "motion",
        "payload": {"detected": False},
        "ts": ts,
    }

    response = post_event(ingest_url, payload)
    assert response.status_code == 200

    time.sleep(1)
    result = table.get_item(Key={"device_id": device_id, "ts": ts})
    assert "Item" in result, "Item not found in DynamoDB after successful ingest"
    assert result["Item"]["type"] == "motion"


def test_rejects_unknown_event_type(ingest_url):
    payload = {
        "device_id": "inttest-bad-001",
        "type": "invalid",
        "payload": {"detected": True},
        "ts": make_ts(),
    }
    response = post_event(ingest_url, payload)
    assert response.status_code in (
        400,
        422,
    ), f"Expected 4xx, got {response.status_code}"


def test_rejects_plug_wattage_above_device_rating(ingest_url):
    payload = {
        "device_id": "inttest-bad-002",
        "type": "plug",
        "payload": {"watt": 9999.0},
        "ts": make_ts(),
    }
    response = post_event(ingest_url, payload)
    assert response.status_code in (
        400,
        422,
    ), f"Expected 4xx, got {response.status_code}"


def test_rejects_event_missing_required_fields(ingest_url):
    payload = {"type": "motion", "ts": make_ts()}
    response = post_event(ingest_url, payload)
    assert response.status_code in (
        400,
        422,
    ), f"Expected 4xx, got {response.status_code}"
