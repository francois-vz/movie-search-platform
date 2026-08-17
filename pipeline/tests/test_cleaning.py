"""Unit tests for Section 1.1 — data cleaning."""

from __future__ import annotations

import pandas as pd

from src.pipeline.cleaning import (
    MAX_GENUINE_RELEASE_YEAR,
    CleaningReport,
    clean,
    remove_duplicates,
)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_exact_duplicate_removed_keeping_more_complete_row() -> None:
    df = _frame(
        [
            {"Title": "The Matrix", "Release Date": "Mar 31 1999", "Director": None, "IMDB Votes": 10},
            {"Title": "the matrix ", "Release Date": "Mar 31 1999", "Director": "Wachowski", "IMDB Votes": 500},
        ]
    )
    cleaned, report = clean(df)

    assert report.rows_in == 2
    assert report.duplicates_removed == 1
    assert report.rows_out == 1
    assert cleaned.iloc[0]["director"] == "Wachowski"
    assert cleaned.iloc[0]["title"] == "the matrix"


def test_same_title_different_years_are_not_duplicates() -> None:
    df = _frame(
        [
            {"Title": "The Mummy", "Release Date": "May 7 1999", "IMDB Votes": 100},
            {"Title": "The Mummy", "Release Date": "Jun 10 2002", "IMDB Votes": 200},
        ]
    )
    cleaned, report = clean(df)

    assert report.duplicates_removed == 0
    assert report.rows_out == 2
    years = set(cleaned["release_year"].astype(int))
    assert years == {1999, 2002}


def test_rows_missing_release_date_are_flagged_not_dropped() -> None:
    df = _frame(
        [
            {"Title": "Mystery Film", "Release Date": None, "IMDB Votes": 1},
            {"Title": "Mystery Film", "Release Date": "  ", "IMDB Votes": 2},
        ]
    )
    cleaned, report = clean(df)

    assert report.duplicates_removed == 0
    assert report.rows_missing_dedup_key == 2
    assert report.dates_unparseable == 0
    assert len(cleaned) == 2


def test_duplicate_examples_sample_is_populated() -> None:
    df = _frame(
        [
            {"Title": "Dup", "Release Date": "Jan 1 2000", "IMDB Votes": 5},
            {"Title": "Dup", "Release Date": "Jan 1 2000", "IMDB Votes": 5},
        ]
    )
    _cleaned, report = clean(df)

    assert report.duplicates_removed == 1
    assert report.duplicate_examples and report.duplicate_examples[0]["title"] == "Dup"
    assert report.duplicate_examples[0]["release_year"] == "2000"


def test_remove_duplicates_on_snake_case_year_key() -> None:
    df = _frame(
        [
            {"title": "Mystery Film", "release_year": pd.NA, "imdb_votes": 1},
            {"title": "Mystery Film", "release_year": pd.NA, "imdb_votes": 2},
        ]
    )
    report = CleaningReport()
    result = remove_duplicates(df, report)
    assert report.duplicates_removed == 0
    assert report.rows_missing_dedup_key == 2
    assert len(result) == 2


def test_underscored_vega_columns_are_renamed() -> None:
    df = _frame(
        [
            {
                "Title": "Heat",
                "Release_Date": "Dec 15 1995",
                "Major_Genre": "Action",
                "IMDB_Rating": 8.3,
                "IMDB_Votes": 100,
                "Rotten_Tomatoes_Rating": 87,
                "Production_Budget": 60_000_000,
            }
        ]
    )
    cleaned, report = clean(df)

    assert "release_date" in cleaned.columns
    assert "major_genre" in cleaned.columns
    assert "rt_rating" in cleaned.columns
    assert report.columns_renamed["Release_Date"] == "release_date"
    assert int(cleaned.iloc[0]["release_year"]) == 1995


def test_numeric_titles_are_stringified() -> None:
    df = _frame([{"Title": 300, "Release Date": "Mar 09 2007"}])
    cleaned, report = clean(df)

    assert report.titles_stringified == 1
    assert cleaned.iloc[0]["title"] == "300"
    assert isinstance(cleaned.iloc[0]["title"], str)


def test_whitespace_collapsed_and_sentinels_nulled() -> None:
    df = _frame(
        [
            {
                "Title": "Halloween:  The Curse of Michael Myers",
                "Release Date": "Sep 29 1995",
                "Director": "None",
                "Major Genre": "Horror",
                "MPAA Rating": "pg13",
                "Distributor": "  Dimension  ",
            }
        ]
    )
    cleaned, report = clean(df)
    row = cleaned.iloc[0]

    assert row["title"] == "Halloween: The Curse of Michael Myers"
    assert pd.isna(row["director"])
    assert row["mpaa_rating"] == "PG-13"
    assert row["distributor"] == "Dimension"
    assert report.sentinels_nulled.get("director") == 1
    assert report.strings_normalized["title"] >= 1
    assert report.strings_normalized["mpaa_rating"] >= 1


def test_century_correction_rewrites_encoded_classics() -> None:
    df = _frame(
        [
            {"Title": "Snow White and the Seven Dwarfs", "Release Date": "Dec 21 2037"},
            {"Title": "The Birth of a Nation", "Release Date": "Feb 08 2015"},
            {
                "Title": "The Adventures of Tintin: Secret of the Unicorn",
                "Release Date": "Dec 23 2011",
            },
        ]
    )
    cleaned, report = clean(df)
    by_title = cleaned.set_index("title")["release_year"].astype(int).to_dict()

    assert MAX_GENUINE_RELEASE_YEAR == 2011
    assert by_title["Snow White and the Seven Dwarfs"] == 1937
    assert by_title["The Birth of a Nation"] == 1915
    assert by_title["The Adventures of Tintin: Secret of the Unicorn"] == 2011
    assert report.dates_century_corrected == 2
    assert report.dates_parsed == 3
    assert report.dates_unparseable == 0


def test_unparseable_dates_are_nulled_not_dropped() -> None:
    df = _frame(
        [
            {"Title": "Bad Date", "Release Date": "not-a-date", "IMDB Votes": 3},
            {"Title": "Good Date", "Release Date": "Jun 12 1998", "IMDB Votes": 3},
        ]
    )
    cleaned, report = clean(df)

    assert report.dates_unparseable == 1
    assert report.dates_parsed == 1
    assert report.rows_out == 2
    bad = cleaned.set_index("title").loc["Bad Date"]
    assert pd.isna(bad["release_date"])
    assert pd.isna(bad["release_year"])
    assert report.rows_missing_dedup_key == 1


def test_zero_gross_treated_as_missing_not_out_of_range() -> None:
    df = _frame(
        [
            {
                "Title": "12 Angry Men",
                "Release Date": "Apr 01 1957",
                "US Gross": 0,
                "Worldwide Gross": 0,
                "Production Budget": 350_000,
                "IMDB Rating": 8.9,
            }
        ]
    )
    cleaned, report = clean(df)
    row = cleaned.iloc[0]

    assert pd.isna(row["us_gross"])
    assert pd.isna(row["worldwide_gross"])
    assert row["production_budget"] == 350_000
    assert report.numeric_zero_as_missing.get("us_gross") == 1
    assert report.numeric_out_of_range == {}


def test_out_of_range_numerics_nulled_and_counted() -> None:
    df = _frame(
        [
            {
                "Title": "Impossible",
                "Release Date": "Jan 01 2000",
                "IMDB Rating": 15,
                "Rotten Tomatoes Rating": -5,
                "Running Time min": 12,
                "IMDB Votes": -3,
            }
        ]
    )
    cleaned, report = clean(df)
    row = cleaned.iloc[0]

    assert pd.isna(row["imdb_rating"])
    assert pd.isna(row["rt_rating"])
    assert pd.isna(row["running_time_min"])
    assert pd.isna(row["imdb_votes"])
    assert report.numeric_out_of_range["imdb_rating"] == 1
    assert report.numeric_out_of_range["rt_rating"] == 1
    assert report.numeric_out_of_range["running_time_min"] == 1
    assert report.numeric_out_of_range["imdb_votes"] == 1


def test_distributor_20th_not_mangled_by_title_case() -> None:
    df = _frame(
        [{"Title": "Avatar", "Release Date": "Dec 18 2009", "Distributor": "20th Century Fox"}]
    )
    cleaned, _report = clean(df)
    assert cleaned.iloc[0]["distributor"] == "20th Century Fox"
