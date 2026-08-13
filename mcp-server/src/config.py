"""Environment-based configuration for the MCP server."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    embedding_base_url: str = Field(alias="EMBEDDING_BASE_URL")
    embedding_model: str = Field(alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")

    host: str = Field(default="0.0.0.0", alias="MCP_HOST")
    port: int = Field(default=8000, alias="MCP_PORT")
    transport: str = Field(default="sse", alias="MCP_TRANSPORT")
    log_level: str = Field(default="INFO", alias="MCP_LOG_LEVEL")
    pool_min_size: int = Field(default=2, alias="DB_POOL_MIN_SIZE")
    pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE")


def get_settings() -> MCPSettings:
    return MCPSettings()  # type: ignore[call-arg]
