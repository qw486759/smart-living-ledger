"""Enrichment Lambda (Phase 2): S3 candidate frame -> Bedrock vision -> event.

Triggered when a frame lands under `frames/` in the candidate-frames bucket.
Downloads the frame plus the Zeus reference photos (`refs/zeus/`), asks a Bedrock
vision model "is this Zeus? how many animals? any non-Zeus animal?" — model-
agnostic via the Converse API, switchable between Nova Lite and Claude Sonnet by
`BEDROCK_MODEL_ID` — and on a confident positive POSTs a `sighting` event to the
ingest API, which flows through the existing CDC -> projection -> dashboard
pipeline. See docs/adr/0005, 0008.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

import boto3

from recognition import (
    build_intrusion_event,
    build_sighting_event,
    parse_frame_key,
    parse_recognition,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
INGEST_URL = os.environ["INGEST_URL"].rstrip("/")
REFS_PREFIX = os.environ.get("REFS_PREFIX", "refs/zeus/")
# Empty-porch negative exemplars: teach the model what "no animal" looks like on
# this exact scene (fixed distractors like a static leaf pile) — see docs/adr/0005.
EMPTY_REFS_PREFIX = os.environ.get("EMPTY_REFS_PREFIX", "refs/empty/")
CONFIDENCE_MIN = float(os.environ.get("CONFIDENCE_MIN", "0.6"))

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")

_SYSTEM = (
    "You watch a fixed outdoor porch camera to spot a specific cat named Zeus. "
    "You are given reference photos of Zeus, then one candidate frame from that camera.\n"
    "The candidate frame is OFTEN EMPTY — just the porch: metal railings, a concrete "
    "floor, moving tree shadows, leaves, plants, and parked cars. Railings, shadows, "
    "dappled light, leaves and pavement are NEVER animals. If no animal is visible, "
    "return is_zeus=false and animal_count=0.\n"
    "Zeus is the cat that regularly visits this porch; the reference photos show him "
    "from several angles, including from behind and grooming. If you can see a cat "
    "whose size, build and coloring are consistent with Zeus, treat it as Zeus "
    "(is_zeus=true) — you do NOT need a perfect match, and partial, distant or rear "
    "views still count. Only report a non-Zeus animal (others_present=true, and count "
    "it) if you clearly see a cat or animal that does NOT match Zeus (clearly different "
    "color, size or markings).\n"
    "Report is_zeus, animal_count (real animals actually visible, 0 if none), "
    "others_present, and confidence in the is_zeus decision. Always answer with the "
    "record_recognition tool."
)

_TOOL = {
    "toolSpec": {
        "name": "record_recognition",
        "description": "Record the recognition result for the candidate frame.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "is_zeus": {"type": "boolean"},
                    "confidence": {"type": "number", "description": "0.0 to 1.0"},
                    "animal_count": {"type": "integer"},
                    "others_present": {
                        "type": "boolean",
                        "description": "a non-Zeus animal is in frame",
                    },
                },
                "required": ["is_zeus", "confidence", "animal_count", "others_present"],
            }
        },
    }
}


def _load_images(bucket: str, prefix: str) -> list[bytes]:
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    images = []
    for obj in resp.get("Contents", []):
        if obj["Key"].lower().endswith((".jpg", ".jpeg", ".png")):
            images.append(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
    return images


def _image_block(data: bytes) -> dict:
    return {"image": {"format": "jpeg", "source": {"bytes": data}}}


def _recognize(
    reference_images: list[bytes], empty_images: list[bytes], frame: bytes
) -> dict:
    content: list[dict] = []
    for i, img in enumerate(reference_images):
        content.append({"text": f"Reference photo {i + 1} of Zeus:"})
        content.append(_image_block(img))
    for img in empty_images:
        content.append(
            {
                "text": "Reference photo of the EMPTY porch (no animals present; the "
                "fixed pile of dead leaves by the right railing is not an animal):"
            }
        )
        content.append(_image_block(img))
    # Everything above (system prompt + reference images) is identical on every
    # call, so cache it: within the cache TTL, repeated recognitions only pay full
    # price for the changing candidate frame below, not the ~7 reference images.
    content.append({"cachePoint": {"type": "default"}})
    content.append({"text": "Candidate frame to classify:"})
    content.append(_image_block(frame))

    resp = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": _SYSTEM}],
        messages=[{"role": "user", "content": content}],
        toolConfig={
            "tools": [_TOOL],
            "toolChoice": {"tool": {"name": "record_recognition"}},
        },
    )
    return parse_recognition(resp)


def _post_event(event: dict) -> None:
    req = urllib.request.Request(
        f"{INGEST_URL}/events",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # urlopen raises HTTPError on >=400; treat any non-2xx as a failure too so a
    # partial/redirect response can't be mistaken for a stored event.
    with urllib.request.urlopen(req, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"ingest returned HTTP {response.status}")
        response.read()


def lambda_handler(event: dict, context) -> dict:
    processed = 0
    sightings = 0
    intrusions = 0

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        try:
            zone, ts = parse_frame_key(key)
        except ValueError:
            logger.info(json.dumps({"event": "skip_non_frame_key", "key": key}))
            continue

        # Isolate each frame: a failure here (e.g. ingest POST error) must not fail
        # the whole batch, or S3's async retry would re-run Bedrock on every frame
        # in it and re-pay for recognitions that already succeeded.
        try:
            frame = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            refs = _load_images(bucket, REFS_PREFIX)
            empties = _load_images(bucket, EMPTY_REFS_PREFIX)
            recognition = _recognize(refs, empties, frame)
            processed += 1
            logger.info(json.dumps({"event": "recognized", "key": key, **recognition}))

            # Gate 1 (here): the model isn't confident enough — drop regardless of
            # is_zeus. Gate 2 (build_sighting_event): only produce an event when
            # is_zeus is true. The two are independent, not a duplicate check.
            if float(recognition.get("confidence", 0.0)) < CONFIDENCE_MIN:
                continue
            # Zeus -> sighting; a confident non-Zeus animal -> intrusion (bully cat
            # at the door with Zeus away). Exactly one of these is non-None.
            posted = build_sighting_event(recognition, zone, ts) or build_intrusion_event(
                recognition, zone, ts
            )
            if posted:
                _post_event(posted)
                if posted["type"] == "sighting":
                    sightings += 1
                else:
                    intrusions += 1
                logger.info(
                    json.dumps(
                        {"event": "event_posted", "type": posted["type"], "key": key, "zone": zone}
                    )
                )
        except Exception:  # noqa: BLE001 - keep one bad frame from failing the batch
            logger.exception(json.dumps({"event": "frame_failed", "key": key}))
            continue

    return {"processed": processed, "sightings": sightings, "intrusions": intrusions}
