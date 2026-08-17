"""Live idempotency check for Section 1.5.

Idempotency is a graded requirement that cannot be proven without a database,
so this test runs only when a throwaway Postgres is pointed at explicitly:

    PIPELINE_TEST_DSN=postgresql://movies:...@localhost:5432/movies pytest

It applies V1/V2 (both are ``IF NOT EXISTS``), so a bare ``pgvector/pgvector``
container is enough. It TRUNCATEs the movies table — never aim it at a database
you care about.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline.config import PipelineSettings
from src.pipeline.loader import load

DSN = os.environ.get("PIPELINE_TEST_DSN")

pytestmark = pytest.mark.skipif(
    not DSN, reason="set PIPELINE_TEST_DSN to run loader integration tests"
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"

ROWS = [
    {
        "title": "Heat",
        "release_date": pd.Timestamp("1995-12-15"),
        "release_year": 1995,
        "major_genre": "Action",
        "imdb_rating": 8.3,
        "rt_rating": 87,
        "running_time_min": 170,
        "production_budget": 60_000_000,
        "decade": 1990,
        "budget_tier": "major",
        "blockbuster_flag": True,
        "augmented_text": "Title: Heat",
    },
    {
        # Remake-style row: same title, different year, must stay separate.
        "title": "The Mummy",
        "release_date": pd.Timestamp("1999-05-07"),
        "release_year": 1999,
        "major_genre": "Adventure",
        "augmented_text": "Title: The Mummy",
    },
    {
        "title": "The Mummy",
        "release_date": pd.Timestamp("2002-05-03"),
        "release_year": 2002,
        "major_genre": "Adventure",
        "augmented_text": "Title: The Mummy",
    },
    {
        # No natural key: must be skipped rather than duplicated on re-run.
        "title": None,
        "release_date": pd.Timestamp("2006-11-03"),
        "release_year": 2006,
        "major_genre": "Thriller/Suspense",
        "augmented_text": "Genre: Thriller/Suspense",
    },
]

DIM = 768


def _settings() -> PipelineSettings:
    return PipelineSettings(
        DATABASE_URL=str(DSN),
        EMBEDDING_BASE_URL="http://unused",
        EMBEDDING_MODEL="nomic-embed-text",
        EMBEDDING_DIM=DIM,
        PIPELINE_VERSION="test-1",
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(ROWS)


def _embeddings() -> list[list[float]]:
    return [[0.01 * (index + 1)] * DIM for index in range(len(ROWS))]


@pytest.fixture
async def clean_db():
    import asyncpg

    conn = await asyncpg.connect(str(DSN))
    try:
        for migration in sorted(MIGRATIONS.glob("V*.sql")):
            await conn.execute(migration.read_text(encoding="utf-8"))
        await conn.execute("TRUNCATE movies")
    finally:
        await conn.close()
    yield


async def test_load_writes_rows_and_skips_keyless(clean_db: None) -> None:
    report = await load(_frame(), _embeddings(), _settings())

    assert report.rows_in == 4
    assert report.rows_written == 3
    assert report.rows_skipped_no_key == 1
    assert report.table_total_after == 3


async def test_rerunning_does_not_duplicate(clean_db: None) -> None:
    import asyncpg

    first = await load(_frame(), _embeddings(), _settings())
    second = await load(_frame(), _embeddings(), _settings())

    assert first.table_total_after == second.table_total_after == 3

    conn = await asyncpg.connect(str(DSN))
    try:
        # Remakes survive; the natural key is (title, year), not title alone.
        mummies = await conn.fetchval(
            "SELECT COUNT(*) FROM movies WHERE lower(title) = 'the mummy'"
        )
        assert mummies == 2
        # The V1 trigger must have advanced updated_at on the second pass.
        stale = await conn.fetchval("SELECT COUNT(*) FROM movies WHERE updated_at < created_at")
        assert stale == 0
    finally:
        await conn.close()


async def test_rerun_updates_changed_values_in_place(clean_db: None) -> None:
    import asyncpg

    await load(_frame(), _embeddings(), _settings())

    changed = _frame()
    changed.loc[0, "imdb_rating"] = 9.1
    await load(changed, _embeddings(), _settings())

    conn = await asyncpg.connect(str(DSN))
    try:
        rating = await conn.fetchval("SELECT imdb_rating FROM movies WHERE title = 'Heat'")
        assert float(rating) == 9.1
    finally:
        await conn.close()


async def test_embeddings_are_stored_as_vectors(clean_db: None) -> None:
    import asyncpg
    from pgvector.asyncpg import register_vector

    await load(_frame(), _embeddings(), _settings())

    conn = await asyncpg.connect(str(DSN))
    try:
        await register_vector(conn)
        embedded = await conn.fetchval(
            "SELECT COUNT(*) FROM movies WHERE embedding IS NOT NULL"
        )
        assert embedded == 3
        # The HNSW cosine operator must work against what we wrote.
        nearest = await conn.fetchval(
            "SELECT title FROM movies WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> $1 LIMIT 1",
            [0.01] * DIM,
        )
        assert nearest is not None
    finally:
        await conn.close()
