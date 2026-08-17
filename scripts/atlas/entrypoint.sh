#!/bin/sh
# Wait (optional) + export Parquet from pgvector, then serve Embedding Atlas.
set -eu

export ATLAS_WAIT="${ATLAS_WAIT:-1}"
export ATLAS_EXPORT_PATH="${ATLAS_EXPORT_PATH:-/data/movies.parquet}"

python /app/scripts/export_embeddings_atlas.py

exec embedding-atlas "$ATLAS_EXPORT_PATH" \
  --vector embedding \
  --text title \
  --host 0.0.0.0 \
  --port 7000 \
  --umap-metric cosine \
  --umap-random-state 42
