import importlib
import json
import os
import sys

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("EVENT_STORED_TOPIC_ARN", "arn:aws:sns:us-east-1:000:sll-test")
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "stream_consumer"))

from stream_consumer import stream_logic as logic  # noqa: E402


def _insert_record():
    return {
        "eventName": "INSERT",
        "dynamodb": {
            "NewImage": {
                "device_id": {"S": "temp-sensor-001"},
                "type": {"S": "temp"},
                "ts": {"N": "1778040094"},
                "payload": {"M": {"celsius": {"N": "22.5"}, "humidity": {"N": "50"}}},
                "expire_at": {"N": "1780632094"},
            }
        },
    }


def test_is_insert_filters_non_insert():
    assert logic.is_insert(_insert_record()) is True
    assert logic.is_insert({"eventName": "MODIFY"}) is False
    assert logic.is_insert({"eventName": "REMOVE"}) is False  # e.g. TTL delete


def test_new_image_deserializes_and_jsonifies():
    item = logic.new_image_to_item(_insert_record())
    assert item["device_id"] == "temp-sensor-001"
    assert item["ts"] == 1778040094  # Decimal -> int
    assert item["payload"]["celsius"] == 22.5  # Decimal -> float
    assert item["payload"]["humidity"] == 50  # whole number -> int
    # Must be JSON-serializable (no Decimal leaks).
    json.dumps(item)


class _SpySNS:
    def __init__(self):
        self.published = []

    def publish(self, **kwargs):
        self.published.append(kwargs)
        return {"MessageId": "test"}


def _load_handler(monkeypatch):
    handler = importlib.import_module("stream_consumer.handler")
    spy = _SpySNS()
    monkeypatch.setattr(handler, "sns", spy)
    return handler, spy


def test_handler_publishes_insert_and_skips_others(monkeypatch):
    handler, spy = _load_handler(monkeypatch)

    event = {
        "Records": [
            _insert_record(),
            {"eventName": "MODIFY", "dynamodb": {"NewImage": {}}},
            {"eventName": "REMOVE", "dynamodb": {}},
        ]
    }
    result = handler.lambda_handler(event, None)

    assert result == {"published": 1, "skipped": 2}
    assert len(spy.published) == 1
    body = json.loads(spy.published[0]["Message"])
    assert body["device_id"] == "temp-sensor-001"
    assert body["type"] == "temp"
