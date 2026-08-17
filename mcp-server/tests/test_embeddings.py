"""Ollama EmbeddingClient: search_query: prefix and dimension assert."""

from __future__ import annotations

from typing import Any

import pytest

from src.config import MCPSettings
from src.server.embeddings import QUERY_PREFIX, EmbeddingClient, EmbeddingDimensionError


def _settings(dim: int = 4) -> MCPSettings:
    return MCPSettings.model_construct(
        database_url="postgresql://movies:x@postgres:5432/movies",
        embedding_base_url="http://embeddings:11434",
        embedding_model="nomic-embed-text",
        embedding_dim=dim,
    )


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self.calls.append((url, json))
        return _FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_embed_query_prefixes_and_returns_vector() -> None:
    http = _FakeHttp({"embeddings": [[0.1, 0.2, 0.3, 0.4]]})
    client = EmbeddingClient(_settings(), http_client=http)  # type: ignore[arg-type]
    vector = await client.embed_query("action movies from the 90s")
    assert vector == [0.1, 0.2, 0.3, 0.4]
    assert http.calls[0][0] == "/api/embed"
    assert http.calls[0][1]["input"] == f"{QUERY_PREFIX}action movies from the 90s"
    assert http.calls[0][1]["model"] == "nomic-embed-text"


@pytest.mark.asyncio
async def test_embed_query_does_not_double_prefix() -> None:
    http = _FakeHttp({"embeddings": [[1.0, 2.0, 3.0, 4.0]]})
    client = EmbeddingClient(_settings(), http_client=http)  # type: ignore[arg-type]
    await client.embed_query("search_query: already prefixed")
    assert http.calls[0][1]["input"] == "search_query: already prefixed"


@pytest.mark.asyncio
async def test_embed_query_rejects_wrong_dimension() -> None:
    http = _FakeHttp({"embeddings": [[0.1, 0.2]]})
    client = EmbeddingClient(_settings(dim=4), http_client=http)  # type: ignore[arg-type]
    with pytest.raises(EmbeddingDimensionError):
        await client.embed_query("foo")
