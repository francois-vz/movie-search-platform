"""GET /health readiness: 200 after ping, 503 otherwise."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.requests import Request

from src.server.main import health


def _request() -> Request:
    return MagicMock(spec=Request)


@pytest.mark.asyncio
async def test_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ping() -> None:
        return None

    monkeypatch.setattr("src.server.db.ping", fake_ping)
    response = await health(_request())
    assert response.status_code == 200
    assert response.body == b'{"status":"ok"}'


@pytest.mark.asyncio
async def test_health_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ping() -> None:
        raise RuntimeError("database pool is not initialized")

    monkeypatch.setattr("src.server.db.ping", fake_ping)
    response = await health(_request())
    assert response.status_code == 503
    assert b"unavailable" in response.body
