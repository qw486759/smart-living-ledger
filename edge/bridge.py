"""Edge Bridge (Phase 1): poll the Tapo camera over RTSP, gate frames locally,
and upload only candidate frames to S3. Recognition ("is this Zeus?") happens in
the cloud (Phase 2). Secrets and endpoints come from env vars — nothing is
hard-coded.

Env:
    TAPO_RTSP_URL          full rtsp:// URL (or TAPO_HOST / TAPO_USER / TAPO_PASS / TAPO_STREAM)
    EIP_FRAMES_BUCKET      S3 bucket for candidate frames (deploy output CandidateFramesBucketName)
    EIP_ZONE               label for these frames (default 'porch')
    EIP_POLL_SECONDS       seconds between grabs (default 15) — how often we sample the stream
    EIP_HEARTBEAT_SECONDS  upload a frame at least this often even with no motion (default 60).
                           This is the real "periodic poll" safety net: a cat sitting still
                           produces almost no frame-diff, so motion-gating alone would miss it
                           (the exact blind spot Tapo's own motion detector has). The heartbeat
                           guarantees a stationary animal still reaches the cloud recognizer.
    EIP_MOTION_THRESHOLD   changed-pixel fraction to treat as a candidate (default 0.02)
    EIP_MAX_DIM            longest edge (px) to upload (default 1024; keeps cloud cost down)
    AWS creds via the standard chain (edge uploader key: AWS_ACCESS_KEY_ID / _SECRET / _DEFAULT_REGION)
"""
from __future__ import annotations

import logging
import os
import time

import boto3
import cv2

from detection import frame_key, is_candidate, motion_ratio, to_gray

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("edge-bridge")

BUFFER_DIR = os.path.join(os.path.dirname(__file__), "buffer")


def rtsp_url() -> str:
    url = os.environ.get("TAPO_RTSP_URL")
    if url:
        return url
    host = os.environ.get("TAPO_HOST")
    user = os.environ.get("TAPO_USER")
    password = os.environ.get("TAPO_PASS")
    stream = os.environ.get("TAPO_STREAM", "stream2")  # stream2 = lower-res, cheaper
    if not all([host, user, password]):
        raise SystemExit("Set TAPO_RTSP_URL, or TAPO_HOST / TAPO_USER / TAPO_PASS.")
    return f"rtsp://{user}:{password}@{host}:554/{stream}"


def resize_max(frame, max_dim: int):
    height, width = frame.shape[:2]
    scale = max_dim / max(height, width)
    if scale >= 1.0:
        return frame
    return cv2.resize(
        frame, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
    )


def encode_jpg(frame) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise RuntimeError("jpg encode failed")
    return buf.tobytes()


def _grab(url):
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            log.warning("could not open RTSP stream; will retry next poll")
            return None
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def _upload(s3, bucket, key, body) -> bool:
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="image/jpeg")
        return True
    except Exception as exc:  # noqa: BLE001 - buffer anything and retry later
        log.warning("upload failed for %s: %s", key, exc)
        return False


def _handle_candidate(s3, bucket, zone, frame, max_dim, reason):
    ts = int(time.time())
    key = frame_key(zone, ts)
    body = encode_jpg(resize_max(frame, max_dim))
    if _upload(s3, bucket, key, body):
        log.info("uploaded candidate %s (%s, %d bytes)", key, reason, len(body))
    else:
        os.makedirs(BUFFER_DIR, exist_ok=True)
        path = os.path.join(BUFFER_DIR, f"{zone}__{ts}.jpg")
        with open(path, "wb") as f:
            f.write(body)
        log.warning("buffered locally to %s (will retry when online)", path)


def _flush_buffer(s3, bucket):
    """Retry any frames that were buffered during an outage, oldest first."""
    if not os.path.isdir(BUFFER_DIR):
        return
    for name in sorted(os.listdir(BUFFER_DIR)):
        if not name.endswith(".jpg"):
            continue
        zone, sep, ts = name[:-4].partition("__")
        # Guard the round-trip of _handle_candidate's "<zone>__<ts>.jpg" naming: a
        # malformed name would build a bad S3 key that enrichment silently skips —
        # and we'd delete the local copy — so skip (don't delete) and flag it.
        if not sep or not ts.isdigit():
            log.warning("skipping malformed buffer file %s", name)
            continue
        path = os.path.join(BUFFER_DIR, name)
        with open(path, "rb") as f:
            body = f.read()
        if _upload(s3, bucket, frame_key(zone, ts), body):
            os.remove(path)
            log.info("flushed buffered frame %s", name)
        else:
            return  # still offline; keep the rest for later


def main() -> None:
    bucket = os.environ.get("EIP_FRAMES_BUCKET")
    if not bucket:
        raise SystemExit("Set EIP_FRAMES_BUCKET (deploy output CandidateFramesBucketName).")
    zone = os.environ.get("EIP_ZONE", "porch")
    poll = float(os.environ.get("EIP_POLL_SECONDS", "15"))
    heartbeat = float(os.environ.get("EIP_HEARTBEAT_SECONDS", "60"))
    threshold = float(os.environ.get("EIP_MOTION_THRESHOLD", "0.02"))
    max_dim = int(os.environ.get("EIP_MAX_DIM", "1024"))

    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    s3 = boto3.client("s3")
    url = rtsp_url()

    log.info(
        "edge bridge starting: zone=%s poll=%ss heartbeat=%ss threshold=%.3f bucket=%s",
        zone, poll, heartbeat, threshold, bucket,
    )
    prev_gray = None
    last_upload = 0.0
    while True:
        _flush_buffer(s3, bucket)
        frame = _grab(url)
        if frame is not None:
            gray = to_gray(frame)
            ratio = 0.0
            if prev_gray is not None and prev_gray.shape == gray.shape:
                ratio = motion_ratio(prev_gray, gray)
            prev_gray = gray

            now = time.monotonic()
            moved = is_candidate(ratio, threshold)
            due = (now - last_upload) >= heartbeat  # safety net for a still animal
            if moved or due:
                reason = f"motion={ratio:.3f}" if moved else "heartbeat"
                _handle_candidate(s3, bucket, zone, frame, max_dim, reason)
                last_upload = now
        time.sleep(poll)


if __name__ == "__main__":
    main()
