"""Pydantic v2 models for MCP tool inputs and outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    similarity: float | None = Field(default=None, description="Cosine similarity score")


class DatasetStats(BaseModel):
    total_movies: int
    genres: int
    year_min: int | None = None
    year_max: int | None = None
    avg_imdb_rating: float | None = None
