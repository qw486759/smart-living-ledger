import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "projection_consumer"))
from projection_logic import (  # noqa: E402
    entity_for,
    projection_update_params,
)


# --- device → entity mapping (ADR-0006) ---


def test_all_sensors_map_to_zeus():
    assert entity_for("tapo-cam-porch") == "zeus"
    assert entity_for("feeder-scale-01") == "zeus"
    assert entity_for("manual") == "zeus"


def test_unknown_device_falls_back_to_default_entity():
    assert entity_for("some-new-sensor") == "zeus"


# --- sighting → entity last-seen ---


def test_sighting_updates_entity_last_seen():
    msg = {
        "type": "sighting",
        "device_id": "tapo-cam-porch",
        "ts": 1000,
        "payload": {"zone": "porch", "confidence": 0.97, "source": "vision"},
    }
    params = projection_update_params(msg)
    assert params["Key"] == {"pk": "ENTITY#zeus", "device_id": "STATE"}
    assert "last_sighting_ts = :ts" in params["UpdateExpression"]
    assert params["ConditionExpression"] == (
        "attribute_not_exists(last_sighting_ts) OR last_sighting_ts < :ts"
    )
    assert params["ExpressionAttributeValues"][":ts"] == 1000
    assert params["ExpressionAttributeValues"][":zone"] == "porch"
    assert params["ExpressionAttributeValues"][":conf"] == Decimal("0.97")


# --- feeding → entity intake ---


def test_feeding_updates_entity_intake_and_is_decimal():
    msg = {
        "type": "feeding",
        "device_id": "feeder-scale-01",
        "ts": 2000,
        "payload": {"grams": 42.5},
    }
    params = projection_update_params(msg)
    assert params["Key"] == {"pk": "ENTITY#zeus", "device_id": "STATE"}
    assert "last_feeding_grams = :grams" in params["UpdateExpression"]
    assert params["ExpressionAttributeValues"][":grams"] == Decimal("42.5")


# --- multiple sensors fold into one entity item, independent timelines ---


def test_sighting_and_feeding_share_one_entity_item():
    s = projection_update_params(
        {
            "type": "sighting",
            "device_id": "tapo-cam-porch",
            "ts": 1,
            "payload": {"zone": "z", "confidence": 1.0, "source": "manual"},
        }
    )
    f = projection_update_params(
        {"type": "feeding", "device_id": "feeder-scale-01", "ts": 1, "payload": {"grams": 10.0}}
    )
    assert s["Key"] == f["Key"] == {"pk": "ENTITY#zeus", "device_id": "STATE"}


def test_independent_ts_versioning_per_timeline():
    s = projection_update_params(
        {
            "type": "sighting",
            "device_id": "manual",
            "ts": 5,
            "payload": {"zone": "z", "confidence": 1.0, "source": "manual"},
        }
    )
    f = projection_update_params(
        {"type": "feeding", "device_id": "feeder-scale-01", "ts": 5, "payload": {"grams": 10.0}}
    )
    assert "last_sighting_ts" in s["ConditionExpression"]
    assert "last_feeding_ts" in f["ConditionExpression"]


# --- legacy device types unchanged ---


def test_legacy_device_type_keeps_device_scoped_key():
    msg = {
        "type": "motion",
        "device_id": "motion-sensor-001",
        "ts": 100,
        "payload": {"detected": True},
    }
    params = projection_update_params(msg)
    assert params["Key"] == {"pk": "TYPE#motion", "device_id": "motion-sensor-001"}
    assert params["ConditionExpression"] == "attribute_not_exists(#ts) OR #ts < :ts"
