"""Unit tests for Section 1.5 — the pgvector loader.

These cover parameter binding and the upsert contract without a database. A
live idempotency check needs Postgres; see ``test_loader_integration.py``.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.pipeline.loader import (
    INSERT_COLUMNS,
    UPSERT_SQL,
    build_params,
    has_natural_key,
)

ROW = {
    "title": "Heat",
    "release_date": pd.Timestamp("1995-12-15"),
    "release_year": 1995,
    "major_genre": "Action",
    "mpaa_rating": "R",
    "director": "Michael Mann",
    "distributor": "Warner Bros.",
    "creative_type": "Contemporary Fiction",
    "source": "Original Screenplay",
    "imdb_rating": 8.3,
    "imdb_votes": 100_000,
    "rt_rating": 87,
    "production_budget": 60_000_000,
    "us_gross": 67_400_000,
    "worldwide_gross": 187_400_000,
    "running_time_min": 170,
    "budget_tier": "major",
    "decade": 1990,
    "rating_score_delta": -4.0,
    "blockbuster_flag": True,
    "imdb_rating_imputed": False,
    "rt_rating_imputed": False,
    "production_budget_imputed": False,
    "running_time_min_imputed": False,
    "augmented_text": "Title: Heat",
}


def _params(**overrides: object) -> tuple:
    row = pd.Series({**ROW, **overrides})
    return build_params(row, [0.1] * 4, "1.2.3")


def test_upsert_targets_the_v1_partial_unique_index() -> None:
    # Must match uq_movies_title_year in V1 exactly, or re-runs duplicate rows.
    assert "ON CONFLICT (lower(title), release_year)" in UPSERT_SQL
    assert "WHERE title IS NOT NULL AND release_year IS NOT NULL" in UPSERT_SQL
    assert "DO UPDATE SET" in UPSERT_SQL


def test_upsert_updates_every_column_except_the_key() -> None:
    for column in INSERT_COLUMNS:
        if column in {"title", "release_year"}:
            assert f"{column} = EXCLUDED.{column}" not in UPSERT_SQL
        else:
            assert f"{column} = EXCLUDED.{column}" in UPSERT_SQL


def test_updated_at_is_left_to_the_v1_trigger() -> None:
    assert "updated_at" not in UPSERT_SQL


def test_placeholder_count_matches_the_column_list() -> None:
    assert f"${len(INSERT_COLUMNS)}" in UPSERT_SQL
    assert f"${len(INSERT_COLUMNS) + 1}" not in UPSERT_SQL


def test_params_are_ordered_and_typed_for_postgres() -> None:
    params = _params()
    values = dict(zip(INSERT_COLUMNS, params, strict=True))

    assert len(params) == len(INSERT_COLUMNS)
    assert values["title"] == "Heat"
    assert values["release_date"] == dt.date(1995, 12, 15)
    assert isinstance(values["release_year"], int)
    assert isinstance(values["imdb_rating"], float)
    assert isinstance(values["rt_rating"], int)
    assert values["blockbuster_flag"] is True
    assert values["embedding"] == [0.1] * 4
    assert values["pipeline_version"] == "1.2.3"


def test_missing_cells_bind_as_none() -> None:
    values = dict(
        zip(
            INSERT_COLUMNS,
            _params(rt_rating=pd.NA, director=None, blockbuster_flag=pd.NA),
            strict=True,
        )
    )

    assert values["rt_rating"] is None
    assert values["director"] is None
    assert values["blockbuster_flag"] is None


def test_provenance_flags_are_carried_through() -> None:
    values = dict(
        zip(INSERT_COLUMNS, _params(running_time_min_imputed=True), strict=True)
    )
    assert values["running_time_min_imputed"] is True


@pytest.mark.parametrize(
    ("title", "year", "expected"),
    [
        ("Heat", 1995, True),
        (None, 1995, False),
        ("Heat", None, False),
        ("   ", 1995, False),
        (None, None, False),
    ],
)
def test_natural_key_detection(title: object, year: object, expected: bool) -> None:
    row = pd.Series({"title": title, "release_year": year})
    assert has_natural_key(row) is expected
