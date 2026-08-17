"""Tool behaviour with mocked pool + embedding client."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.server.models import DatasetStats, MovieResult
from src.server.tools import (
    get_dataset_stats,
    get_movie_by_title,
    get_similar_movies,
    list_genres,
    search_movies_by_description,
)


def _movie(**overrides: Any) -> MovieResult:
    data: dict[str, Any] = {
        "id": str(uuid4()),
        "title": "Die Hard",
        "release_year": 1988,
        "major_genre": "Action",
        "similarity": 0.91,
    }
    data.update(overrides)
    return MovieResult.model_validate(data)


@pytest.mark.asyncio
async def test_search_extracts_filters_embeds_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_embed(query: str) -> list[float]:
        captured["query"] = query
        return [0.1, 0.2, 0.3]

    async def fake_hybrid(embedding: list[float], **kwargs: Any) -> list[MovieResult]:
        captured["embedding"] = embedding
        captured["kwargs"] = kwargs
        return [_movie()]

    monkeypatch.setattr("src.server.embeddings.embed_query", fake_embed)
    monkeypatch.setattr("src.server.db.hybrid_search", fake_hybrid)

    results = await search_movies_by_description(
        "action movies from the 90s with high IMDB ratings",
        top_k=100,
    )

    assert len(results) == 1
    assert captured["query"] == "action movies from the 90s with high IMDB ratings"
    assert captured["embedding"] == [0.1, 0.2, 0.3]
    assert captured["kwargs"]["genre_filter"] == "Action"
    assert captured["kwargs"]["decade"] == 1990
    assert captured["kwargs"]["min_imdb_rating"] == 7.5
    assert captured["kwargs"]["mpaa_rating"] is None
    assert captured["kwargs"]["top_k"] == 50


@pytest.mark.asyncio
async def test_search_explicit_filters_win(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_embed(_query: str) -> list[float]:
        return [0.0]

    async def fake_hybrid(_embedding: list[float], **kwargs: Any) -> list[MovieResult]:
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr("src.server.embeddings.embed_query", fake_embed)
    monkeypatch.setattr("src.server.db.hybrid_search", fake_hybrid)

    results = await search_movies_by_description(
        "action movies from the 90s with high IMDB ratings",
        genre_filter="Drama",
        decade=2000,
        min_imdb_rating=8.0,
        mpaa_rating="R",
        top_k=0,
    )

    assert results == []
    assert captured["kwargs"]["genre_filter"] == "Drama"
    assert captured["kwargs"]["decade"] == 2000
    assert captured["kwargs"]["min_imdb_rating"] == 8.0
    assert captured["kwargs"]["mpaa_rating"] == "R"
    assert captured["kwargs"]["top_k"] == 1


@pytest.mark.asyncio
async def test_get_movie_by_title_none_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_lookup(_title: str) -> MovieResult | None:
        return None

    monkeypatch.setattr("src.server.db.get_movie_by_title", fake_lookup)
    assert await get_movie_by_title("no such film") is None


@pytest.mark.asyncio
async def test_get_similar_movies_invalid_uuid_skips_db(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_similar(*_args: object, **_kwargs: object) -> list[MovieResult]:
        raise AssertionError("db.similar_movies should not be called")

    monkeypatch.setattr("src.server.db.similar_movies", fail_similar)
    assert await get_similar_movies("not-a-uuid") == []


@pytest.mark.asyncio
async def test_get_similar_movies_valid_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    movie_id = uuid4()
    captured: dict[str, Any] = {}

    async def fake_similar(parsed_id: object, top_k: int) -> list[MovieResult]:
        captured["id"] = parsed_id
        captured["top_k"] = top_k
        return [_movie(id=str(uuid4()), title="Predator")]

    monkeypatch.setattr("src.server.db.similar_movies", fake_similar)
    results = await get_similar_movies(str(movie_id), top_k=99)
    assert len(results) == 1
    assert captured["id"] == movie_id
    assert captured["top_k"] == 50


@pytest.mark.asyncio
async def test_list_genres_and_stats_empty_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_genres() -> list[str]:
        return []

    async def fake_stats() -> DatasetStats:
        return DatasetStats(total_movies=0, genres=0)

    monkeypatch.setattr("src.server.db.list_genres", fake_genres)
    monkeypatch.setattr("src.server.db.dataset_stats", fake_stats)

    assert await list_genres() == []
    stats = await get_dataset_stats()
    assert stats.total_movies == 0
    assert stats.genres == 0
    assert stats.avg_imdb_rating is None
