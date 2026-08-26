#!/usr/bin/env bash
# One-tap start for the Edge Bridge.
#
# Polls the Tapo camera, gates frames locally, and uploads candidate frames to
# S3 — which then auto-recognizes (is this Zeus?) and alerts in the cloud.
#
# Usage:
#   bash run-edge.sh          # start; Ctrl+C to stop (saves cost when Zeus isn't around)
#
# First time: copy edge/.env.example to edge/.env and fill in your camera URL.
set -euo pipefail
cd "$(dirname "$0")"

# Load camera URL + settings from edge/.env (gitignored; holds the camera password).
if [ -f edge/.env ]; then
  set -a; . edge/.env; set +a
fi

: "${TAPO_RTSP_URL:?Set TAPO_RTSP_URL in edge/.env (copy edge/.env.example first)}"
: "${EIP_FRAMES_BUCKET:?Set EIP_FRAMES_BUCKET in edge/.env}"

echo "──────────────────────────────────────────────"
echo " Edge bridge starting"
echo "   zone   : ${EIP_ZONE:-porch}"
echo "   poll   : ${EIP_POLL_SECONDS:-15}s"
echo "   bucket : $EIP_FRAMES_BUCKET"
echo " Ctrl+C to stop."
echo "──────────────────────────────────────────────"
.venv-wsl/bin/python edge/bridge.py
