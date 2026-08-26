import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "enrichment"))
from recognition import (  # noqa: E402
    build_intrusion_event,
    build_sighting_event,
    parse_frame_key,
    parse_recognition,
)


def test_parse_frame_key_extracts_zone_and_ts():
    assert parse_frame_key("frames/porch/1787447094.jpg") == ("porch", 1787447094)


def test_parse_frame_key_rejects_non_frame_key():
    import pytest

    with pytest.raises(ValueError):
        parse_frame_key("frames/porch/oneshot-123.jpg")
    with pytest.raises(ValueError):
        parse_frame_key("refs/zeus/ref1.jpg")


def test_parse_recognition_extracts_tool_input():
    resp = {
        "output": {
            "message": {
                "content": [
                    {"text": "Here is my analysis"},
                    {"toolUse": {"name": "record_recognition", "input": {"is_zeus": True, "confidence": 0.9}}},
                ]
            }
        }
    }
    assert parse_recognition(resp) == {"is_zeus": True, "confidence": 0.9}


def test_parse_recognition_raises_without_tool_use():
    import pytest

    with pytest.raises(ValueError):
        parse_recognition({"output": {"message": {"content": [{"text": "no tool"}]}}})


def test_zeus_becomes_sighting_event():
    ev = build_sighting_event(
        {"is_zeus": True, "confidence": 0.96, "animal_count": 1, "others_present": False},
        "porch",
        1787445534,
    )
    assert ev["type"] == "sighting"
    assert ev["device_id"] == "tapo-cam-porch"
    assert ev["payload"]["zone"] == "porch"
    assert ev["payload"]["source"] == "vision"
    assert ev["payload"]["confidence"] == 0.96
    assert ev["payload"]["others_present"] is False
    assert ev["ts"] == 1787445534


def test_not_zeus_yields_no_event():
    assert build_sighting_event({"is_zeus": False, "confidence": 0.1}, "porch", 1) is None


def test_co_presence_fields_carried_through():
    ev = build_sighting_event(
        {"is_zeus": True, "confidence": 0.8, "animal_count": 2, "others_present": True},
        "porch",
        5,
    )
    assert ev["payload"]["animal_count"] == 2
    assert ev["payload"]["others_present"] is True


def test_confidence_coerced_to_float():
    ev = build_sighting_event({"is_zeus": True, "confidence": 1}, "backyard", 3)
    assert isinstance(ev["payload"]["confidence"], float)


def test_missing_optional_fields_omitted():
    ev = build_sighting_event({"is_zeus": True, "confidence": 0.9}, "porch", 2)
    assert "animal_count" not in ev["payload"]
    assert "others_present" not in ev["payload"]


# --- build_intrusion_event (non-Zeus animal, Zeus absent) ---


def test_non_zeus_animal_becomes_intrusion_event():
    ev = build_intrusion_event(
        {"is_zeus": False, "confidence": 0.85, "animal_count": 1}, "porch", 42
    )
    assert ev["type"] == "intrusion"
    assert ev["payload"]["animal_count"] == 1
    assert ev["payload"]["source"] == "vision"
    assert ev["ts"] == 42


def test_zeus_frame_yields_no_intrusion():
    assert (
        build_intrusion_event({"is_zeus": True, "confidence": 0.9, "animal_count": 1}, "porch", 1)
        is None
    )


def test_no_animal_yields_no_intrusion():
    assert build_intrusion_event({"is_zeus": False, "confidence": 0.9, "animal_count": 0}, "porch", 1) is None


def test_intrusion_confidence_coerced_to_float():
    ev = build_intrusion_event({"is_zeus": False, "confidence": 1, "animal_count": 2}, "porch", 5)
    assert ev["payload"]["confidence"] == 1.0
    assert isinstance(ev["payload"]["confidence"], float)
