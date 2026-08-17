"""Contract checks for Part 2 schema + the documented hybrid-search query.

These do not hit Postgres. They freeze the SQL the MCP server / .NET API will
call, and the unique-key contract 1.1 cleaning already uses.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HYBRID_SQL = REPO_ROOT / "database" / "queries" / "hybrid_search.sql"
V1_SQL = REPO_ROOT / "database" / "migrations" / "V1__initial_schema.sql"
V2_SQL = REPO_ROOT / "database" / "migrations" / "V2__indexes.sql"


def test_hybrid_search_sql_is_vector_plus_metadata_filters() -> None:
    sql = HYBRID_SQL.read_text()

    assert "embedding <=> $1::vector" in sql
    assert "1 - (embedding <=> $1::vector) AS similarity" in sql
    assert "$2::text" in sql and "major_genre = $2" in sql
    assert "$3::int" in sql and "decade = $3" in sql
    assert "$4::numeric" in sql and "imdb_rating >= $4" in sql
    assert "$5::text" in sql and "mpaa_rating = $5" in sql
    assert "LIMIT $6" in sql
    assert "WHERE embedding IS NOT NULL" in sql
    # MovieResult columns (bind params $1–$6 stay fixed).
    select_sql = sql.split("FROM movies", 1)[0]
    for column in (
        "release_year",
        "mpaa_rating",
        "director",
        "distributor",
        "rt_rating",
    ):
        assert column in select_sql
    # match_type tells callers this score is cosine, not the trigram score
    # title_fuzzy.sql returns on the same field.
    assert "'semantic'::text AS match_type" in select_sql


def test_v1_unique_key_matches_cleaning_contract() -> None:
    sql = V1_SQL.read_text()

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in sql
    assert "embedding           vector(768)" in sql
    assert "uq_movies_title_year" in sql
    assert "ON movies (lower(title), release_year)" in sql
    assert "WHERE title IS NOT NULL AND release_year IS NOT NULL" in sql
    # Untitled 2006 row: title must be nullable (example schema had NOT NULL).
    assert "title               TEXT," in sql
    assert "title               TEXT NOT NULL" not in sql
    # us_dvd_sales is mentioned in a comment only — no column.
    data_lines = [ln.split("--", 1)[0] for ln in sql.splitlines()]
    assert not any("us_dvd_sales" in ln for ln in data_lines)
    assert "set_updated_at" in sql


def test_v2_has_hnsw_cosine_and_hybrid_filter_indexes() -> None:
    sql = V2_SQL.read_text()

    assert "USING hnsw (embedding vector_cosine_ops)" in sql
    assert "WHERE embedding IS NOT NULL" in sql
    assert "idx_movies_genre" in sql
    assert "idx_movies_decade" in sql
    assert "idx_movies_imdb" in sql
    assert "idx_movies_mpaa" in sql
    assert "USING gin (title gin_trgm_ops)" in sql
