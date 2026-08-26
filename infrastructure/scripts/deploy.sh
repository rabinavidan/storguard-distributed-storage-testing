#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(dirname "$SCRIPT_DIR")"
PROFILE="${1:-storage}"

echo "[storguard] Starting profile: $PROFILE"
cd "$COMPOSE_DIR"

docker compose --profile "$PROFILE" up -d

echo "[storguard] Waiting for cluster health..."
"$SCRIPT_DIR/wait-for-health.sh"

echo "[storguard] Cluster is ready."
echo "  S3 API     : http://localhost:9000"
echo "  Console    : http://localhost:9090"
if [[ "$PROFILE" == "ci" || "$PROFILE" == "all" ]]; then
  echo "  Jenkins    : http://localhost:8080"
  echo "  Allure UI  : http://localhost:5252"
fi
