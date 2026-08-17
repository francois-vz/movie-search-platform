"""Unit tests for Section 1.3 — feature augmentation."""

from __future__ import annotations

import pandas as pd

from src.pipeline.augmentation import (
    add_derived_features,
    augment,
    build_augmented_text,
)
from src.pipeline.imputation import UNKNOWN

# Every field observed, so the render must match the brief's template exactly.
FULL_ROW = {
    "title": "Titanic",
    "major_genre": "Drama",
    "director": "James Cameron",
    "mpaa_rating": "PG-13",
    "release_year": 1997,
    "running_time_min": 194,
    "imdb_rating": 7.4,
    "imdb_votes": 240732,
    "rt_rating": 82,
    "production_budget": 200_000_000,
    "distributor": "Paramount Pictures",
    "creative_type": "Historical Fiction",
    "source": "Original Screenplay",
}

EXPECTED_FULL_TEXT = """\
Title: Titanic
Genre: Drama
Director: James Cameron
MPAA Rating: PG-13
Release Year: 1997
Runtime: 194 minutes
IMDB Rating: 7.4/10 (240,732 votes)
Rotten Tomatoes: 82%
Budget: $200,000,000
Distributor: Paramount Pictures
Creative Type: Historical Fiction
Source: Original Screenplay"""


def test_fully_observed_row_matches_the_brief_template() -> None:
    assert build_augmented_text(pd.Series(FULL_ROW)) == EXPECTED_FULL_TEXT


def test_imputed_values_are_omitted_from_the_embedding_text() -> None:
    row = dict(FULL_ROW)
    row["running_time_min_imputed"] = True
    row["rt_rating_imputed"] = True
    text = build_augmented_text(pd.Series(row))

    assert "Runtime:" not in text
    assert "Rotten Tomatoes:" not in text
    # Observed neighbours survive.
    assert "Release Year: 1997" in text
    assert "IMDB Rating: 7.4/10" in text


def test_unknown_sentinel_is_omitted_rather_than_rendered() -> None:
    row = dict(FULL_ROW)
    row["director"] = UNKNOWN
    row["mpaa_rating"] = UNKNOWN
    text = build_augmented_text(pd.Series(row))

    assert UNKNOWN not in text
    assert "Director:" not in text
    assert "MPAA Rating:" not in text


def test_missing_values_are_omitted() -> None:
    row = dict(FULL_ROW)
    row["major_genre"] = None
    row["rt_rating"] = None
    text = build_augmented_text(pd.Series(row))

    assert "Genre:" not in text
    assert "Rotten Tomatoes:" not in text
    assert "nan" not in text.lower()


def test_votes_dropped_but_rating_kept_when_votes_missing() -> None:
    row = dict(FULL_ROW)
    row["imdb_votes"] = None
    text = build_augmented_text(pd.Series(row))

    assert "IMDB Rating: 7.4/10" in text
    assert "votes" not in text


def test_untitled_row_still_produces_usable_text() -> None:
    row = dict(FULL_ROW)
    row["title"] = None
    text = build_augmented_text(pd.Series(row))

    assert "Title:" not in text
    assert text.startswith("Genre: Drama")


def test_decade_derived_from_release_year() -> None:
    df = pd.DataFrame([{"release_year": 1997}, {"release_year": 2000}, {"release_year": None}])
    result = add_derived_features(df)

    assert result.iloc[0]["decade"] == 1990
    assert result.iloc[1]["decade"] == 2000
    assert pd.isna(result.iloc[2]["decade"])


def test_budget_tier_bands() -> None:
    df = pd.DataFrame(
        [
            {"production_budget": 500_000},
            {"production_budget": 30_000_000},
            {"production_budget": 75_000_000},
            {"production_budget": 200_000_000},
            {"production_budget": None},
        ]
    )
    tiers = add_derived_features(df)["budget_tier"].tolist()
    assert tiers[:4] == ["indie", "mid", "major", "blockbuster"]
    assert pd.isna(tiers[4])


def test_budget_tier_is_null_when_the_budget_was_imputed() -> None:
    df = pd.DataFrame([{"production_budget": 30_000_000, "production_budget_imputed": True}])
    assert pd.isna(add_derived_features(df).iloc[0]["budget_tier"])


def test_rating_score_delta_needs_both_ratings_observed() -> None:
    df = pd.DataFrame(
        [
            {"imdb_rating": 8.0, "rt_rating": 60},
            {"imdb_rating": 8.0, "rt_rating": 60, "rt_rating_imputed": True},
            {"imdb_rating": None, "rt_rating": 60},
        ]
    )
    deltas = add_derived_features(df)["rating_score_delta"].tolist()

    assert deltas[0] == 20.0
    assert pd.isna(deltas[1])
    assert pd.isna(deltas[2])


def test_blockbuster_flag_uses_both_gross_and_budget() -> None:
    df = pd.DataFrame(
        [
            # Cleared the floor and more than doubled its budget.
            {"worldwide_gross": 500_000_000, "production_budget": 100_000_000},
            # Huge gross but did not double a huge budget.
            {"worldwide_gross": 200_000_000, "production_budget": 250_000_000},
            # Doubled a small budget but never cleared the absolute floor.
            {"worldwide_gross": 20_000_000, "production_budget": 1_000_000},
            # Unknown gross means unknown outcome, not False.
            {"worldwide_gross": None, "production_budget": 50_000_000},
        ]
    )
    flags = add_derived_features(df)["blockbuster_flag"].tolist()

    assert flags[0] is True
    assert flags[1] is False
    assert flags[2] is False
    assert pd.isna(flags[3])


def test_augment_reports_coverage_and_adds_all_columns() -> None:
    df = pd.DataFrame([FULL_ROW, {**FULL_ROW, "title": "Other", "release_year": 2005}])
    result, report = augment(df)

    for column in ("decade", "budget_tier", "rating_score_delta", "blockbuster_flag",
                   "augmented_text"):
        assert column in result.columns
    assert report.derived_features == [
        "decade",
        "budget_tier",
        "rating_score_delta",
        "blockbuster_flag",
    ]
    assert report.augmented_text_rows == 2
    assert report.augmented_text_empty == 0
    assert report.feature_coverage["decade"] == 2
