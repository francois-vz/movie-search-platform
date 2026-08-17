"""Unit tests for Section 1.4 — embedding generation."""

from __future__ import annotations

import httpx
import pytest

from src.pipeline import embedding as embedding_module
from src.pipeline.config import PipelineSettings
from src.pipeline.embedding import (
    DOCUMENT_PREFIX,
    EmbeddingClient,
    EmbeddingCountError,
    EmbeddingDimensionError,
    embed_texts,
)

DIM = 4


def _settings(batch_size: int = 2) -> PipelineSettings:
    return PipelineSettings(
        DATABASE_URL="postgresql://u:p@localhost/db",
        EMBEDDING_BASE_URL="http://embeddings:11434",
        EMBEDDING_MODEL="nomic-embed-text",
        EMBEDDING_DIM=DIM,
        EMBEDDING_BATCH_SIZE=batch_size,
    )


def _client(handler, batch_size: int = 2) -> EmbeddingClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://embeddings:11434")
    return EmbeddingClient(_settings(batch_size), http_client=http)


def _vectors(count: int, dim: int = DIM) -> list[list[float]]:
    return [[float(index)] * dim for index in range(count)]


async def test_documents_are_sent_with_the_search_document_prefix() -> None:
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        seen.append(payload["input"])
        return httpx.Response(200, json={"embeddings": _vectors(len(payload["input"]))})

    client = _client(handler)
    await client.embed_batch(["Title: Heat", "Title: Alien"])

    assert seen == [[f"{DOCUMENT_PREFIX}Title: Heat", f"{DOCUMENT_PREFIX}Title: Alien"]]


async def test_prefix_is_not_applied_twice() -> None:
    seen: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        seen.append(payload["input"])
        return httpx.Response(200, json={"embeddings": _vectors(len(payload["input"]))})

    client = _client(handler)
    await client.embed_batch([f"{DOCUMENT_PREFIX}Title: Heat"])

    assert seen == [[f"{DOCUMENT_PREFIX}Title: Heat"]]


async def test_wrong_dimensionality_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    client = _client(handler)
    with pytest.raises(EmbeddingDimensionError):
        await client.embed_batch(["one"])


async def test_short_vector_count_is_rejected() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": _vectors(1)})

    client = _client(handler)
    with pytest.raises(EmbeddingCountError):
        await client.embed_batch(["one", "two"])


async def test_transient_failure_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding_module, "RETRY_MIN_SECONDS", 0.0)
    monkeypatch.setattr(embedding_module, "RETRY_MAX_SECONDS", 0.0)
    attempts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"embeddings": _vectors(1)})

    client = _client(handler)
    vectors = await client.embed_batch(["one"])

    assert attempts["count"] == 2
    assert len(vectors) == 1


async def test_falls_back_to_the_legacy_endpoint_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embedding_module, "RETRY_MIN_SECONDS", 0.0)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/embed":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"embedding": [0.0] * DIM})

    client = _client(handler)
    vectors = await client.embed_batch(["one", "two"])

    assert paths[0] == "/api/embed"
    assert paths[1:] == ["/api/embeddings", "/api/embeddings"]
    assert len(vectors) == 2


async def test_embed_texts_batches_by_configured_size() -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        batch_sizes.append(len(payload["input"]))
        return httpx.Response(200, json={"embeddings": _vectors(len(payload["input"]))})

    client = _client(handler, batch_size=2)
    vectors = await embed_texts(["a", "b", "c", "d", "e"], _settings(2), client=client)

    assert batch_sizes == [2, 2, 1]
    assert len(vectors) == 5


async def test_empty_batch_makes_no_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call expected for an empty batch")

    client = _client(handler)
    assert await client.embed_batch([]) == []
