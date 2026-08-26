#!/usr/bin/env bash
# Serve the Zeus dashboard locally so the browser can call the API.
# Serving over http://localhost (instead of opening the file directly with
# file://) avoids the browser's null-origin CORS restrictions.
#
# Usage:
#   ./run-dashboard.sh          # serves on :8000
#   ./run-dashboard.sh 8001     # serves on a different port
#
# Then open http://localhost:<port>/index.html (dashboard)
#          or http://localhost:<port>/checkin.html (manual check-in)

set -euo pipefail
PORT="${1:-8000}"
cd "$(dirname "$0")/dashboard"
echo "Serving dashboard at http://localhost:${PORT}/index.html"
echo "Manual check-in at    http://localhost:${PORT}/checkin.html"
echo "Ctrl+C to stop."
python3 -m http.server "$PORT"
