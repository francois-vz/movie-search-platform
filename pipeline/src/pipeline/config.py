"""Environment-based configuration for the data pipeline."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    """Runtime configuration, populated from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")

    embedding_base_url: str = Field(alias="EMBEDDING_BASE_URL")
    embedding_model: str = Field(alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")

    pipeline_version: str = Field(default="0.1.0", alias="PIPELINE_VERSION")
    log_level: str = Field(default="INFO", alias="PIPELINE_LOG_LEVEL")


def get_settings() -> PipelineSettings:
    """Return a validated settings instance."""
    return PipelineSettings()  # type: ignore[call-arg]
