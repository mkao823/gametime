#!/usr/bin/env bash
# Start the predictions API via docker compose and wait for /health.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Building api image (if needed)..."
docker compose build api

echo "Starting api service..."
docker compose up -d api

echo "Waiting for http://127.0.0.1:8000/health ..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "API is healthy."
    curl -s http://127.0.0.1:8000/health | python3 -m json.tool
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for API health check." >&2
docker compose logs api --tail 50
exit 1
