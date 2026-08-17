"""MCP tool implementations (Part 3.1).

Each tool is registered on the shared FastMCP instance and performs semantic
vector search (with optional metadata filters) against pgvector.

Tools take flat, named parameters — the MCP convention, and what the .NET
client sends — but validate them through the Pydantic v2 models in
``models.py``. Signatures carry ``Field`` descriptions only, which is what
reaches the JSON schema an LLM caller reads.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastmcp import FastMCP
from pydantic import Field

from ..config import get_settings
from . import db, embeddings
from .filters import resolve_filters
from .models import (
    DEFAULT_SIMILAR_TOP_K,
    DEFAULT_TOP_K,
    DatasetStats,
    MovieIdInput,
    MovieResult,
    SearchMoviesInput,
    SimilarMoviesInput,
    TitleLookupInput,
    clamp_top_k,
)

log = structlog.get_logger("mcp.tools")


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


def _incoming_trace_id() -> str:
    """Correlation id for this tool call.

    Prefers the caller's W3C traceparent so MCP logs join up with .NET traces.
    Under SSE the tool body runs outside the POST that delivered it, so the
    HTTP-middleware binding is not always visible here — hence the direct read,
    with a generated id as the last resort so no tool log is ever uncorrelated.
    """
    try:
        from fastmcp.server.dependencies import get_http_headers

        headers = get_http_headers()
    except Exception:  # noqa: BLE001 — no HTTP context (stdio transport, tests)
        headers = {}

    traceparent = headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return traceparent
    request_id = headers.get("x-request-id")
    if request_id:
        return request_id
    return uuid.uuid4().hex


@asynccontextmanager
async def _tool_span(name: str) -> AsyncIterator[None]:
    """Time a tool call and emit one structured log line carrying trace_id."""
    bound = False
    if not structlog.contextvars.get_contextvars().get("trace_id"):
        structlog.contextvars.bind_contextvars(trace_id=_incoming_trace_id())
        bound = True
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
    finally:
        if bound:
            structlog.contextvars.unbind_contextvars("trace_id")


@mcp.tool()
async def search_movies_by_description(
    query: Annotated[str, Field(description="Natural language description of the movie.")],
    top_k: Annotated[int, Field(description="Maximum results; clamped to MCP_TOP_K_MAX.")] = (
        DEFAULT_TOP_K
    ),
    genre_filter: Annotated[str | None, Field(description="Exact major_genre match.")] = None,
    min_imdb_rating: Annotated[float | None, Field(description="Minimum IMDB rating.")] = None,
    mpaa_rating: Annotated[str | None, Field(description="Exact MPAA rating, e.g. PG-13.")] = None,
    decade: Annotated[int | None, Field(description="Decade start year, e.g. 1990.")] = None,
) -> list[MovieResult]:
    """Search movies using a natural language description.

    Performs semantic vector similarity search with optional metadata filters.
    Returns ranked results with similarity scores.
    """
    async with _tool_span("search_movies_by_description"):
        params = SearchMoviesInput(
            query=query,
            top_k=top_k,
            genre_filter=genre_filter,
            min_imdb_rating=min_imdb_rating,
            mpaa_rating=mpaa_rating,
            decade=decade,
        )
        settings = get_settings()
        filters = resolve_filters(
            params.query,
            genre_filter=params.genre_filter,
            decade=params.decade,
            min_imdb_rating=params.min_imdb_rating,
            mpaa_rating=params.mpaa_rating,
            high_imdb_threshold=settings.high_imdb_threshold,
        )
        vector = await embeddings.embed_query(params.query)
        return await db.hybrid_search(
            vector,
            genre_filter=filters.genre_filter,
            decade=filters.decade,
            min_imdb_rating=filters.min_imdb_rating,
            mpaa_rating=filters.mpaa_rating,
            top_k=clamp_top_k(params.top_k, settings.top_k_max),
        )


@mcp.tool()
async def get_movie_by_title(
    title: Annotated[str, Field(description="Movie title; exact match is tried first.")],
) -> MovieResult | None:
    """Retrieve a specific movie by exact or fuzzy title match."""
    async with _tool_span("get_movie_by_title"):
        params = TitleLookupInput(title=title)
        return await db.get_movie_by_title(params.title)


@mcp.tool()
async def get_movie_by_id(
    movie_id: Annotated[str, Field(description="Movie UUID, as returned by search results.")],
) -> MovieResult | None:
    """Retrieve a specific movie by its unique identifier.

    Returns null when the id is not a valid UUID or matches no movie.
    """
    async with _tool_span("get_movie_by_id"):
        params = MovieIdInput(movie_id=movie_id)
        try:
            parsed = UUID(params.movie_id)
        except ValueError:
            return None
        return await db.get_movie_by_id(parsed)


@mcp.tool()
async def get_similar_movies(
    movie_id: Annotated[str, Field(description="Movie UUID to find neighbours for.")],
    top_k: Annotated[int, Field(description="Maximum results; clamped to MCP_TOP_K_MAX.")] = (
        DEFAULT_SIMILAR_TOP_K
    ),
) -> list[MovieResult]:
    """Given a movie ID, return the most semantically similar movies."""
    async with _tool_span("get_similar_movies"):
        params = SimilarMoviesInput(movie_id=movie_id, top_k=top_k)
        try:
            parsed = UUID(params.movie_id)
        except ValueError:
            return []
        top_k_max = get_settings().top_k_max
        return await db.similar_movies(parsed, clamp_top_k(params.top_k, top_k_max))


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
