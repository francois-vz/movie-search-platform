"""Unit tests for Section 1.1 Point 1 — duplicate handling."""

from __future__ import annotations

import pandas as pd

from src.pipeline.cleaning import CleaningReport, clean, remove_duplicates


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_exact_duplicate_removed_keeping_more_complete_row() -> None:
    df = _frame(
        [
            # Sparse version of the same movie.
            {"Title": "The Matrix", "Release Date": "Mar 31 1999", "Director": None, "IMDB Votes": 10},
            # Richer version — should be the one kept.
            {"Title": "the matrix ", "Release Date": "Mar 31 1999", "Director": "Wachowski", "IMDB Votes": 500},
        ]
    )
    cleaned, report = clean(df)

    assert report.rows_in == 2
    assert report.duplicates_removed == 1
    assert report.rows_out == 1
    assert cleaned.iloc[0]["Director"] == "Wachowski"


def test_same_title_different_dates_are_not_duplicates() -> None:
    df = _frame(
        [
            {"Title": "The Mummy", "Release Date": "May 7 1999", "IMDB Votes": 100},
            {"Title": "The Mummy", "Release Date": "Jun 10 2017", "IMDB Votes": 200},
        ]
    )
    _cleaned, report = clean(df)

    assert report.duplicates_removed == 0
    assert report.rows_out == 2


def test_rows_missing_release_date_are_flagged_not_dropped() -> None:
    df = _frame(
        [
            {"Title": "Mystery Film", "Release Date": None, "IMDB Votes": 1},
            {"Title": "Mystery Film", "Release Date": "  ", "IMDB Votes": 2},
        ]
    )
    report = CleaningReport()
    result = remove_duplicates(df, report)

    assert report.duplicates_removed == 0
    assert report.rows_missing_dedup_key == 2
    assert len(result) == 2


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
