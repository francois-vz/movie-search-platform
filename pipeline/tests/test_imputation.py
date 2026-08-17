"""Unit tests for Section 1.2 — imputation."""

from __future__ import annotations

import pandas as pd

from src.pipeline.imputation import (
    MIN_GROUP_SIZE,
    UNKNOWN,
    impute,
)


def _genre_rows(genre: str, ratings: list[float | None]) -> list[dict]:
    return [
        {
            "title": f"{genre} {index}",
            "release_year": 2000,
            "major_genre": genre,
            "imdb_rating": rating,
        }
        for index, rating in enumerate(ratings)
    ]


def test_numeric_gap_filled_with_group_median_and_flagged() -> None:
    # 10 observed Horror ratings (median 5.0) + 1 missing.
    rows = _genre_rows("Horror", [5.0] * MIN_GROUP_SIZE + [None])
    result, report = impute(pd.DataFrame(rows))

    assert result.iloc[-1]["imdb_rating"] == 5.0
    assert bool(result.iloc[-1]["imdb_rating_imputed"]) is True
    assert bool(result.iloc[0]["imdb_rating_imputed"]) is False
    assert report.imputed_counts["imdb_rating"] == 1
    assert report.group_median_fills["imdb_rating"] == 1
    assert report.global_median_fills["imdb_rating"] == 0


def test_small_group_falls_back_to_global_median() -> None:
    # Western has too few observations to trust; Drama supplies the global median.
    rows = _genre_rows("Drama", [8.0] * MIN_GROUP_SIZE)
    rows += [{"title": "Lonely Western", "release_year": 2000, "major_genre": "Western",
              "imdb_rating": None}]
    result, report = impute(pd.DataFrame(rows))

    assert result.iloc[-1]["imdb_rating"] == 8.0
    assert report.group_median_fills["imdb_rating"] == 0
    assert report.global_median_fills["imdb_rating"] == 1
    assert report.global_medians["imdb_rating"] == 8.0


def test_null_genre_rows_use_the_global_median() -> None:
    rows = _genre_rows("Comedy", [6.0] * MIN_GROUP_SIZE)
    rows += [{"title": "Ungenred", "release_year": 2000, "major_genre": None,
              "imdb_rating": None}]
    result, _report = impute(pd.DataFrame(rows))

    assert result.iloc[-1]["imdb_rating"] == 6.0
    assert pd.isna(result.iloc[-1]["major_genre"])


def test_observed_values_are_never_overwritten() -> None:
    rows = _genre_rows("Action", [4.0] * MIN_GROUP_SIZE)
    rows[0]["imdb_rating"] = 9.9
    result, _report = impute(pd.DataFrame(rows))

    assert result.iloc[0]["imdb_rating"] == 9.9
    assert bool(result.iloc[0]["imdb_rating_imputed"]) is False


def test_categoricals_get_unknown_sentinel_not_the_mode() -> None:
    df = pd.DataFrame(
        [
            {"title": "A", "release_year": 2000, "director": "Spielberg",
             "distributor": "Universal", "mpaa_rating": "PG"},
            {"title": "B", "release_year": 2001, "director": "Spielberg",
             "distributor": "Universal", "mpaa_rating": "PG"},
            {"title": "C", "release_year": 2002, "director": None,
             "distributor": None, "mpaa_rating": None},
        ]
    )
    result, report = impute(df)
    row = result.iloc[2]

    # The mode is "Spielberg"/"Universal"/"PG" — none of it may be borrowed.
    assert row["director"] == UNKNOWN
    assert row["distributor"] == UNKNOWN
    assert row["mpaa_rating"] == UNKNOWN
    assert report.imputed_counts["director"] == 1
    assert "never mode-imputed" in report.strategy_by_field["director"]


def test_major_genre_is_left_null_as_a_facet_field() -> None:
    df = pd.DataFrame(
        [
            {"title": "A", "release_year": 2000, "major_genre": "Drama"},
            {"title": "B", "release_year": 2001, "major_genre": None},
        ]
    )
    result, report = impute(df)

    assert pd.isna(result.iloc[1]["major_genre"])
    assert UNKNOWN not in set(result["major_genre"].dropna())
    assert report.imputed_counts["major_genre"] == 0
    assert "facet" in report.strategy_by_field["major_genre"]


def test_imputed_values_are_rounded_to_the_column_type() -> None:
    rows = [
        {"title": f"T{i}", "release_year": 2000, "major_genre": "Drama",
         "imdb_rating": rating, "rt_rating": rt, "running_time_min": runtime}
        for i, (rating, rt, runtime) in enumerate(
            [(7.1, 61, 101), (7.2, 62, 102), (7.3, 63, 103)] * 4
        )
    ]
    rows.append({"title": "Gap", "release_year": 2000, "major_genre": "Drama",
                 "imdb_rating": None, "rt_rating": None, "running_time_min": None})
    result, _report = impute(pd.DataFrame(rows))
    row = result.iloc[-1]

    assert row["imdb_rating"] == round(float(row["imdb_rating"]), 1)
    # Integer columns must arrive as Int64 so 1.5 binds ints, not floats.
    assert str(result["rt_rating"].dtype) == "Int64"
    assert str(result["running_time_min"].dtype) == "Int64"


def test_flag_columns_exist_even_when_nothing_is_missing() -> None:
    df = pd.DataFrame([{"title": "A", "release_year": 2000, "imdb_rating": 7.0}])
    result, _report = impute(df)

    for column in (
        "imdb_rating_imputed",
        "rt_rating_imputed",
        "production_budget_imputed",
        "running_time_min_imputed",
    ):
        assert column in result.columns
    assert bool(result.iloc[0]["imdb_rating_imputed"]) is False
