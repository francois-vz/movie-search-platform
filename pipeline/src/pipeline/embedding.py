"""Stage 1.4 — Embedding generation.

Calls the containerized embedding model over HTTP (no in-process model
download). Processes records in configurable batches, logs progress and
failures.

Model: ``nomic-embed-text`` served by the Compose ``embeddings`` service
(Ollama), 768 dimensions — matching ``vector(768)`` in V1. Nomic is asymmetric
and expects a task prefix: stored documents use ``search_document: `` here,
while the MCP server prefixes queries with ``search_query: ``. Mixing the two up
silently degrades retrieval, so both sides assert their own prefix.

Every returned vector is length-checked against ``EMBEDDING_DIM``. A batch that
still fails after retries raises rather than yielding a short vector — a partial
load would leave the corpus quietly incomplete, which is harder to notice than
a failed run.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import PipelineSettings

logger = logging.getLogger("pipeline.embedding")

DOCUMENT_PREFIX = "search_document: "

BATCH_ENDPOINT = "/api/embed"
LEGACY_ENDPOINT = "/api/embeddings"

RETRY_ATTEMPTS = 4
RETRY_MIN_SECONDS = 1.0
RETRY_MAX_SECONDS = 10.0
REQUEST_TIMEOUT_SECONDS = 120.0

RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class EmbeddingDimensionError(ValueError):
    """Raised when the server returns a vector whose length != EMBEDDING_DIM."""


class EmbeddingCountError(ValueError):
    """Raised when the server returns a different number of vectors than inputs."""


def _prefixed(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith(DOCUMENT_PREFIX):
        return stripped
    return f"{DOCUMENT_PREFIX}{stripped}"


def _vectors_from_batch(data: object, expected: int) -> list[list[float]]:
    if not isinstance(data, dict):
        raise TypeError("embed response is not a JSON object")
    embeddings = data.get("embeddings")
    if embeddings is None:
        raise ValueError("embed response is missing 'embeddings'")
    if not isinstance(embeddings, list):
        raise TypeError("'embeddings' is not a list")
    vectors = [[float(x) for x in vector] for vector in embeddings]
    if len(vectors) != expected:
        raise EmbeddingCountError(f"got {len(vectors)} vectors for {expected} inputs")
    return vectors


def _vector_from_single(data: object) -> list[float]:
    if not isinstance(data, dict):
        raise TypeError("embed response is not a JSON object")
    embedding = data.get("embedding")
    if embedding is None:
        raise ValueError("embed response is missing 'embedding'")
    if not isinstance(embedding, list):
        raise TypeError("'embedding' is not a list")
    return [float(x) for x in embedding]


class EmbeddingClient:
    """Thin async client for the containerized embedding server."""

    def __init__(
        self,
        settings: PipelineSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=settings.embedding_base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._use_legacy = False

    def _check_dimensions(self, vectors: Sequence[Sequence[float]]) -> None:
        expected = self._settings.embedding_dim
        for index, vector in enumerate(vectors):
            if len(vector) != expected:
                raise EmbeddingDimensionError(
                    f"vector {index} has length {len(vector)}, expected {expected}"
                )

    async def _post_batch(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._client.post(
            BATCH_ENDPOINT,
            json={"model": self._settings.embedding_model, "input": list(texts)},
        )
        response.raise_for_status()
        return _vectors_from_batch(response.json(), len(texts))

    async def _post_legacy(self, texts: Sequence[str]) -> list[list[float]]:
        """One request per text, for servers without the batch endpoint."""
        vectors: list[list[float]] = []
        for text in texts:
            response = await self._client.post(
                LEGACY_ENDPOINT,
                json={"model": self._settings.embedding_model, "prompt": text},
            )
            response.raise_for_status()
            vectors.append(_vector_from_single(response.json()))
        return vectors

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input."""
        if not texts:
            return []

        prefixed = [_prefixed(text) for text in texts]
        vectors: list[list[float]] = []

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            wait=wait_exponential(min=RETRY_MIN_SECONDS, max=RETRY_MAX_SECONDS),
            retry=retry_if_exception_type(RETRYABLE),
            reraise=True,
        ):
            with attempt:
                if self._use_legacy:
                    vectors = await self._post_legacy(prefixed)
                else:
                    try:
                        vectors = await self._post_batch(prefixed)
                    except httpx.HTTPStatusError as error:
                        if error.response.status_code != httpx.codes.NOT_FOUND:
                            raise
                        logger.warning(
                            "%s returned 404; falling back to %s",
                            BATCH_ENDPOINT,
                            LEGACY_ENDPOINT,
                        )
                        self._use_legacy = True
                        vectors = await self._post_legacy(prefixed)

        self._check_dimensions(vectors)
        return vectors

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


async def embed_texts(
    texts: Sequence[str],
    settings: PipelineSettings,
    *,
    client: EmbeddingClient | None = None,
) -> list[list[float]]:
    """Embed all texts in batches of settings.embedding_batch_size."""
    embedder = client or EmbeddingClient(settings)
    owns_client = client is None
    batch_size = max(1, settings.embedding_batch_size)
    total = len(texts)
    vectors: list[list[float]] = []

    try:
        for start in range(0, total, batch_size):
            batch = texts[start : start + batch_size]
            try:
                vectors.extend(await embedder.embed_batch(batch))
            except Exception:
                logger.exception(
                    "Embedding failed for batch starting at row %d (size %d)",
                    start,
                    len(batch),
                )
                raise
            logger.info("Embedded %d/%d rows", len(vectors), total)
    finally:
        if owns_client:
            await embedder.aclose()

    return vectors
