"""Stage 1.1 — Data cleaning.

  [x] Point 1 — Remove or flag duplicate entries
  [x] Point 2 — Standardize string fields
  [x] Point 3 — Parse and normalize Release Date
  [x] Point 4 — Validate and constrain numeric fields
  [x] Point 5 — Produce a structured cleaning report

Guiding principle: flag rather than silently mutate. Cleaning fixes structure
and unambiguous errors; filling missing values is 1.2's job.

See ``reports/section-1.md`` for the full justification of every rule.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

# Newest genuine theatrical year in the frozen Vega movies dataset (Tintin /
# Restless, 2011). Every later year in the file is a 19xx classic encoded +100.
MAX_GENUINE_RELEASE_YEAR = 2011

_WS = re.compile(r"\s+")
_SENTINELS = frozenset({"", "none", "n/a", "na", "null", "unknown", "nan"})

# Brief uses spaced names ("Release Date"); current vega-datasets uses
# underscores ("Release_Date"). Accept both, emit schema snake_case.
COLUMN_RENAME: dict[str, str] = {
    "Title": "title",
    "US Gross": "us_gross",
    "US_Gross": "us_gross",
    "Worldwide Gross": "worldwide_gross",
    "Worldwide_Gross": "worldwide_gross",
    "US DVD Sales": "us_dvd_sales",
    "US_DVD_Sales": "us_dvd_sales",
    "Production Budget": "production_budget",
    "Production_Budget": "production_budget",
    "Release Date": "release_date",
    "Release_Date": "release_date",
    "MPAA Rating": "mpaa_rating",
    "MPAA_Rating": "mpaa_rating",
    "Running Time min": "running_time_min",
    "Running_Time_min": "running_time_min",
    "Distributor": "distributor",
    "Source": "source",
    "Major Genre": "major_genre",
    "Major_Genre": "major_genre",
    "Creative Type": "creative_type",
    "Creative_Type": "creative_type",
    "Director": "director",
    "Rotten Tomatoes Rating": "rt_rating",
    "Rotten_Tomatoes_Rating": "rt_rating",
    "IMDB Rating": "imdb_rating",
    "IMDB_Rating": "imdb_rating",
    "IMDB Votes": "imdb_votes",
    "IMDB_Votes": "imdb_votes",
}

STRING_COLUMNS = (
    "title",
    "major_genre",
    "mpaa_rating",
    "director",
    "distributor",
    "creative_type",
    "source",
)

# Canonicalise only true aliases / casing drift. Keys are lowercased.
MPAA_ALIASES: dict[str, str] = {
    "g": "G",
    "pg": "PG",
    "pg13": "PG-13",
    "pg-13": "PG-13",
    "pg 13": "PG-13",
    "r": "R",
    "nc17": "NC-17",
    "nc-17": "NC-17",
    "nc 17": "NC-17",
    "not rated": "Not Rated",
    "not-rated": "Not Rated",
    "unrated": "Not Rated",
    "nr": "Not Rated",
    "open": "Open",
}

# Inclusive bounds. None = unbounded on that side.
NUMERIC_BOUNDS: dict[str, tuple[float | None, float | None]] = {
    "imdb_rating": (0.0, 10.0),
    "rt_rating": (0.0, 100.0),
    "imdb_votes": (0.0, None),
    "production_budget": (0.0, None),
    "us_gross": (0.0, None),
    "worldwide_gross": (0.0, None),
    "us_dvd_sales": (0.0, None),
    "running_time_min": (30.0, 300.0),
}

# 0 is a data-entry placeholder for money, not a real $0 figure.
ZERO_IS_MISSING = frozenset(
    {"production_budget", "us_gross", "worldwide_gross", "us_dvd_sales"}
)


@dataclass
class CleaningReport:
    """Counts of issues found and actions taken during cleaning."""

    rows_in: int = 0
    rows_out: int = 0
    columns_renamed: dict[str, str] = field(default_factory=dict)

    # Point 1
    duplicates_removed: int = 0
    rows_missing_dedup_key: int = 0
    duplicate_examples: list[dict[str, str]] = field(default_factory=list)

    # Point 2
    strings_normalized: dict[str, int] = field(default_factory=dict)
    sentinels_nulled: dict[str, int] = field(default_factory=dict)
    titles_stringified: int = 0

    # Point 3
    dates_parsed: int = 0
    dates_unparseable: int = 0
    dates_century_corrected: int = 0
    century_corrected_examples: list[dict[str, str]] = field(default_factory=list)

    # Point 4
    numeric_out_of_range: dict[str, int] = field(default_factory=dict)
    numeric_zero_as_missing: dict[str, int] = field(default_factory=dict)
    numeric_coerced: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_na(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if not hasattr(result, "any") else False


def _values_differ(left: Any, right: Any) -> bool:
    left_na, right_na = _is_na(left), _is_na(right)
    if left_na and right_na:
        return False
    if left_na or right_na:
        return True
    return bool(left != right)


def _collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _normalize_title_key(value: Any) -> str:
    """Lowercase + trim + collapse whitespace. Keying only — does not mutate title."""
    if _is_na(value):
        return ""
    return _collapse_ws(str(value)).lower()


def _shift_century(ts: Any) -> Any:
    """Subtract 100 years from a timestamp, preserving month/day."""
    if _is_na(ts):
        return ts
    timestamp = pd.Timestamp(ts)
    try:
        return timestamp.replace(year=timestamp.year - 100)
    except ValueError:
        return timestamp - pd.DateOffset(years=100)


def rename_columns(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Map Vega / brief column names onto the schema's snake_case names."""
    mapping = {col: COLUMN_RENAME[col] for col in df.columns if col in COLUMN_RENAME}
    report.columns_renamed = mapping
    return df.rename(columns=mapping)


def _standardize_one(value: Any, column: str) -> Any:
    if _is_na(value):
        return value
    if column == "title" and not isinstance(value, str):
        value = str(value)
    text = _collapse_ws(str(value))
    if text.lower() in _SENTINELS:
        return pd.NA
    if column == "mpaa_rating":
        aliased = MPAA_ALIASES.get(text.lower())
        if aliased is not None:
            return aliased
    return text


def standardize_strings(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Point 2 — whitespace, sentinels, MPAA aliases; stringify numeric titles.

    Casing of titles/directors is preserved. Low-cardinality categoricals are
    *not* blindly ``.title()``'d — that mangles '20th Century Fox'.
    """
    work = df.copy()
    changed: dict[str, int] = {}
    nulled: dict[str, int] = {}
    titles_stringified = 0

    if "title" in work.columns:
        titles_stringified = int(
            work["title"].map(lambda v: (not _is_na(v)) and not isinstance(v, str)).sum()
        )

    for column in STRING_COLUMNS:
        if column not in work.columns:
            continue
        original = work[column]
        updated = original.map(lambda v, col=column: _standardize_one(v, col))
        was_na = original.map(_is_na)
        now_na = updated.map(_is_na)
        cell_changed = [
            _values_differ(a, b)
            for a, b in zip(original.tolist(), updated.tolist(), strict=True)
        ]
        n_changed = int(sum(cell_changed))
        n_nulled = int((~was_na & now_na).sum())
        if n_changed:
            changed[column] = n_changed
        if n_nulled:
            nulled[column] = n_nulled
        work[column] = updated

    report.strings_normalized = changed
    report.sentinels_nulled = nulled
    report.titles_stringified = titles_stringified
    return work


def parse_release_dates(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Point 3 — parse Release Date, century-correct years after 2011, emit release_year."""
    if "release_date" not in df.columns:
        return df

    work = df.copy()
    raw = work["release_date"]
    raw_str = raw.map(lambda v: pd.NA if _is_na(v) else _collapse_ws(str(v)))
    blank = raw_str.map(lambda v: _is_na(v) or str(v) == "")

    parsed = pd.to_datetime(raw_str, format="%b %d %Y", errors="coerce")
    needs_fallback = parsed.isna() & ~blank
    if bool(needs_fallback.any()):
        parsed.loc[needs_fallback] = pd.to_datetime(
            raw_str.loc[needs_fallback], errors="coerce"
        )

    years = parsed.dt.year.copy()
    century_mask = years.notna() & (years > MAX_GENUINE_RELEASE_YEAR)
    n_century = int(century_mask.sum())
    if n_century:
        examples: list[dict[str, str]] = []
        sample = work.loc[century_mask].head(10)
        year_by_index = years.to_dict()
        raw_by_index = raw_str.to_dict()
        for idx, row in sample.iterrows():
            old_year = int(year_by_index[idx])
            examples.append(
                {
                    "title": "" if _is_na(row.get("title")) else str(row.get("title")),
                    "raw": str(raw_by_index[idx]),
                    "from_year": str(old_year),
                    "to_year": str(old_year - 100),
                }
            )
        report.century_corrected_examples = examples
        years = years.mask(century_mask, years - 100)
        shifted = parsed.copy()
        shifted.loc[century_mask] = parsed.loc[century_mask].map(_shift_century)
        parsed = shifted

    report.dates_parsed = int(parsed.notna().sum())
    report.dates_unparseable = int((~blank & parsed.isna()).sum())
    report.dates_century_corrected = n_century

    work["release_date"] = parsed
    work["release_year"] = years.astype("Int64")
    return work


def remove_duplicates(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Point 1 — drop key-duplicates, keep the most complete row.

    Natural key = (normalized title, release_year). Rows missing either
    component are kept and counted as ``rows_missing_dedup_key``.
    """
    work = df.reset_index(drop=True).copy()
    title_col = "title" if "title" in work.columns else None
    year_col = "release_year" if "release_year" in work.columns else None
    votes_col = "imdb_votes" if "imdb_votes" in work.columns else None

    if title_col is None:
        report.rows_missing_dedup_key = len(work)
        return work.reset_index(drop=True)

    title_key = work[title_col].map(_normalize_title_key)
    if year_col is not None:
        year_key = pd.to_numeric(work[year_col], errors="coerce")
        has_year = year_key.notna()
    else:
        year_key = pd.Series([pd.NA] * len(work), index=work.index)
        has_year = pd.Series(False, index=work.index)

    has_key = title_key.ne("") & has_year
    completeness = work.notna().sum(axis=1)
    votes = (
        pd.to_numeric(work[votes_col], errors="coerce").fillna(-1)
        if votes_col is not None
        else pd.Series(-1, index=work.index)
    )

    work = work.assign(
        _title_key=title_key,
        _year_key=year_key,
        _has_key=has_key,
        _completeness=completeness,
        _votes=votes,
    )
    keyed = work[work["_has_key"]]
    unkeyed = work[~work["_has_key"]]

    keyed_sorted = keyed.sort_values(
        ["_completeness", "_votes"], ascending=[False, False], kind="mergesort"
    )
    dropped_mask = keyed_sorted.duplicated(subset=["_title_key", "_year_key"], keep="first")
    dropped = keyed_sorted[dropped_mask]
    kept_keyed = keyed_sorted[~dropped_mask]

    report.duplicates_removed = len(dropped)
    report.rows_missing_dedup_key = len(unkeyed)
    report.duplicate_examples = [
        {
            "title": "" if _is_na(row[title_col]) else str(row[title_col]),
            "release_year": "" if _is_na(row.get("_year_key")) else str(int(row["_year_key"])),
        }
        for _, row in dropped.head(10).iterrows()
    ]

    helper_cols = ["_title_key", "_year_key", "_has_key", "_completeness", "_votes"]
    result = (
        pd.concat([kept_keyed, unkeyed])
        .sort_index()
        .drop(columns=helper_cols)
        .reset_index(drop=True)
    )
    return result


def validate_numerics(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Point 4 — coerce numerics; out-of-range and placeholder zeros → NULL."""
    work = df.copy()
    out_of_range: dict[str, int] = {}
    zero_missing: dict[str, int] = {}
    coerced: dict[str, int] = {}

    for column, (lo, hi) in NUMERIC_BOUNDS.items():
        if column not in work.columns:
            continue
        original = work[column]
        numeric = pd.to_numeric(original, errors="coerce")
        n_coerced = int((original.notna() & numeric.isna()).sum())
        if n_coerced:
            coerced[column] = n_coerced

        invalid = pd.Series(False, index=work.index)
        if lo is not None:
            invalid = invalid | (numeric < lo)
        if hi is not None:
            invalid = invalid | (numeric > hi)
        n_invalid = int(invalid.fillna(False).sum())
        if n_invalid:
            out_of_range[column] = n_invalid
        numeric = numeric.mask(invalid)

        if column in ZERO_IS_MISSING:
            zeros = numeric.eq(0)
            n_zeros = int(zeros.fillna(False).sum())
            if n_zeros:
                zero_missing[column] = n_zeros
            numeric = numeric.mask(zeros)

        work[column] = numeric

    report.numeric_out_of_range = out_of_range
    report.numeric_zero_as_missing = zero_missing
    report.numeric_coerced = coerced
    return work


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Run the full 1.1 cleaning pipeline and return (frame, report)."""
    report = CleaningReport(rows_in=len(df))
    work = df.copy()
    work = rename_columns(work, report)
    work = standardize_strings(work, report)
    work = parse_release_dates(work, report)
    work = remove_duplicates(work, report)
    work = validate_numerics(work, report)
    report.rows_out = len(work)
    return work.reset_index(drop=True), report
