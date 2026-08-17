#!/bin/sh
# Wait (optional) + export Parquet from pgvector, then serve Embedding Atlas.
set -eu

export ATLAS_WAIT="${ATLAS_WAIT:-1}"
export ATLAS_EXPORT_PATH="${ATLAS_EXPORT_PATH:-/data/movies.parquet}"

# Column the embedding view colours by on load. The brief asks for Major Genre.
# Set to empty to serve stock Embedding Atlas, where colouring is a UI click.
export ATLAS_COLOR_BY="${ATLAS_COLOR_BY-major_genre}"

python /app/scripts/export_embeddings_atlas.py

set -- "$ATLAS_EXPORT_PATH" \
  --vector embedding \
  --text title \
  --host 0.0.0.0 \
  --port 7000 \
  --umap-metric cosine \
  --umap-random-state 42

if [ -n "$ATLAS_COLOR_BY" ]; then
  # atlas_color_by patches the CLI's prop builder in-process; see that module for
  # why there is no configuration hook for this. --with imports it before the
  # data is read.
  PYTHONPATH="/app/scripts/atlas${PYTHONPATH:+:${PYTHONPATH}}"
  export PYTHONPATH
  set -- "$@" --with atlas_color_by
fi

exec embedding-atlas "$@"
