"""Pydantic v2 models for MCP tool inputs and outputs.

Tool functions keep flat, named parameters — that is the MCP convention and it
is what the .NET client sends — but every tool validates its arguments through
one of the ``*Input`` models below. Constraints live here and nowhere else; the
signatures carry descriptions only, which is what ends up in the tool's
JSON schema for LLM callers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The brief fixes the default at 10 for description search; similarity search
# returns a tighter neighbourhood. The *maximum* is configurable
# (MCP_TOP_K_MAX) because it is a policy limit rather than a structural one.
DEFAULT_TOP_K = 10
DEFAULT_SIMILAR_TOP_K = 5
TOP_K_MIN = 1

# How a row's `similarity` score was produced. Without this the field is
# ambiguous: cosine similarity and trigram similarity share a [0, 1] range but
# are not comparable, and a direct lookup has no score at all.
MatchType = Literal["semantic", "exact", "fuzzy", "lookup"]


class MovieResult(BaseModel):
    id: str
    title: str
    release_year: int | None = None
    major_genre: str | None = None
    mpaa_rating: str | None = None
    director: str | None = None
    distributor: str | None = None
    imdb_rating: float | None = None
    rt_rating: int | None = None
    similarity: float | None = Field(
        default=None,
        description=(
            "Match score in [0, 1]. Interpretation depends on match_type: "
            "cosine similarity for 'semantic', trigram similarity for 'fuzzy', "
            "1.0 for 'exact', and null for 'lookup'."
        ),
    )
    match_type: MatchType | None = Field(
        default=None,
        description="How this row was matched, and therefore how to read similarity.",
    )


class DatasetStats(BaseModel):
    total_movies: int
    genres: int
    year_min: int | None = None
    year_max: int | None = None
    avg_imdb_rating: float | None = None


class SearchMoviesInput(BaseModel):
    """Validated arguments for search_movies_by_description."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    # Deliberately unbounded here: out-of-range values are clamped to
    # [TOP_K_MIN, settings.top_k_max] rather than rejected, so a caller asking
    # for 1,000 results gets the maximum instead of an error.
    top_k: int = DEFAULT_TOP_K
    genre_filter: str | None = None
    min_imdb_rating: float | None = Field(default=None, ge=0.0, le=10.0)
    mpaa_rating: str | None = None
    decade: int | None = Field(default=None, ge=1880, le=2100)


class TitleLookupInput(BaseModel):
    """Validated arguments for get_movie_by_title."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)


class MovieIdInput(BaseModel):
    """Validated arguments for get_movie_by_id."""

    model_config = ConfigDict(extra="forbid")

    movie_id: str = Field(min_length=1)


class SimilarMoviesInput(BaseModel):
    """Validated arguments for get_similar_movies."""

    model_config = ConfigDict(extra="forbid")

    movie_id: str = Field(min_length=1)
    top_k: int = DEFAULT_SIMILAR_TOP_K


def clamp_top_k(value: int, top_k_max: int) -> int:
    """Clamp a requested result count into [TOP_K_MIN, top_k_max]."""
    return max(TOP_K_MIN, min(value, top_k_max))
