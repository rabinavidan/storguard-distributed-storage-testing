#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
DEADLINE="${DEADLINE_SECONDS:-120}"
INTERVAL=3

start=$(date +%s)

echo "[storguard] Polling cluster health at $ENDPOINT/minio/health/cluster"

while true; do
  now=$(date +%s)
  elapsed=$(( now - start ))

  if (( elapsed >= DEADLINE )); then
    echo "[storguard] ERROR: cluster not healthy after ${DEADLINE}s"
    docker ps --filter "name=storguard" --format "table {{.Names}}\t{{.Status}}"
    exit 1
  fi

  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    "${ENDPOINT}/minio/health/cluster" 2>/dev/null || echo "000")

  if [[ "$http_code" == "200" ]]; then
    echo "[storguard] Cluster healthy after ${elapsed}s"
    exit 0
  fi

  echo "[storguard] [${elapsed}s/${DEADLINE}s] status=$http_code — retrying in ${INTERVAL}s..."
  sleep "$INTERVAL"
done
