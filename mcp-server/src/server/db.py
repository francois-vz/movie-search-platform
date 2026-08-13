"""asyncpg connection pooling + query helpers for pgvector."""

from __future__ import annotations

import asyncpg

from ..config import MCPSettings

_pool: asyncpg.Pool | None = None


async def init_pool(settings: MCPSettings) -> asyncpg.Pool:
    """Create the shared connection pool (idempotent)."""
    raise NotImplementedError


async def get_pool() -> asyncpg.Pool:
    """Return the initialized pool or raise if not initialized."""
    raise NotImplementedError


async def close_pool() -> None:
    raise NotImplementedError
