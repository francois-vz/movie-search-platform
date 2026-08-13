"""MCP tool implementations (Part 3.1).

Each tool is registered on the shared FastMCP instance and performs semantic
vector search (with optional metadata filters) against pgvector.
"""

from __future__ import annotations

from fastmcp import FastMCP

from .models import DatasetStats, MovieResult

mcp: FastMCP = FastMCP("movie-search")


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
    raise NotImplementedError


@mcp.tool()
async def get_movie_by_title(title: str) -> MovieResult | None:
    """Retrieve a specific movie by exact or fuzzy title match."""
    raise NotImplementedError


@mcp.tool()
async def get_similar_movies(movie_id: str, top_k: int = 5) -> list[MovieResult]:
    """Given a movie ID, return the most semantically similar movies."""
    raise NotImplementedError


@mcp.tool()
async def list_genres() -> list[str]:
    """Return all distinct genres available in the dataset."""
    raise NotImplementedError


@mcp.tool()
async def get_dataset_stats() -> DatasetStats:
    """Return summary statistics about the movie dataset."""
    raise NotImplementedError
