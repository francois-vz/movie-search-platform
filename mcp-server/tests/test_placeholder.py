"""Placeholder tests for the MCP server.

TODO: test each tool against a seeded pgvector test container, plus /health.
"""


def test_models_importable() -> None:
    from src.server.models import DatasetStats, MovieResult  # noqa: F401
