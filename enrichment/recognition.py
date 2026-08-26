"""Pure logic for turning a vision recognition result into a platform event.

No AWS / Bedrock I/O here, so it unit-tests directly. The Enrichment Lambda calls
a Bedrock vision model that returns:

    {is_zeus: bool, confidence: float, animal_count: int, others_present: bool}

and this module decides what event (if any) that becomes. `others_present` /
`animal_count` ride along on the sighting payload so the alerter's co_presence
rule can fire (Zeus in frame with another animal — see docs/adr/0005, 0008).
"""
from __future__ import annotations

from typing import Any, Optional

# The camera device these frames come from (resolves to entity 'zeus' in the
# projection — see docs/adr/0006). Overridable per deployment.
DEVICE_ID = "tapo-cam-porch"


def build_sighting_event(
    recognition: dict,
    zone: str,
    ts: int,
    device_id: str = DEVICE_ID,
) -> Optional[dict]:
    """Return a `sighting` event dict if the frame is Zeus, else None."""
    if not recognition.get("is_zeus"):
        return None

    payload: dict[str, Any] = {
        "zone": zone,
        "source": "vision",
        "confidence": float(recognition.get("confidence", 0.0)),
    }
    if "animal_count" in recognition:
        payload["animal_count"] = int(recognition["animal_count"])
    if "others_present" in recognition:
        payload["others_present"] = bool(recognition["others_present"])

    return {
        "device_id": device_id,
        "type": "sighting",
        "payload": payload,
        "ts": int(ts),
    }


def build_intrusion_event(
    recognition: dict,
    zone: str,
    ts: int,
    device_id: str = DEVICE_ID,
) -> Optional[dict]:
    """Return an `intrusion` event if the frame shows a non-Zeus animal (and Zeus
    is not in it). Lets the door be watched for the bully cat even when Zeus is
    away — see docs/adr/0005."""
    if recognition.get("is_zeus"):
        return None
    count = recognition.get("animal_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return None

    return {
        "device_id": device_id,
        "type": "intrusion",
        "payload": {
            "zone": zone,
            "source": "vision",
            "confidence": float(recognition.get("confidence", 0.0)),
            "animal_count": int(count),
        },
        "ts": int(ts),
    }


def parse_frame_key(key: str) -> tuple[str, int]:
    """`frames/<zone>/<ts>.jpg` -> (zone, ts). Raises ValueError if the key isn't
    a real bridge frame (e.g. a test/one-shot upload), so the caller can skip it."""
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "frames" or not parts[2].endswith(".jpg"):
        raise ValueError(f"unexpected frame key: {key}")
    return parts[1], int(parts[2][:-4])


def parse_recognition(converse_response: dict) -> dict:
    """Pull the recognizer's structured output (the toolUse block's input) out of
    a Bedrock Converse response. Raises ValueError if no toolUse block is present."""
    content = (
        converse_response.get("output", {}).get("message", {}).get("content", [])
    )
    for block in content:
        if "toolUse" in block:
            return block["toolUse"].get("input", {})
    raise ValueError("no toolUse block in Converse response")

