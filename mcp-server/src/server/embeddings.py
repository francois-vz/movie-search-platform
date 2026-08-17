"""Thin async client for the containerized Ollama embedding server."""

from __future__ import annotations

import httpx

from ..config import MCPSettings

QUERY_PREFIX = "search_query: "

_client: EmbeddingClient | None = None


class EmbeddingDimensionError(ValueError):
    """Raised when Ollama returns a vector whose length != EMBEDDING_DIM."""


class EmbeddingClient:
    """Single-query embedder. Documents use search_document: in pipeline 1.4."""

    def __init__(
        self,
        settings: MCPSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=settings.embedding_base_url,
            timeout=60.0,
        )

    def _prefixed(self, query: str) -> str:
        text = query.strip()
        if text.startswith(QUERY_PREFIX):
            return text
        return f"{QUERY_PREFIX}{text}"

    async def embed_query(self, query: str) -> list[float]:
        payload = {
            "model": self._settings.embedding_model,
            "input": self._prefixed(query),
        }
        response = await self._http.post("/api/embed", json=payload)
        response.raise_for_status()
        data = response.json()
        vector = _first_embedding(data)
        expected = self._settings.embedding_dim
        if len(vector) != expected:
            raise EmbeddingDimensionError(
                f"embedding length {len(vector)} != EMBEDDING_DIM {expected}"
            )
        return vector

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def _first_embedding(data: object) -> list[float]:
    if not isinstance(data, dict):
        raise TypeError("Ollama embed response is not a JSON object")
    embeddings = data.get("embeddings")
    if isinstance(embeddings, list) and embeddings:
        first = embeddings[0]
        if isinstance(first, list):
            return [float(x) for x in first]
    embedding = data.get("embedding")
    if isinstance(embedding, list):
        return [float(x) for x in embedding]
    raise ValueError("Ollama embed response is missing embeddings")


async def init_client(settings: MCPSettings) -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient(settings)
    return _client


def get_client() -> EmbeddingClient:
    if _client is None:
        raise RuntimeError("embedding client is not initialized")
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def embed_query(query: str) -> list[float]:
    return await get_client().embed_query(query)
