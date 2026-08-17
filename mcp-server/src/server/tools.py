"""MCP tool implementations (Part 3.1).

Each tool is registered on the shared FastMCP instance and performs semantic
vector search (with optional metadata filters) against pgvector.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import structlog
from fastmcp import FastMCP

from ..config import get_settings
from . import db, embeddings
from .filters import resolve_filters
from .models import DatasetStats, MovieResult

log = structlog.get_logger("mcp.tools")

TOP_K_MIN = 1
TOP_K_MAX = 50


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    await db.init_pool(settings)
    await embeddings.init_client(settings)
    try:
        yield {}
    finally:
        await embeddings.close_client()
        await db.close_pool()


mcp: FastMCP = FastMCP("movie-search", lifespan=_lifespan)


def _clamp_top_k(top_k: int) -> int:
    return max(TOP_K_MIN, min(top_k, TOP_K_MAX))


@asynccontextmanager
async def _tool_span(name: str) -> AsyncIterator[None]:
    start = time.perf_counter()
    try:
        yield
        log.info(
            "mcp_tool",
            tool=name,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            status="ok",
        )
    except Exception:
        log.exception(
            "mcp_tool",
            tool=name,
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            status="error",
        )
        raise


@mcp.tool()
async def search_movies_by_description(
    query: str,
    top_k: int = 10,
    genre_filter: str | None = None,
    min_imdb_rating: float | None = None,
    mpaa_rating: str | None = None,
    decade: int | None = None,
) -> list[MovieResult]:
    """Search movies using a natural language description.

    Performs semantic vector similarity search with optional metadata filters.
    Returns ranked results with similarity scores.
    """
    async with _tool_span("search_movies_by_description"):
        filters = resolve_filters(
            query,
            genre_filter=genre_filter,
            decade=decade,
            min_imdb_rating=min_imdb_rating,
            mpaa_rating=mpaa_rating,
        )
        vector = await embeddings.embed_query(query)
        return await db.hybrid_search(
            vector,
            genre_filter=filters.genre_filter,
            decade=filters.decade,
            min_imdb_rating=filters.min_imdb_rating,
            mpaa_rating=filters.mpaa_rating,
            top_k=_clamp_top_k(top_k),
        )


@mcp.tool()
async def get_movie_by_title(title: str) -> MovieResult | None:
    """Retrieve a specific movie by exact or fuzzy title match."""
    async with _tool_span("get_movie_by_title"):
        return await db.get_movie_by_title(title)


@mcp.tool()
async def get_similar_movies(movie_id: str, top_k: int = 5) -> list[MovieResult]:
    """Given a movie ID, return the most semantically similar movies."""
    async with _tool_span("get_similar_movies"):
        try:
            parsed = UUID(movie_id)
        except ValueError:
            return []
        return await db.similar_movies(parsed, _clamp_top_k(top_k))


@mcp.tool()
async def list_genres() -> list[str]:
    """Return all distinct genres available in the dataset."""
    async with _tool_span("list_genres"):
        return await db.list_genres()


@mcp.tool()
async def get_dataset_stats() -> DatasetStats:
    """Return summary statistics about the movie dataset."""
    async with _tool_span("get_dataset_stats"):
        return await db.dataset_stats()
