"""MCP server entry point.

Wires config + DB pool + tools and serves over the configured transport (SSE
locally). Exposes GET /health and structured JSON logging with request tracing.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal, cast

import structlog
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import MCPSettings, get_settings
from . import db
from .tools import mcp


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Bind W3C traceparent (or a generated id) into structlog contextvars."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        trace_id = _trace_id_from_request(request)
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            return await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()


def _trace_id_from_request(request: Request) -> str:
    traceparent = request.headers.get("traceparent")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return traceparent
    request_id = request.headers.get("x-request-id")
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
