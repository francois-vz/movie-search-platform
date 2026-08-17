"""Static contract between the SQL files and row_to_movie.

`row_to_movie` indexes every column by name, so a query that forgets one fails
at runtime with a KeyError on the first result — in production, not in CI.
These checks need no database. `test_sql_execution.py` covers what only a real
Postgres can: that the SQL is actually valid.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.server.db import MOVIE_COLUMNS

SQL_DIR = Path(__file__).resolve().parents[1] / "src" / "server" / "sql"

# Row-returning queries mapped through row_to_movie, and the match_type each
# must declare so callers can interpret `similarity`.
MOVIE_QUERIES: tuple[tuple[str, str], ...] = (
    ("hybrid_search.sql", "semantic"),
    ("similar_movies.sql", "semantic"),
    ("title_exact.sql", "exact"),
    ("title_fuzzy.sql", "fuzzy"),
    ("movie_by_id.sql", "lookup"),
)


def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _projection(sql: str) -> str:
    """The outermost SELECT list — the last SELECT before its FROM."""
    body = _strip_comments(sql)
    start = body.upper().rindex("SELECT")
    end = body.upper().index("FROM", start)
    return body[start + len("SELECT") : end]


@pytest.mark.parametrize(("filename", "_match_type"), MOVIE_QUERIES)
def test_query_projects_every_column_row_to_movie_reads(
    filename: str, _match_type: str
) -> None:
    projection = _projection((SQL_DIR / filename).read_text(encoding="utf-8"))
    for column in MOVIE_COLUMNS:
        assert re.search(rf"\b{column}\b", projection), f"{filename} omits {column}"


@pytest.mark.parametrize(("filename", "match_type"), MOVIE_QUERIES)
def test_query_declares_its_match_type(filename: str, match_type: str) -> None:
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    assert f"'{match_type}'::text AS match_type" in sql


def test_match_types_are_all_known_to_the_model() -> None:
    from typing import get_args

    from src.server.models import MatchType

    allowed = set(get_args(MatchType))
    assert {match_type for _name, match_type in MOVIE_QUERIES} <= allowed


def test_exact_title_match_scores_one_not_null() -> None:
    """A perfect title hit should rank above a fuzzy one, not below it."""
    sql = (SQL_DIR / "title_exact.sql").read_text(encoding="utf-8")
    assert "1.0::double precision AS similarity" in sql


def test_lookup_by_id_has_no_similarity_score() -> None:
    sql = (SQL_DIR / "movie_by_id.sql").read_text(encoding="utf-8")
    assert "NULL::double precision AS similarity" in sql
