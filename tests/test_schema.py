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


# --- Cat-welfare event types: sighting + feeding ---


def test_accepts_vision_confirmed_sighting_event():
    event = validate_event(
        {
            "device_id": "tapo-cam-porch",
            "type": "sighting",
            "payload": {"zone": "porch", "confidence": 0.97, "source": "vision"},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["confidence"] == 0.97


def test_accepts_manual_sighting_checkin_at_full_confidence():
    event = validate_event(
        {
            "device_id": "manual",
            "type": "sighting",
            "payload": {"zone": "backyard", "confidence": 1.0, "source": "manual"},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["source"] == "manual"


def test_rejects_sighting_confidence_above_one():
    with pytest.raises(ValidationError, match="confidence"):
        validate_event(
            {
                "device_id": "tapo-cam-porch",
                "type": "sighting",
                "payload": {"zone": "porch", "confidence": 1.4, "source": "vision"},
                "ts": make_ts(),
            }
        )


def test_rejects_sighting_without_zone():
    with pytest.raises(ValidationError, match="zone"):
        validate_event(
            {
                "device_id": "tapo-cam-porch",
                "type": "sighting",
                "payload": {"confidence": 0.9, "source": "vision"},
                "ts": make_ts(),
            }
        )


def test_accepts_feeding_event_with_duration():
    event = validate_event(
        {
            "device_id": "feeder-scale-01",
            "type": "feeding",
            "payload": {"grams": 42.5, "duration_s": 90},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["grams"] == 42.5


def test_accepts_feeding_event_without_optional_duration():
    event = validate_event(
        {
            "device_id": "feeder-scale-01",
            "type": "feeding",
            "payload": {"grams": 30.0},
            "ts": make_ts(),
        }
    )
    assert event["payload"]["grams"] == 30.0


def test_rejects_negative_feeding_grams():
    with pytest.raises(ValidationError, match="grams"):
        validate_event(
            {
                "device_id": "feeder-scale-01",
                "type": "feeding",
                "payload": {"grams": -5.0},
                "ts": make_ts(),
            }
        )


def test_rejects_feeding_grams_above_sane_max():
    with pytest.raises(ValidationError, match="grams"):
        validate_event(
            {
                "device_id": "feeder-scale-01",
                "type": "feeding",
                "payload": {"grams": 9999.0},
                "ts": make_ts(),
            }
        )


def test_accepts_sighting_with_co_presence_fields():
    event = validate_event(
        {
            "device_id": "tapo-cam-porch",
            "type": "sighting",
            "payload": {
                "zone": "porch",
                "confidence": 0.95,
                "source": "vision",
                "animal_count": 2,
                "others_present": True,
            },
            "ts": make_ts(),
        }
    )
    assert event["payload"]["others_present"] is True


def test_rejects_sighting_animal_count_below_one():
    with pytest.raises(ValidationError, match="animal_count"):
        validate_event(
            {
                "device_id": "tapo-cam-porch",
                "type": "sighting",
                "payload": {
                    "zone": "porch",
                    "confidence": 0.9,
                    "source": "vision",
                    "animal_count": 0,
                },
                "ts": make_ts(),
            }
        )


def test_rejects_sighting_others_present_non_bool():
    with pytest.raises(ValidationError, match="others_present"):
        validate_event(
            {
                "device_id": "tapo-cam-porch",
                "type": "sighting",
                "payload": {
                    "zone": "porch",
                    "confidence": 0.9,
                    "source": "vision",
                    "others_present": "yes",
                },
                "ts": make_ts(),
            }
        )


# --- intrusion (non-Zeus animal at the door, Zeus not in frame) ---


def test_accepts_intrusion_event():
    event = validate_event(
        {
            "device_id": "tapo-cam-porch",
            "type": "intrusion",
            "payload": {
                "zone": "porch",
                "confidence": 0.88,
                "source": "vision",
                "animal_count": 1,
            },
            "ts": make_ts(),
        }
    )
    assert event["type"] == "intrusion"


def test_rejects_intrusion_without_animal_count():
    with pytest.raises(ValidationError, match="animal_count"):
        validate_event(
            {
                "device_id": "tapo-cam-porch",
                "type": "intrusion",
                "payload": {"zone": "porch", "confidence": 0.9, "source": "vision"},
                "ts": make_ts(),
            }
        )
