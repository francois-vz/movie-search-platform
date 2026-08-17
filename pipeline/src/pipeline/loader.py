"""Stage 1.5 — Loader.

Upserts cleaned + imputed + augmented + embedded rows into pgvector.

**Idempotency** comes from the partial unique index V1 declares:
``(lower(title), release_year) WHERE title IS NOT NULL AND release_year IS NOT
NULL`` — the same natural key 1.1 de-duplicates on. Re-running the pipeline
updates rows in place and stamps ``updated_at`` via the V1 trigger; it never
inserts a second copy.

**Rows with no natural key are skipped and counted.** This closes the question
1.1 and Part 2 both left open. A NULL title cannot participate in the unique
index (Postgres does not collide NULLs), so such a row would be inserted afresh
on every run — directly violating the idempotency requirement. The alternative,
minting a synthetic title, was rejected: that string is not a title, and it
would be served to API clients through ``MovieResult.title`` as though it were
one. In the frozen Vega dataset this affects exactly one row of 3,201.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import asyncpg
import pandas as pd
from pgvector.asyncpg import register_vector

from .config import PipelineSettings

logger = logging.getLogger("pipeline.loader")

# Rows per executemany round-trip. Large enough to amortise latency, small
# enough to give useful progress logs on a ~3k-row corpus.
LOAD_CHUNK_SIZE = 500

# Column order for the upsert. Kept adjacent to the SQL so the two cannot drift.
INSERT_COLUMNS: tuple[str, ...] = (
    "title",
    "release_date",
    "release_year",
    "major_genre",
    "mpaa_rating",
    "director",
    "distributor",
    "creative_type",
    "source",
    "imdb_rating",
    "imdb_votes",
    "rt_rating",
    "production_budget",
    "us_gross",
    "worldwide_gross",
    "running_time_min",
    "budget_tier",
    "decade",
    "rating_score_delta",
    "blockbuster_flag",
    "imdb_rating_imputed",
    "rt_rating_imputed",
    "production_budget_imputed",
    "running_time_min_imputed",
    "augmented_text",
    "embedding",
    "pipeline_version",
)

TEXT_COLUMNS = frozenset(
    {
        "title",
        "major_genre",
        "mpaa_rating",
        "director",
        "distributor",
        "creative_type",
        "source",
        "budget_tier",
        "augmented_text",
        "pipeline_version",
    }
)
INT_COLUMNS = frozenset(
    {
        "release_year",
        "imdb_votes",
        "rt_rating",
        "production_budget",
        "us_gross",
        "worldwide_gross",
        "running_time_min",
        "decade",
    }
)
FLOAT_COLUMNS = frozenset({"imdb_rating", "rating_score_delta"})
BOOL_COLUMNS = frozenset(
    {
        "blockbuster_flag",
        "imdb_rating_imputed",
        "rt_rating_imputed",
        "production_budget_imputed",
        "running_time_min_imputed",
    }
)

# V1 declares the imputation flags NOT NULL DEFAULT FALSE. The DEFAULT only applies
# when a column is omitted from the INSERT, and this loader always binds all of them,
# so a missing or NA flag would bind an explicit NULL and the constraint would reject
# the whole batch. "Absent" means "this value was not imputed", so it maps to False.
NOT_NULL_BOOL_COLUMNS = frozenset(
    {
        "imdb_rating_imputed",
        "rt_rating_imputed",
        "production_budget_imputed",
        "running_time_min_imputed",
    }
)

# updated_at is intentionally absent from the SET list: the V1 trigger
# trg_movies_updated_at stamps it on every UPDATE.
_UPDATABLE = tuple(column for column in INSERT_COLUMNS if column not in {"title", "release_year"})

UPSERT_SQL = f"""
INSERT INTO movies ({", ".join(INSERT_COLUMNS)})
VALUES ({", ".join(f"${index}" for index in range(1, len(INSERT_COLUMNS) + 1))})
ON CONFLICT (lower(title), release_year)
    WHERE title IS NOT NULL AND release_year IS NOT NULL
DO UPDATE SET
    {", ".join(f"{column} = EXCLUDED.{column}" for column in _UPDATABLE)}
"""


@dataclass
class LoadReport:
    """Outcome of the upsert into pgvector."""

    rows_in: int = 0
    rows_written: int = 0
    rows_skipped_no_key: int = 0
    rows_skipped_no_embedding: int = 0
    skipped_examples: list[dict[str, str]] = field(default_factory=list)
    table_total_after: int = 0
    pipeline_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_na(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if not hasattr(result, "any") else False


def _coerce(column: str, value: Any) -> Any:
    """Map a pandas cell onto the Postgres type V1 declares for the column."""
    if _is_na(value):
        return False if column in NOT_NULL_BOOL_COLUMNS else None
    if column in TEXT_COLUMNS:
        return str(value)
    if column in INT_COLUMNS:
        return round(float(value))
    if column in FLOAT_COLUMNS:
        return float(value)
    if column in BOOL_COLUMNS:
        return bool(value)
    if column == "release_date":
        return pd.Timestamp(value).date()
    return value


def has_natural_key(row: pd.Series) -> bool:
    """True when the row can upsert on (lower(title), release_year)."""
    title = row.get("title")
    year = row.get("release_year")
    if _is_na(title) or _is_na(year):
        return False
    return str(title).strip() != ""


def build_params(
    row: pd.Series,
    embedding: list[float],
    pipeline_version: str,
) -> tuple[Any, ...]:
    """Bind one row to the UPSERT_SQL parameter list."""
    values: list[Any] = []
    for column in INSERT_COLUMNS:
        if column == "embedding":
            values.append(embedding)
        elif column == "pipeline_version":
            values.append(pipeline_version)
        else:
            values.append(_coerce(column, row.get(column)))
    return tuple(values)


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def load(
    df: pd.DataFrame,
    embeddings: list[list[float]],
    settings: PipelineSettings,
) -> LoadReport:
    """Upsert rows into the movies table; return a report of what was written."""
    if len(df) != len(embeddings):
        raise ValueError(f"{len(df)} rows but {len(embeddings)} embeddings")

    report = LoadReport(rows_in=len(df), pipeline_version=settings.pipeline_version)
    params: list[tuple[Any, ...]] = []

    for (_, row), embedding in zip(df.iterrows(), embeddings, strict=True):
        if not has_natural_key(row):
            report.rows_skipped_no_key += 1
            if len(report.skipped_examples) < 10:
                title = row.get("title")
                year: Any = row.get("release_year")
                report.skipped_examples.append(
                    {
                        "title": "" if _is_na(title) else str(title),
                        "release_year": "" if _is_na(year) else str(int(year)),
                        "reason": "no natural key (title/release_year)",
                    }
                )
            continue
        if not embedding:
            report.rows_skipped_no_embedding += 1
            continue
        params.append(build_params(row, embedding, settings.pipeline_version))

    if report.rows_skipped_no_key:
        logger.warning(
            "Skipping %d row(s) without a natural key; they cannot upsert idempotently",
            report.rows_skipped_no_key,
        )

    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=4,
        init=_init_connection,
    )
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for start in range(0, len(params), LOAD_CHUNK_SIZE):
                    chunk = params[start : start + LOAD_CHUNK_SIZE]
                    await conn.executemany(UPSERT_SQL, chunk)
                    report.rows_written += len(chunk)
                    logger.info("Upserted %d/%d rows", report.rows_written, len(params))
            report.table_total_after = int(await conn.fetchval("SELECT COUNT(*) FROM movies"))
    finally:
        await pool.close()

    return report
