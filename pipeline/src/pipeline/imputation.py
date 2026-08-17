"""Stage 1.2 — Imputation.

Decide how to handle missing values across numeric and categorical fields.

Two rules, applied by field *role* rather than by dtype. See
``reports/section-1.md`` §1.2 for the measured missingness that motivates each.

1. **Descriptive categoricals** (``mpaa_rating``, ``director``, ``distributor``,
   ``creative_type``, ``source``) get an explicit ``"Unknown"`` sentinel.
   Mode-imputation is rejected on purpose: filling 1,331 missing directors with
   the modal name would attribute films to a person who did not make them, and
   the brief's own example query is *"sci-fi films directed by James Cameron"*.
   A wrong fact is worse than an absent one.

2. **Numerics** (``imdb_rating``, ``rt_rating``, ``running_time_min``,
   ``production_budget``) get a group median with a global-median fallback, and
   every filled cell is flagged in the matching ``<column>_imputed`` boolean —
   the provenance columns V1 already reserves. Downstream consumers can then
   tell an observed 6.4 from a filled one.

``major_genre`` is deliberately **left NULL**. It is a facet: the MCP
``list_genres`` tool advertises it and ``genre_filter`` matches on it, so an
``"Unknown"`` genre would become a browsable category and a selectable filter
value. Absent is the honest answer there.

Imputation fills the *columns*; it does not fill the embedding input. Stage 1.3
renders only observed facts into ``augmented_text``, so a filled runtime never
reaches the embedding model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

UNKNOWN = "Unknown"

# Descriptive text fields: an explicit sentinel beats a fabricated value.
SENTINEL_COLUMNS: tuple[str, ...] = (
    "mpaa_rating",
    "director",
    "distributor",
    "creative_type",
    "source",
)

# Facet fields: stay NULL so they never pollute list_genres / genre_filter.
FACET_COLUMNS: tuple[str, ...] = ("major_genre",)

# column -> column whose value groups the median.
# Genre for the rating/runtime fields: a Horror runtime is a better guess than a
# dataset-wide one. Decade for budget: nominal budgets inflate over time.
# Genre x decade was measured and rejected — 28 of its 75 cells hold <5 rows.
NUMERIC_STRATEGIES: dict[str, str] = {
    "imdb_rating": "major_genre",
    "rt_rating": "major_genre",
    "running_time_min": "major_genre",
    "production_budget": "decade",
}

# A group median computed from fewer observations than this is noise; those
# rows fall back to the global median instead.
MIN_GROUP_SIZE = 10

# Decimal places to round a filled value to, so it matches the V1 column type
# (imdb_rating is NUMERIC(3,1); the rest are integer columns).
ROUNDING: dict[str, int] = {
    "imdb_rating": 1,
    "rt_rating": 0,
    "running_time_min": 0,
    "production_budget": 0,
}

# Nullable integer columns after imputation, so the loader binds ints not floats.
INTEGER_COLUMNS: tuple[str, ...] = (
    "rt_rating",
    "running_time_min",
    "production_budget",
    "imdb_votes",
    "us_gross",
    "worldwide_gross",
    "release_year",
)


@dataclass
class ImputationReport:
    """Per-field imputation counts and the strategy applied."""

    strategy_by_field: dict[str, str] = field(default_factory=dict)
    imputed_counts: dict[str, int] = field(default_factory=dict)
    # Of the imputed cells, how many used a group median vs the global fallback.
    group_median_fills: dict[str, int] = field(default_factory=dict)
    global_median_fills: dict[str, int] = field(default_factory=dict)
    global_medians: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decade_series(df: pd.DataFrame) -> pd.Series:
    """Decade key derived on the fly; 1.3 owns the stored ``decade`` column."""
    if "release_year" not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Int64")
    years = pd.to_numeric(df["release_year"], errors="coerce")
    decades: pd.Series = (years // 10 * 10).astype("Int64")
    return decades


def _group_key(df: pd.DataFrame, name: str) -> pd.Series | None:
    if name == "decade":
        return _decade_series(df)
    if name in df.columns:
        return df[name]
    return None


def impute_numeric(df: pd.DataFrame, report: ImputationReport) -> pd.DataFrame:
    """Fill numeric gaps with a group median, flagging provenance per cell."""
    work = df.copy()

    for column, group_name in NUMERIC_STRATEGIES.items():
        flag_column = f"{column}_imputed"
        if column not in work.columns:
            work[flag_column] = False
            continue

        values = pd.to_numeric(work[column], errors="coerce")
        missing = values.isna()
        # Provenance is recorded before any filling happens.
        work[flag_column] = missing
        report.imputed_counts[column] = int(missing.sum())

        if not bool(missing.any()):
            report.strategy_by_field[column] = (
                f"median by {group_name} (no missing values in this run)"
            )
            work[column] = values
            continue

        filled = values.copy()
        keys = _group_key(work, group_name)
        n_group = 0
        if keys is not None and bool(keys.notna().any()):
            group_median = values.groupby(keys, dropna=True).transform("median")
            observed_per_group = values.notna().groupby(keys, dropna=True).transform("sum")
            usable = missing & group_median.notna() & (observed_per_group >= MIN_GROUP_SIZE)
            usable = usable.fillna(False).astype(bool)
            filled = filled.mask(usable, group_median)
            n_group = int(usable.sum())

        remaining = filled.isna()
        n_global = int(remaining.sum())
        if n_global and bool(values.notna().any()):
            global_median = float(values.median())
            filled = filled.mask(remaining, global_median)
            report.global_medians[column] = global_median

        precision = ROUNDING.get(column)
        if precision is not None:
            filled = filled.round(precision)

        work[column] = filled
        report.group_median_fills[column] = n_group
        report.global_median_fills[column] = n_global
        report.strategy_by_field[column] = (
            f"median by {group_name} (min {MIN_GROUP_SIZE} observations), "
            "else global median; flagged in " + flag_column
        )

    return work


def impute_categorical(df: pd.DataFrame, report: ImputationReport) -> pd.DataFrame:
    """Fill descriptive categoricals with an explicit sentinel; leave facets NULL."""
    work = df.copy()

    for column in SENTINEL_COLUMNS:
        if column not in work.columns:
            continue
        missing = work[column].isna()
        report.imputed_counts[column] = int(missing.sum())
        report.strategy_by_field[column] = f'"{UNKNOWN}" sentinel (never mode-imputed)'
        work[column] = work[column].fillna(UNKNOWN)

    for column in FACET_COLUMNS:
        if column not in work.columns:
            continue
        report.imputed_counts[column] = 0
        report.strategy_by_field[column] = (
            "left NULL — facet field surfaced by list_genres / genre_filter"
        )

    return work


def _finalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Cast whole-number columns to nullable Int64 for clean binding in 1.5."""
    work = df.copy()
    for column in INTEGER_COLUMNS:
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").round(0).astype("Int64")
    return work


def impute(df: pd.DataFrame) -> tuple[pd.DataFrame, ImputationReport]:
    """Impute missing values and return the frame + report."""
    report = ImputationReport()
    work = impute_numeric(df, report)
    work = impute_categorical(work, report)
    work = _finalize_dtypes(work)
    return work, report
