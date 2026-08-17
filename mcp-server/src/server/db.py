"""asyncpg connection pooling + query helpers for pgvector."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import asyncpg
from pgvector.asyncpg import register_vector

from ..config import MCPSettings
from .models import DatasetStats, MovieResult

_SQL_DIR = Path(__file__).resolve().parent / "sql"

_pool: asyncpg.Pool | None = None


def _load_sql(name: str) -> str:
    return (_SQL_DIR / name).read_text(encoding="utf-8")


HYBRID_SEARCH_SQL = _load_sql("hybrid_search.sql")
TITLE_EXACT_SQL = _load_sql("title_exact.sql")
TITLE_FUZZY_SQL = _load_sql("title_fuzzy.sql")
MOVIE_BY_ID_SQL = _load_sql("movie_by_id.sql")
SIMILAR_MOVIES_SQL = _load_sql("similar_movies.sql")
LIST_GENRES_SQL = _load_sql("list_genres.sql")
DATASET_STATS_SQL = _load_sql("dataset_stats.sql")

# Every row-returning query must project exactly these, or row_to_movie breaks.
# tests/test_sql_contract.py asserts it without needing a database.
MOVIE_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "release_year",
    "major_genre",
    "mpaa_rating",
    "director",
    "distributor",
    "imdb_rating",
    "rt_rating",
    "similarity",
    "match_type",
)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    return float(cast(Any, value))


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    return int(cast(Any, value))


def row_to_movie(row: asyncpg.Record) -> MovieResult:
    """Map a movies row to MovieResult. Null title becomes ""."""
    movie_id = row["id"]
    if isinstance(movie_id, UUID):
        movie_id = str(movie_id)
    else:
        movie_id = str(movie_id)
    title = row["title"]
    return MovieResult(
        id=movie_id,
        title=title if isinstance(title, str) else "",
        release_year=_as_int(row["release_year"]),
        major_genre=row["major_genre"],
        mpaa_rating=row["mpaa_rating"],
        director=row["director"],
        distributor=row["distributor"],
        imdb_rating=_as_float(row["imdb_rating"]),
        rt_rating=_as_int(row["rt_rating"]),
        similarity=_as_float(row["similarity"]),
        match_type=row["match_type"],
    )


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)


async def init_pool(settings: MCPSettings) -> asyncpg.Pool:
    """Create the shared connection pool (idempotent)."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        init=_init_connection,
    )
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Return the initialized pool or raise if not initialized."""
    if _pool is None:
        raise RuntimeError("database pool is not initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping() -> None:
    """Readiness probe: one round-trip against the pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")


async def hybrid_search(
    embedding: Sequence[float],
    *,
    genre_filter: str | None,
    decade: int | None,
    min_imdb_rating: float | None,
    mpaa_rating: str | None,
    top_k: int,
) -> list[MovieResult]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            HYBRID_SEARCH_SQL,
            list(embedding),
            genre_filter,
            decade,
            min_imdb_rating,
            mpaa_rating,
            top_k,
        )
    return [row_to_movie(row) for row in rows]


async def get_movie_by_title(title: str) -> MovieResult | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(TITLE_EXACT_SQL, title)
        if row is None:
            row = await conn.fetchrow(TITLE_FUZZY_SQL, title)
    return row_to_movie(row) if row is not None else None


async def get_movie_by_id(movie_id: UUID) -> MovieResult | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(MOVIE_BY_ID_SQL, movie_id)
    return row_to_movie(row) if row is not None else None


async def similar_movies(movie_id: UUID, top_k: int) -> list[MovieResult]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SIMILAR_MOVIES_SQL, movie_id, top_k)
    return [row_to_movie(row) for row in rows]


async def list_genres() -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(LIST_GENRES_SQL)
    return [str(row["major_genre"]) for row in rows]


async def dataset_stats() -> DatasetStats:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(DATASET_STATS_SQL)
    if row is None:
        return DatasetStats(total_movies=0, genres=0)
    return DatasetStats(
        total_movies=int(row["total_movies"]),
        genres=int(row["genres"]),
        year_min=_as_int(row["year_min"]),
        year_max=_as_int(row["year_max"]),
        avg_imdb_rating=_as_float(row["avg_imdb_rating"]),
    )
