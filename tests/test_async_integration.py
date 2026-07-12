"""End-to-end tests for the async fan-out path. These require a deployed stack
and are skipped unless the relevant env vars are set (same pattern as
test_integration.py). The redrive test intentionally waits a few minutes for a
poison message to exhaust its receive count and land in the DLQ.

Env:
  SLL_API_URL            ingest/query API base (via conftest fixtures)
  AWS_DEFAULT_REGION     default us-east-1
  SLL_STAGE              default dev (used to derive default resource names)
  SLL_PROJECTION_TABLE   default sll-projection-<stage>
  SLL_PROJECTION_QUEUE_URL / SLL_PROJECTION_DLQ_URL  required for the redrive test
"""
import os
import time

import boto3
import pytest
import requests

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
STAGE = os.environ.get("SLL_STAGE", "dev")
PROJECTION_TABLE = os.environ.get("SLL_PROJECTION_TABLE", f"sll-projection-{STAGE}")
METRIC_NAMESPACE = "SmartLivingLedger"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)
cloudwatch = boto3.client("cloudwatch", region_name=REGION)


def _poll(fn, timeout, interval=3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None


def test_event_appears_in_projection(ingest_url):
    ts = int(time.time())
    device_id = f"e2e-test-proj-{ts}"
    payload = {"device_id": device_id, "type": "temp",
               "payload": {"celsius": 21.0, "humidity": 50.0}, "ts": ts}

    assert requests.post(ingest_url, json=payload, timeout=10).status_code == 200

    table = dynamodb.Table(PROJECTION_TABLE)
    item = _poll(
        lambda: table.get_item(
            Key={"pk": "TYPE#temp", "device_id": device_id}
        ).get("Item"),
        timeout=45,
    )
    assert item is not None, "event did not reach the projection table in time"
    assert int(item["ts"]) == ts


def test_anomaly_emits_metric(ingest_url):
    ts = int(time.time())
    payload = {"device_id": f"e2e-test-anom-{ts}", "type": "temp",
               "payload": {"celsius": 55.0, "humidity": 50.0}, "ts": ts}
    start = time.gmtime(ts - 60)

    assert requests.post(ingest_url, json=payload, timeout=10).status_code == 200

    def _datapoints():
        resp = cloudwatch.get_metric_statistics(
            Namespace=METRIC_NAMESPACE,
            MetricName="AnomalyDetected",
            Dimensions=[
                {"Name": "Stage", "Value": STAGE},
                {"Name": "AnomalyType", "Value": "temp_over_max"},
            ],
            StartTime=time.strftime("%Y-%m-%dT%H:%M:%SZ", start),
            EndTime=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)),
            Period=60,
            Statistics=["Sum"],
        )
        return resp["Datapoints"] or None

    # Custom metrics can lag a minute or two.
    assert _poll(_datapoints, timeout=180, interval=15), "no AnomalyDetected datapoint"


def test_poison_message_redrives_to_dlq():
    queue_url = os.environ.get("SLL_PROJECTION_QUEUE_URL")
    dlq_url = os.environ.get("SLL_PROJECTION_DLQ_URL")
    if not queue_url or not dlq_url:
        pytest.skip("set SLL_PROJECTION_QUEUE_URL and SLL_PROJECTION_DLQ_URL")

    marker = f"poison-{int(time.time())}"
    sqs.send_message(QueueUrl=queue_url, MessageBody=f"not-json::{marker}")

    # ~maxReceiveCount (3) x visibility (60s) before it dead-letters.
    def _dlq_message():
        resp = sqs.receive_message(
            QueueUrl=dlq_url, MaxNumberOfMessages=10, WaitTimeSeconds=20,
            VisibilityTimeout=5,
        )
        for m in resp.get("Messages", []):
            if marker in m["Body"]:
                return m
        return None

    assert _poll(_dlq_message, timeout=240, interval=5), "poison never reached the DLQ"
