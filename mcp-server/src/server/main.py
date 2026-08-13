"""MCP server entry point.

Wires config + DB pool + tools and serves over the configured transport (SSE
locally). Exposes GET /health and structured JSON logging with request tracing.
"""

from __future__ import annotations

from ..config import get_settings
from .tools import mcp


def main() -> None:
    settings = get_settings()
    # TODO:
    #   - init asyncpg pool (db.init_pool) on startup, close on shutdown
    #   - mount GET /health
    #   - configure structlog JSON logging + trace propagation
    #   - run mcp with transport=settings.transport on settings.host:settings.port
    _ = settings
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
