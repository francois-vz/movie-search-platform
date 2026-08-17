#!/usr/bin/env bash
# Build the data pipeline image and (optionally) run it.
#
#   ./build.sh            # build the pipeline image
#   ./build.sh --run      # build, then run Section 1.1 cleaning once
#
# 1.1 execution (no database / embeddings required):
#   docker compose run --rm --no-deps pipeline
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "No .env found — creating one from .env.example"
  cp .env.example .env
fi

echo ">> Building pipeline image..."
docker compose build pipeline

if [[ "${1:-}" == "--run" ]]; then
  echo ">> Running pipeline (Section 1.1 cleaning, --no-deps: no postgres/embeddings yet)..."
  docker compose run --rm --no-deps pipeline
else
  echo ">> Done. Run the 1.1 pipeline with:"
  echo "     docker compose run --rm --no-deps pipeline"
  echo "   (Use --no-deps until 1.4/1.5 need postgres + embeddings.)"
fi
