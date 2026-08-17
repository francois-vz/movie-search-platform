"""Shared test setup.

The tool layer reads MCPSettings on every call, so tests need the required
environment present and the settings cache cleared between tests that change it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.config import get_settings

REQUIRED_ENV = {
    "DATABASE_URL": "postgresql://movies:test@localhost:5432/movies",
    "EMBEDDING_BASE_URL": "http://embeddings:11434",
    "EMBEDDING_MODEL": "nomic-embed-text",
}


@pytest.fixture(autouse=True)
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
