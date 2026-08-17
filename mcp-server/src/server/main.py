"""MCP server entry point.

Wires config + DB pool + tools and serves over the configured transport (SSE
locally). Exposes GET /health and structured JSON logging with request tracing.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal, cast

import structlog
import uvicorn
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import MCPSettings, get_settings
from . import db
from .tools import mcp


class TraceIdMiddleware:
    """Bind W3C traceparent (or a generated id) into structlog contextvars.

    Written as raw ASGI rather than Starlette's ``BaseHTTPMiddleware``: the latter
    consumes the response through an anyio stream that asserts every message is an
    ``http.response.body``, which the SSE transport's long-lived streaming responses
    violate — every ``GET /sse`` raised ``AssertionError: Unexpected message`` and
    logged a traceback. Passing the scope straight through leaves streaming intact.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        trace_id = _trace_id_from_headers(Headers(scope=scope))
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            await self.app(scope, receive, send)
        finally:
            structlog.contextvars.unbind_contextvars("trace_id")


def _trace_id_from_headers(headers: Headers) -> str:
    traceparent = headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return traceparent
    request_id = headers.get("x-request-id")
    if request_id:
        return request_id
    return uuid.uuid4().hex


def configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Readiness: 200 after SELECT 1, otherwise 503."""
    try:
        await db.ping()
    except Exception:  # noqa: BLE001 — any pool/DB failure is unreadiness
        structlog.get_logger("mcp.health").exception("health_unavailable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return
    uvicorn.run(
        _http_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


_HTTP_TRANSPORTS = ("http", "streamable-http", "sse")


def _http_app(settings: MCPSettings) -> Starlette:
    transport = settings.transport
    if transport not in _HTTP_TRANSPORTS:
        raise ValueError(f"unsupported MCP_TRANSPORT {transport!r}")
    return mcp.http_app(
        transport=cast(Literal["http", "streamable-http", "sse"], transport),
        middleware=[Middleware(TraceIdMiddleware)],
    )


if __name__ == "__main__":
    main()
