"""Stage 1.4 — Embedding generation.

Calls the containerized embedding model over HTTP (no in-process model download).
Processes records in configurable batches, logs progress and failures.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from .config import PipelineSettings


class EmbeddingClient:
    """Thin async client for the containerized embedding server."""

    def __init__(self, settings: PipelineSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(base_url=settings.embedding_base_url, timeout=60.0)

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input.

        TODO (Ollama):
          - POST /api/embed  {"model": settings.embedding_model, "input": [...]}
            -> {"embeddings": [[...], ...]}  (batch form; falls back to /api/embeddings)
          - prefix stored docs with "search_document: " (query side uses "search_query: ")
          - retry with backoff (tenacity) on transient failures
          - assert each vector has length == settings.embedding_dim
        """
        raise NotImplementedError

    async def aclose(self) -> None:
        await self._client.aclose()


async def embed_texts(
    texts: Sequence[str], settings: PipelineSettings
) -> list[list[float]]:
    """Embed all texts in batches of settings.embedding_batch_size."""
    raise NotImplementedError
