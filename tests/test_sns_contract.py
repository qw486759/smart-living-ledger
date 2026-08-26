"""Pin the SNS event-stored message contract, the same way the HTTP
{error, code} contract is pinned. Downstream consumers (projection writer,
alerter) depend on this shape; changing it requires a schema_version bump."""
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from stream_consumer import stream_logic as logic  # noqa: E402


def test_event_stored_message_shape_is_stable():
    item = {
        "device_id": "temp-sensor-001",
        "type": "temp",
        "ts": 1778040094,
        "payload": {"celsius": 22.5, "humidity": 50},
        "expire_at": 1780632094,
    }

    message = logic.build_event_stored_message(item)

    assert set(message) == {
        "schema_version",
        "event",
        "device_id",
        "type",
        "ts",
        "payload",
    }
    assert message["schema_version"] == "1"
    assert message["event"] == "event_stored"
    assert message["device_id"] == "temp-sensor-001"
    assert message["type"] == "temp"
    assert message["ts"] == 1778040094
    assert message["payload"] == {"celsius": 22.5, "humidity": 50}
    # Internal fields (like expire_at) must NOT leak into the contract.
    assert "expire_at" not in message
