"""Stage 1.5 — Loader.

Upserts cleaned + augmented + embedded rows into pgvector. Idempotent:
re-running must not create duplicates (upsert on a stable natural key).
"""

from __future__ import annotations

import pandas as pd

from .config import PipelineSettings


async def load(
    df: pd.DataFrame,
    embeddings: list[list[float]],
    settings: PipelineSettings,
) -> int:
    """Upsert rows into the movies table; return number of rows written.

    TODO:
      - open asyncpg pool
      - upsert on natural key (e.g. normalized title + release_year) ON CONFLICT
      - write embedding as vector, plus augmented_text, metadata, audit columns
      - stamp pipeline_version and updated_at
    """
    raise NotImplementedError
