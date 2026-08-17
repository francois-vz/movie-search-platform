#!/usr/bin/env bash
# Build the data pipeline image and (optionally) run it.
#
#   ./build.sh            # build the pipeline image
#   ./build.sh --run      # build, then run Section 1 cleaning once
#
# The pipeline itself is executed via:  docker compose run --rm pipeline
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "No .env found — creating one from .env.example"
  cp .env.example .env
fi

echo ">> Building pipeline image..."
docker compose build pipeline

if [[ "${1:-}" == "--run" ]]; then
  echo ">> Running pipeline (Section 1 cleaning)..."
  docker compose run --rm pipeline
else
  echo ">> Done. Run the pipeline with:"
  echo "     docker compose run --rm pipeline"
fi
