import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "alerter"))
from rules import (  # noqa: E402
    ARRIVAL_GAP_SECONDS,
    NO_SIGHTING_ALERT_HOURS,
    evaluate,
    evaluate_feeding_drop,
    evaluate_night_intrusion,
    evaluate_no_sighting,
    format_alert_message,
    is_new_arrival,
)


# --- no_sighting ---


def test_no_sighting_fires_after_threshold():
    now = 1_000_000
    last = now - int(30 * 3600)  # 30h ago
    result = evaluate_no_sighting(now, last, threshold_hours=24)
    assert result is not None and result["rule"] == "no_sighting"


def test_no_sighting_quiet_within_threshold():
    now = 1_000_000
    last = now - int(2 * 3600)  # 2h ago
    assert evaluate_no_sighting(now, last, threshold_hours=24) is None


def test_no_sighting_none_when_never_seen():
    assert evaluate_no_sighting(1_000_000, None) is None


def test_no_sighting_uses_default_threshold():
    now = 1_000_000
    last = now - int((NO_SIGHTING_ALERT_HOURS + 1) * 3600)
    assert evaluate_no_sighting(now, last) is not None


# --- feeding_drop ---


def test_feeding_drop_fires_on_large_drop():
    result = evaluate_feeding_drop(today_grams=20.0, baseline_grams=100.0, drop_ratio=0.5)
    assert result is not None and result["rule"] == "feeding_drop"


def test_feeding_drop_quiet_on_normal_intake():
    assert evaluate_feeding_drop(today_grams=90.0, baseline_grams=100.0, drop_ratio=0.5) is None


def test_feeding_drop_ignores_tiny_noisy_baseline():
    assert evaluate_feeding_drop(today_grams=0.0, baseline_grams=5.0) is None


def test_feeding_drop_at_exact_threshold_is_quiet():
    # today == threshold (not strictly below) → no alert
    assert evaluate_feeding_drop(today_grams=50.0, baseline_grams=100.0, drop_ratio=0.5) is None


# --- night_intrusion ---


def test_night_intrusion_fires_on_spike():
    result = evaluate_night_intrusion(night_sighting_count=10, baseline_night_avg=2.0, multiplier=3.0)
    assert result is not None and result["rule"] == "night_intrusion"


def test_night_intrusion_quiet_when_near_baseline():
    assert evaluate_night_intrusion(night_sighting_count=4, baseline_night_avg=2.0, multiplier=3.0) is None


def test_night_intrusion_needs_minimum_count():
    assert evaluate_night_intrusion(night_sighting_count=2, baseline_night_avg=0.0) is None


def test_night_intrusion_fires_without_baseline_on_burst():
    result = evaluate_night_intrusion(night_sighting_count=5, baseline_night_avg=0.0)
    assert result is not None and result["rule"] == "night_intrusion"


# --- co-presence: Zeus in frame with another animal (per-event, stateless) ---


def test_co_presence_alert_when_others_present():
    result = evaluate("sighting", {"others_present": True, "animal_count": 2})
    assert result is not None and result["rule"] == "co_presence"
    assert "2 animals" in result["detail"]


def test_no_co_presence_alert_when_zeus_alone():
    assert evaluate("sighting", {"others_present": False, "animal_count": 1}) is None
    assert evaluate("sighting", {}) is None


def test_intrusion_event_alerts_as_solo_intruder():
    result = evaluate("intrusion", {"zone": "porch", "animal_count": 1})
    assert result is not None and result["rule"] == "intruder_solo"
    assert "Zeus not in frame" in result["detail"]
    assert "1 animals" in result["detail"]


# --- alert message formatting (for notifications) ---


def test_format_alert_message_co_presence_is_human_readable():
    msg = format_alert_message(
        {"rule": "co_presence", "detail": "2 animals"},
        device_id="tapo-cam-porch",
    )
    assert "Zeus" in msg
    assert "another animal" in msg
    assert "2 animals" in msg
    assert "tapo-cam-porch" in msg


def test_format_alert_message_no_sighting():
    msg = format_alert_message({"rule": "no_sighting", "detail": "not seen for 26.0h > 24.0h"})
    assert "been seen" in msg
    assert "26.0h" in msg


# --- arrival (new-visit) detection ---


def test_arrival_first_ever_sighting_is_new():
    assert is_new_arrival(None, 1_000_000) is True


def test_arrival_within_gap_is_not_new():
    now = 1_000_000
    prev = now - (ARRIVAL_GAP_SECONDS - 60)  # still the same visit
    assert is_new_arrival(prev, now) is False


def test_arrival_after_gap_is_new():
    now = 1_000_000
    prev = now - (ARRIVAL_GAP_SECONDS + 60)  # long enough gap = new visit
    assert is_new_arrival(prev, now) is True


def test_arrival_exactly_at_gap_is_not_new():
    now = 1_000_000
    assert is_new_arrival(now - ARRIVAL_GAP_SECONDS, now) is False


def test_format_alert_message_arrival():
    msg = format_alert_message({"rule": "arrival", "detail": "at porch"})
    assert "Zeus is here" in msg
    assert "porch" in msg


def test_format_alert_message_solo_intruder():
    msg = format_alert_message(
        {"rule": "intruder_solo", "detail": "Another animal at the door (1 animals)"}
    )
    assert "door" in msg


def test_format_alert_message_unknown_rule_falls_back():
    msg = format_alert_message({"rule": "weird_new_rule", "detail": "x"})
    assert "weird_new_rule" in msg


def test_format_alert_message_has_no_emoji():
    # user preference: no emoji in messages
    msg = format_alert_message({"rule": "co_presence", "detail": "2 animals"})
    assert all(ord(ch) < 0x2190 for ch in msg)

