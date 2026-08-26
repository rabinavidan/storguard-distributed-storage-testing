#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(dirname "$SCRIPT_DIR")"
VOLUMES="${VOLUMES:-false}"

echo "[storguard] Stopping all containers..."
cd "$COMPOSE_DIR"
docker compose --profile storage --profile ci down

if [[ "$VOLUMES" == "true" ]]; then
  echo "[storguard] Removing volumes..."
  docker compose down -v
fi

echo "[storguard] Cluster destroyed."
