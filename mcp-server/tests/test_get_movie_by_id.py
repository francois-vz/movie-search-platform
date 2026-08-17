"""get_movie_by_id — the tool GET /api/v1/movies/{id} depends on.

The .NET client calls the tool name `get_movie_by_id` with a `movie_id`
argument (McpMovieSearchClient.GetByIdAsync). These tests pin that contract.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.server.models import MovieResult
from src.server.tools import get_movie_by_id


def _movie(movie_id: str) -> MovieResult:
    return MovieResult(id=movie_id, title="Heat", match_type="lookup")


async def test_returns_movie_for_known_id(monkeypatch: pytest.MonkeyPatch) -> None:
    movie_id = uuid4()
    captured: dict[str, Any] = {}

    async def fake_lookup(parsed: UUID) -> MovieResult | None:
        captured["id"] = parsed
        return _movie(str(parsed))

    monkeypatch.setattr("src.server.db.get_movie_by_id", fake_lookup)
    result = await get_movie_by_id(str(movie_id))

    assert result is not None
    assert result.id == str(movie_id)
    assert result.match_type == "lookup"
    # The UUID must be parsed, not passed through as text.
    assert captured["id"] == movie_id


async def test_returns_none_for_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_lookup(_parsed: UUID) -> MovieResult | None:
        return None

    monkeypatch.setattr("src.server.db.get_movie_by_id", fake_lookup)
    assert await get_movie_by_id(str(uuid4())) is None


async def test_malformed_uuid_returns_none_without_touching_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_args: object, **_kwargs: object) -> MovieResult | None:
        raise AssertionError("db.get_movie_by_id should not be called")

    monkeypatch.setattr("src.server.db.get_movie_by_id", fail)
    assert await get_movie_by_id("not-a-uuid") is None


async def test_empty_id_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError):
        await get_movie_by_id("")
