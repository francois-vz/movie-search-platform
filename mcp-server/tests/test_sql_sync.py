"""Contract: MCP SQL copy stays in lockstep with database/queries."""

from __future__ import annotations

from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT.parent
CANONICAL = REPO_ROOT / "database" / "queries" / "hybrid_search.sql"
COPY = MCP_ROOT / "src" / "server" / "sql" / "hybrid_search.sql"


def test_hybrid_sql_copy_matches_database() -> None:
    assert COPY.read_text(encoding="utf-8") == CANONICAL.read_text(encoding="utf-8")


def test_mcp_sql_files_exist() -> None:
    sql_dir = MCP_ROOT / "src" / "server" / "sql"
    for name in (
        "hybrid_search.sql",
        "title_exact.sql",
        "title_fuzzy.sql",
        "similar_movies.sql",
        "list_genres.sql",
        "dataset_stats.sql",
    ):
        path = sql_dir / name
        assert path.is_file(), path
        assert "SELECT" in path.read_text(encoding="utf-8")
