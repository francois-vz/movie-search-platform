"""Cross-cutting tool contracts: input validation, config, and log correlation."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
import structlog
from pydantic import ValidationError

from src.config import get_settings
from src.server.models import (
    MovieResult,
    SearchMoviesInput,
    SimilarMoviesInput,
    clamp_top_k,
)
from src.server.tools import get_similar_movies, search_movies_by_description


@pytest.fixture
def stub_search(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture what the tool passes down to the embedding + db layers."""
    captured: dict[str, Any] = {}

    async def fake_embed(query: str) -> list[float]:
        captured["query"] = query
        return [0.0]

    async def fake_hybrid(_embedding: list[float], **kwargs: Any) -> list[MovieResult]:
        captured["kwargs"] = kwargs
        return []

    monkeypatch.setattr("src.server.embeddings.embed_query", fake_embed)
    monkeypatch.setattr("src.server.db.hybrid_search", fake_hybrid)
    return captured


# --- Pydantic input models -------------------------------------------------


def test_empty_query_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchMoviesInput(query="")


def test_out_of_range_rating_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchMoviesInput(query="drama", min_imdb_rating=11.0)


def test_implausible_decade_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchMoviesInput(query="drama", decade=1700)


def test_unknown_argument_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SearchMoviesInput(query="drama", genre="Action")  # type: ignore[call-arg]


def test_top_k_is_clamped_not_rejected() -> None:
    # A caller asking for 1,000 results should get the maximum, not an error.
    assert SimilarMoviesInput(movie_id="x", top_k=1000).top_k == 1000
    assert clamp_top_k(1000, 50) == 50
    assert clamp_top_k(0, 50) == 1
    assert clamp_top_k(7, 50) == 7


async def test_tool_rejects_empty_query(stub_search: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        await search_movies_by_description("")
    assert "kwargs" not in stub_search


# --- Configuration rather than hardcoded policy ----------------------------


async def test_top_k_max_comes_from_configuration(
    monkeypatch: pytest.MonkeyPatch, stub_search: dict[str, Any]
) -> None:
    monkeypatch.setenv("MCP_TOP_K_MAX", "3")
    get_settings.cache_clear()

    await search_movies_by_description("action movies", top_k=99)
    assert stub_search["kwargs"]["top_k"] == 3


async def test_high_imdb_threshold_comes_from_configuration(
    monkeypatch: pytest.MonkeyPatch, stub_search: dict[str, Any]
) -> None:
    monkeypatch.setenv("HIGH_IMDB_THRESHOLD", "9.1")
    get_settings.cache_clear()

    await search_movies_by_description("highly rated dramas")
    assert stub_search["kwargs"]["min_imdb_rating"] == 9.1


async def test_similar_movies_top_k_uses_configured_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_similar(_parsed: object, top_k: int) -> list[MovieResult]:
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr("src.server.db.similar_movies", fake_similar)
    monkeypatch.setenv("MCP_TOP_K_MAX", "2")
    get_settings.cache_clear()

    await get_similar_movies(str(uuid4()), top_k=40)
    assert captured["top_k"] == 2


# --- Log correlation -------------------------------------------------------


async def test_tool_logs_carry_a_trace_id(
    capsys: pytest.CaptureFixture[str], stub_search: dict[str, Any]
) -> None:
    """Every tool log line must be correlatable; §3 claims trace_id is emitted."""
    from src.server.main import configure_logging

    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()

    await search_movies_by_description("action movies")

    lines = [ln for ln in capsys.readouterr().out.splitlines() if "mcp_tool" in ln]
    assert lines, "expected an mcp_tool log line"
    payload = json.loads(lines[-1])
    assert payload["tool"] == "search_movies_by_description"
    assert payload["status"] == "ok"
    assert payload["trace_id"]


async def test_existing_trace_id_is_not_overwritten(
    capsys: pytest.CaptureFixture[str], stub_search: dict[str, Any]
) -> None:
    """An id bound by the HTTP middleware must survive into the tool log."""
    from src.server.main import configure_logging

    configure_logging("INFO")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(trace_id="abc123")
    try:
        await search_movies_by_description("action movies")
    finally:
        structlog.contextvars.clear_contextvars()

    lines = [ln for ln in capsys.readouterr().out.splitlines() if "mcp_tool" in ln]
    assert json.loads(lines[-1])["trace_id"] == "abc123"
