"""Environment-based configuration for the MCP server."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    embedding_base_url: str = Field(alias="EMBEDDING_BASE_URL")
    embedding_model: str = Field(alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")
    embedding_timeout_seconds: float = Field(
        default=60.0, alias="EMBEDDING_TIMEOUT_SECONDS"
    )

    host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    port: int = Field(default=8000, alias="MCP_PORT")
    transport: str = Field(default="sse", alias="MCP_TRANSPORT")
    log_level: str = Field(default="INFO", alias="MCP_LOG_LEVEL")
    pool_min_size: int = Field(default=2, alias="DB_POOL_MIN_SIZE")
    pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE")

    # Search policy. These are business rules, not structural constants, so they
    # belong in configuration rather than being baked into the tool code.
    top_k_max: int = Field(default=50, alias="MCP_TOP_K_MAX")
    # What "highly rated" / "critically acclaimed" means when a natural-language
    # query implies a rating floor but does not state one.
    high_imdb_threshold: float = Field(default=7.5, alias="HIGH_IMDB_THRESHOLD")


@lru_cache(maxsize=1)
def get_settings() -> MCPSettings:
    """Process-wide settings. Cached: tools read this on every call."""
    return MCPSettings()  # type: ignore[call-arg]
