import importlib
import json
import os
import sys

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("STAGE", "test")
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "alerter"))

from alerter import rules  # noqa: E402


def test_temp_rules():
    assert rules.evaluate("temp", {"celsius": 45.0})["rule"] == "temp_over_max"
    assert rules.evaluate("temp", {"celsius": -5.0})["rule"] == "temp_under_min"
    assert rules.evaluate("temp", {"celsius": 22.0}) is None


def test_plug_rule():
    assert rules.evaluate("plug", {"watt": 2200.0})["rule"] == "plug_over_rated"
    assert rules.evaluate("plug", {"watt": 500.0}) is None


def test_non_alerting_types_return_none():
    assert rules.evaluate("motion", {"detected": True}) is None
    assert rules.evaluate("voice", {"command": "status check"}) is None


class _SpyCW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        return {}


def _sns_event(message):
    return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}


def _load_handler(monkeypatch):
    handler = importlib.import_module("alerter.handler")
    spy = _SpyCW()
    monkeypatch.setattr(handler, "cloudwatch", spy)
    return handler, spy


def test_handler_emits_metric_on_anomaly(monkeypatch):
    handler, spy = _load_handler(monkeypatch)
    msg = {"device_id": "temp-sensor-001", "type": "temp", "ts": 1, "payload": {"celsius": 50.0}}

    result = handler.lambda_handler(_sns_event(msg), None)

    assert result == {"alerts": 1}
    assert len(spy.calls) == 1
    dims = {d["Name"]: d["Value"] for d in spy.calls[0]["MetricData"][0]["Dimensions"]}
    assert dims["AnomalyType"] == "temp_over_max"
    assert spy.calls[0]["Namespace"] == "EventDrivenIotPlatform"


def test_handler_silent_on_normal_reading(monkeypatch):
    handler, spy = _load_handler(monkeypatch)
    msg = {"device_id": "temp-sensor-001", "type": "temp", "ts": 1, "payload": {"celsius": 21.0}}

    result = handler.lambda_handler(_sns_event(msg), None)

    assert result == {"alerts": 0}
    assert spy.calls == []
