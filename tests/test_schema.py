import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ingest"))
from schema import MAX_CLOCK_SKEW_SECONDS, ValidationError, validate_event  # noqa: E402


def make_ts(offset_seconds=0):
    return int(time.time()) + offset_seconds


def test_accepts_valid_motion_event():
    event = validate_event(
        {
            "device_id": "d1",
            "type": "motion",
            "payload": {"detected": True},
            "ts": make_ts(),
        }
    )
    assert event["type"] == "motion"


def test_accepts_valid_temperature_event():
    event = validate_event(
        {
            "device_id": "d2",
            "type": "temp",
            "payload": {"celsius": 22.5, "humidity": 55.0},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["celsius"] == 22.5


def test_accepts_valid_plug_event():
    event = validate_event(
        {
            "device_id": "d3",
            "type": "plug",
            "payload": {"watt": 450.0},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["watt"] == 450.0


def test_accepts_valid_voice_command_event():
    event = validate_event(
        {
            "device_id": "d4",
            "type": "voice",
            "payload": {"command": "turn on lights"},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["command"] == "turn on lights"


def test_rejects_event_without_device_id():
    with pytest.raises(ValidationError):
        validate_event(
            {"type": "motion", "payload": {"detected": True}, "ts": make_ts()}
        )


def test_rejects_unknown_event_type():
    with pytest.raises(ValidationError):
        validate_event(
            {
                "device_id": "d1",
                "type": "unknown",
                "payload": {"detected": True},
                "ts": make_ts(),
            }
        )


def test_rejects_plug_wattage_above_device_rating():
    with pytest.raises(ValidationError):
        validate_event(
            {
                "device_id": "d3",
                "type": "plug",
                "payload": {"watt": 9999.0},
                "ts": make_ts(),
            }
        )


def test_rejects_temperature_above_sensor_range():
    with pytest.raises(ValidationError):
        validate_event(
            {
                "device_id": "d2",
                "type": "temp",
                "payload": {"celsius": 150.0, "humidity": 55.0},
                "ts": make_ts(),
            }
        )


def test_rejects_event_without_payload():
    with pytest.raises(ValidationError):
        validate_event({"device_id": "d1", "type": "motion", "ts": make_ts()})


def test_rejects_blank_device_id():
    with pytest.raises(ValidationError):
        validate_event(
            {
                "device_id": "",
                "type": "motion",
                "payload": {"detected": True},
                "ts": make_ts(),
            }
        )


def test_accepts_plug_wattage_at_max_device_rating():
    event = validate_event(
        {
            "device_id": "plug-boundary-001",
            "type": "plug",
            "payload": {"watt": 2400.0},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["watt"] == 2400.0


def test_rejects_negative_plug_wattage_from_meter_rollover_bug():
    with pytest.raises(ValidationError, match="watt"):
        validate_event(
            {
                "device_id": "plug-rollover-001",
                "type": "plug",
                "payload": {"watt": -0.01},
                "ts": make_ts(),
            }
        )


def test_accepts_timestamp_at_clock_skew_boundary():
    event = validate_event(
        {
            "device_id": "clock-boundary-001",
            "type": "motion",
            "payload": {"detected": False},
            "ts": make_ts(MAX_CLOCK_SKEW_SECONDS),
        }
    )
    assert event["device_id"] == "clock-boundary-001"


def test_rejects_timestamp_one_second_beyond_clock_skew_boundary():
    with pytest.raises(ValidationError, match="future"):
        validate_event(
            {
                "device_id": "clock-boundary-002",
                "type": "motion",
                "payload": {"detected": False},
                "ts": make_ts(MAX_CLOCK_SKEW_SECONDS + 2),
            }
        )
