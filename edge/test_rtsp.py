"""Quick RTSP connectivity check for the Tapo camera (Phase 1, step 1).

Set your camera details as environment variables (keeps credentials out of the
code and out of version control):

    export TAPO_HOST=192.168.x.x        # camera's LAN IP
    export TAPO_USER=your_camera_account
    export TAPO_PASS=your_camera_password
    # optional: export TAPO_STREAM=stream1   # stream1 = 1080p, stream2 = 360p

Then run:
    .venv-wsl/bin/python edge/test_rtsp.py

On success it grabs one frame, saves it to edge/rtsp_test.jpg, and prints the
resolution. That confirms the RTSP path works before we build the Edge Bridge.
"""
from __future__ import annotations

import os
import sys

import cv2


def build_url() -> str:
    url = os.environ.get("TAPO_RTSP_URL")
    if url:
        return url
    host = os.environ.get("TAPO_HOST")
    user = os.environ.get("TAPO_USER")
    password = os.environ.get("TAPO_PASS")
    stream = os.environ.get("TAPO_STREAM", "stream1")
    if not all([host, user, password]):
        sys.exit(
            "Set TAPO_HOST, TAPO_USER, TAPO_PASS (optional TAPO_STREAM), "
            "or TAPO_RTSP_URL directly."
        )
    return f"rtsp://{user}:{password}@{host}:554/{stream}"


def main() -> None:
    url = build_url()
    # Log without leaking credentials.
    shown = url.split("@")[-1] if "@" in url else url
    print(f"Connecting to rtsp://***@{shown} ...")

    # TCP transport is more reliable than UDP across WSL's NAT.
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        sys.exit(
            "Could not open the RTSP stream. Check: camera IP, the camera-account "
            "user/password, and that WSL can reach the camera's LAN IP "
            "(try: ping <TAPO_HOST>)."
        )

    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        sys.exit("Opened the stream but failed to read a frame (try TAPO_STREAM=stream2).")

    out = os.path.join(os.path.dirname(__file__), "rtsp_test.jpg")
    cv2.imwrite(out, frame)
    height, width = frame.shape[:2]
    print(f"OK - grabbed a {width}x{height} frame, saved to {out}")


if __name__ == "__main__":
    main()
