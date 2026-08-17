"""Stage 1.1 — Data cleaning.

Implemented incrementally, one brief bullet at a time:

  [x] Point 1 — Remove or flag duplicate entries
  [ ] Point 2 — Standardize string fields
  [ ] Point 3 — Parse and normalize Release Date
  [ ] Point 4 — Validate and constrain numeric fields
  [ ] Point 5 — Produce a structured cleaning report  (report scaffolded below)

Each step records what it did in the ``CleaningReport`` so the pipeline can emit a
structured, auditable summary (see ``reports/section-1.md``).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import pandas as pd

# Column names as they appear in the raw Vega movies dataset.
TITLE_COL = "Title"
RELEASE_DATE_COL = "Release Date"
IMDB_VOTES_COL = "IMDB Votes"


@dataclass
class CleaningReport:
    """Counts of issues found and actions taken during cleaning.

    Fields are grouped by the brief's five bullet points. Only Point 1 is
    populated today; the rest are placeholders that later steps will fill.
    """

    # ---- Point 1: duplicates ----
    rows_in: int = 0
    rows_out: int = 0
    duplicates_removed: int = 0
    rows_missing_dedup_key: int = 0
    duplicate_examples: list[dict[str, str]] = field(default_factory=list)

    # ---- Point 2: string standardization (reserved) ----
    strings_normalized: dict[str, int] = field(default_factory=dict)

    # ---- Point 3: date normalization (reserved) ----
    dates_parsed: int = 0
    dates_unparseable: int = 0

    # ---- Point 4: numeric validation (reserved) ----
    numeric_out_of_range: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_title_key(value: object) -> str:
    """Lowercase + trim + collapse internal whitespace, for dedup keying only.

    This does NOT mutate the real ``Title`` column (Point 2 owns casing/whitespace
    policy for the output); it is purely a stable grouping key for duplicates.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def _release_date_key(value: object) -> str | None:
    """Trimmed raw Release Date string used as the second dedup key component.

    We intentionally key on the raw date string here rather than a parsed year:
    Point 3 has not normalized dates yet, and true duplicate records share the
    same raw date string while remakes/re-releases differ. Once Point 3 lands,
    this key upgrades to ``release_year``.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def remove_duplicates(df: pd.DataFrame, report: CleaningReport) -> pd.DataFrame:
    """Point 1 — remove/flag duplicate entries.

    Strategy:
      * Natural key = (normalized title, raw Release Date string).
      * Within a duplicate group keep the *most complete* row (most non-null
        fields), tie-broken by higher IMDB Votes, then original order.
      * Rows lacking a usable key (missing/blank Release Date) are never
        auto-dropped — they are kept and counted as ``rows_missing_dedup_key``
        so a later, date-aware pass (Point 3 + loader upsert) can resolve them.

    Returns the de-duplicated frame (original column set, original order) and
    mutates ``report`` with the counts + a small sample of dropped rows.
    """
    report.rows_in = len(df)

    work = df.reset_index(drop=True).copy()
    title_key = work[TITLE_COL].map(_normalize_title_key)
    date_key = work[RELEASE_DATE_COL].map(_release_date_key)
    has_key = title_key.ne("") & date_key.notna()

    # Completeness = number of populated fields; tie-break on IMDB Votes.
    completeness = work.notna().sum(axis=1)
    votes = pd.to_numeric(work.get(IMDB_VOTES_COL), errors="coerce").fillna(-1)

    work = work.assign(
        _title_key=title_key,
        _date_key=date_key,
        _has_key=has_key,
        _completeness=completeness,
        _votes=votes,
    )

    keyed = work[work["_has_key"]]
    unkeyed = work[~work["_has_key"]]

    # Sort so the "best" row in each duplicate group sorts first, then keep first.
    keyed_sorted = keyed.sort_values(
        ["_completeness", "_votes"], ascending=[False, False], kind="mergesort"
    )
    dropped_mask = keyed_sorted.duplicated(subset=["_title_key", "_date_key"], keep="first")
    dropped = keyed_sorted[dropped_mask]
    kept_keyed = keyed_sorted[~dropped_mask]

    report.duplicates_removed = int(len(dropped))
    report.rows_missing_dedup_key = int(len(unkeyed))
    report.duplicate_examples = [
        {"title": str(row[TITLE_COL]), "release_date": str(row[RELEASE_DATE_COL])}
        for _, row in dropped.head(10).iterrows()
    ]

    helper_cols = ["_title_key", "_date_key", "_has_key", "_completeness", "_votes"]
    result = (
        pd.concat([kept_keyed, unkeyed])
        .sort_index()
        .drop(columns=helper_cols)
        .reset_index(drop=True)
    )
    report.rows_out = len(result)
    return result


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Run the (currently partial) 1.1 cleaning pipeline.

    Today this runs only Point 1. Points 2–5 will be chained here as they land.
    """
    report = CleaningReport()
    df = remove_duplicates(df, report)
    # TODO Point 2: standardize string fields
    # TODO Point 3: parse/normalize Release Date
    # TODO Point 4: validate/constrain numeric fields
    return df, report
