"""Execute every SQL file against a real Postgres.

The other SQL tests match strings, which pins the contract but would happily
pass on a query Postgres cannot parse. This one runs them. It is skipped unless
a throwaway database is pointed at explicitly:

    MCP_TEST_DSN=postgresql://movies:...@localhost:5432/movies pytest

It applies V1/V2 (both are ``IF NOT EXISTS``), so a bare ``pgvector/pgvector``
image is enough, and it TRUNCATEs the movies table — never aim it at a database
you care about.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from src.server import db

DSN = os.environ.get("MCP_TEST_DSN")

pytestmark = pytest.mark.skipif(
    not DSN, reason="set MCP_TEST_DSN to run SQL execution tests"
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"
DIM = 768


def _vector(*direction: float) -> list[float]:
    """Build a DIM-length vector whose direction is set by the leading components.

    Fixtures must differ in *direction*, not magnitude: cosine ignores magnitude, so
    the constant vectors this file used to seed ([0.10] * DIM, [0.11] * DIM,
    [0.90] * DIM) were all collinear and tied at similarity 1.0. Ranking assertions
    then depended on the physical row order Postgres happened to return rather than
    on cosine, and flipped as soon as the rows were written in a different order.
    """
    return (list(direction) + [0.0] * DIM)[:DIM]


# Cosine similarity to QUERY_VECTOR: Heat 1.0, The Matrix ~0.894, Amelie 0.0.
QUERY_VECTOR = _vector(1.0, 0.0)

ROWS: tuple[dict[str, Any], ...] = (
    {
        "title": "Heat",
        "release_year": 1995,
        "decade": 1990,
        "major_genre": "Action",
        "mpaa_rating": "R",
        "imdb_rating": 8.3,
        "rt_rating": 87,
        "embedding": _vector(1.0, 0.0),
    },
    {
        "title": "The Matrix",
        "release_year": 1999,
        "decade": 1990,
        "major_genre": "Action",
        "mpaa_rating": "R",
        "imdb_rating": 8.7,
        "rt_rating": 88,
        "embedding": _vector(1.0, 0.5),
    },
    {
        "title": "Amelie",
        "release_year": 2001,
        "decade": 2000,
        "major_genre": "Romantic Comedy",
        "mpaa_rating": "R",
        "imdb_rating": 8.4,
        "rt_rating": 89,
        "embedding": _vector(0.0, 1.0),
    },
)

INSERT = """
INSERT INTO movies (
    title, release_year, decade, major_genre, mpaa_rating,
    imdb_rating, rt_rating, embedding, augmented_text
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
RETURNING id
"""


@pytest.fixture
async def seeded() -> AsyncIterator[dict[str, UUID]]:
    import asyncpg
    from pgvector.asyncpg import register_vector

    conn = await asyncpg.connect(str(DSN))
    await register_vector(conn)
    try:
        for migration in sorted(MIGRATIONS.glob("V*.sql")):
            await conn.execute(migration.read_text(encoding="utf-8"))
        await conn.execute("TRUNCATE movies")
        ids: dict[str, UUID] = {}
        for row in ROWS:
            ids[str(row["title"])] = await conn.fetchval(
                INSERT,
                row["title"],
                row["release_year"],
                row["decade"],
                row["major_genre"],
                row["mpaa_rating"],
                row["imdb_rating"],
                row["rt_rating"],
                row["embedding"],
                f"Title: {row['title']}",
            )
        yield ids
    finally:
        await conn.close()


@pytest.fixture
async def pool(seeded: dict[str, UUID]) -> AsyncIterator[dict[str, UUID]]:
    from src.config import MCPSettings

    settings = MCPSettings.model_construct(
        database_url=str(DSN),
        pool_min_size=1,
        pool_max_size=2,
    )
    await db.init_pool(settings)
    try:
        yield seeded
    finally:
        await db.close_pool()


async def test_hybrid_search_runs_and_ranks_by_cosine(pool: dict[str, UUID]) -> None:
    results = await db.hybrid_search(
        QUERY_VECTOR,
        genre_filter=None,
        decade=None,
        min_imdb_rating=None,
        mpaa_rating=None,
        top_k=10,
    )
    assert [m.title for m in results] == ["Heat", "The Matrix", "Amelie"]
    assert all(m.match_type == "semantic" for m in results)
    assert results[0].similarity is not None and results[0].similarity > 0.99


async def test_hybrid_search_applies_every_metadata_filter(pool: dict[str, UUID]) -> None:
    results = await db.hybrid_search(
        QUERY_VECTOR,
        genre_filter="Action",
        decade=1990,
        min_imdb_rating=8.5,
        mpaa_rating="R",
        top_k=10,
    )
    assert [m.title for m in results] == ["The Matrix"]


async def test_title_exact_then_fuzzy(pool: dict[str, UUID]) -> None:
    exact = await db.get_movie_by_title("heat")
    assert exact is not None
    assert exact.title == "Heat"
    assert exact.match_type == "exact"
    assert exact.similarity == 1.0

    fuzzy = await db.get_movie_by_title("The Matrx")
    assert fuzzy is not None
    assert fuzzy.title == "The Matrix"
    assert fuzzy.match_type == "fuzzy"

    assert await db.get_movie_by_title("zzzzzzzzzz") is None


async def test_get_movie_by_id(pool: dict[str, UUID]) -> None:
    movie = await db.get_movie_by_id(pool["Amelie"])
    assert movie is not None
    assert movie.title == "Amelie"
    assert movie.match_type == "lookup"
    assert movie.similarity is None

    assert await db.get_movie_by_id(UUID(int=0)) is None


async def test_similar_movies_excludes_the_source(pool: dict[str, UUID]) -> None:
    results = await db.similar_movies(pool["Heat"], top_k=10)
    titles = [m.title for m in results]
    assert "Heat" not in titles
    assert titles[0] == "The Matrix"
    assert all(m.match_type == "semantic" for m in results)


async def test_list_genres_and_dataset_stats(pool: dict[str, UUID]) -> None:
    assert await db.list_genres() == ["Action", "Romantic Comedy"]

    stats = await db.dataset_stats()
    assert stats.total_movies == 3
    assert stats.genres == 2
    assert stats.year_min == 1995
    assert stats.year_max == 2001
    assert stats.avg_imdb_rating is not None
