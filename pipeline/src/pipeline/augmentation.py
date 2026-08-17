"""Stage 1.3 — Feature augmentation.

Builds the rich text representation used as embedding input, and engineers the
four derived features V1 reserves columns for.

**The augmented text contains observed facts only.** A line is omitted when its
value is missing, when 1.2 filled it (``<column>_imputed``), or when 1.2 wrote
the ``"Unknown"`` sentinel. Two alternatives were rejected:

* Rendering the filled value — ``Runtime: 107 minutes`` on the 62% of rows whose
  runtime was never recorded would embed a fact the dataset does not support.
* Rendering ``Runtime: Unknown`` — that string is identical across every
  affected row, so it pulls unrelated films together in vector space purely
  because they share a gap. Silence carries no such signal.

Derived features are computed from **observed** inputs only and are NULL
otherwise, for the same reason: they feed Atlas facets and the API response, so
a guess would be indistinguishable from a measurement.

See ``reports/section-1.md`` §1.3 for the rationale behind each feature.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from .imputation import UNKNOWN

# Production budget bands, in nominal USD. Fixed thresholds rather than sample
# quartiles: these are the industry's own vocabulary (a "$15M indie" means the
# same thing regardless of corpus), and they stay comparable across runs if the
# dataset is ever refreshed. Observed quartiles for reference: 6.6M / 20M / 42M.
BUDGET_TIERS: tuple[tuple[float, str], ...] = (
    (15_000_000, "indie"),
    (50_000_000, "mid"),
    (100_000_000, "major"),
)
BUDGET_TIER_TOP = "blockbuster"

# A blockbuster cleared a large absolute bar *and* doubled its money. Using
# both sides avoids flagging a $200M film that cost $250M to make.
BLOCKBUSTER_GROSS_FLOOR = 100_000_000.0
BLOCKBUSTER_RETURN_MULTIPLE = 2.0

# The brief's template, one entry per line: (column, format string).
# The IMDB line is rendered separately because it merges two columns.
TEXT_LINES: tuple[tuple[str, str], ...] = (
    ("title", "Title: {}"),
    ("major_genre", "Genre: {}"),
    ("director", "Director: {}"),
    ("mpaa_rating", "MPAA Rating: {}"),
    ("release_year", "Release Year: {}"),
    ("running_time_min", "Runtime: {} minutes"),
    ("imdb_rating", ""),  # placeholder position; see _imdb_line
    ("rt_rating", "Rotten Tomatoes: {}%"),
    ("production_budget", "Budget: ${}"),
    ("distributor", "Distributor: {}"),
    ("creative_type", "Creative Type: {}"),
    ("source", "Source: {}"),
)

INTEGER_TEXT_COLUMNS = frozenset(
    {"release_year", "running_time_min", "rt_rating", "production_budget"}
)
# Rendered with thousands separators so the text reads like prose.
GROUPED_TEXT_COLUMNS = frozenset({"production_budget"})


@dataclass
class AugmentationReport:
    """Coverage of the derived features and the embedding input."""

    derived_features: list[str] = field(default_factory=list)
    feature_coverage: dict[str, int] = field(default_factory=dict)
    budget_tier_counts: dict[str, int] = field(default_factory=dict)
    augmented_text_rows: int = 0
    augmented_text_empty: int = 0
    mean_text_lines: float = 0.0

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


def _observed(row: pd.Series, column: str) -> Any:
    """Return the value only if it was actually measured, else None."""
    if column not in row.index:
        return None
    value = row[column]
    if _is_na(value):
        return None
    if isinstance(value, str) and value == UNKNOWN:
        return None
    if bool(row.get(f"{column}_imputed", False)):
        return None
    return value


def _format_value(column: str, value: Any) -> str:
    if column in INTEGER_TEXT_COLUMNS:
        number = round(float(value))
        return f"{number:,}" if column in GROUPED_TEXT_COLUMNS else str(number)
    if column == "imdb_rating":
        return f"{float(value):.1f}"
    return str(value)


def _imdb_line(row: pd.Series) -> str | None:
    rating = _observed(row, "imdb_rating")
    if rating is None:
        return None
    line = f"IMDB Rating: {float(rating):.1f}/10"
    votes = _observed(row, "imdb_votes")
    if votes is not None:
        line += f" ({int(votes):,} votes)"
    return line


def build_augmented_text(row: pd.Series) -> str:
    """Render a single movie row into the embedding-input text block."""
    lines: list[str] = []
    for column, template in TEXT_LINES:
        if column == "imdb_rating":
            imdb = _imdb_line(row)
            if imdb is not None:
                lines.append(imdb)
            continue
        value = _observed(row, column)
        if value is None:
            continue
        lines.append(template.format(_format_value(column, value)))
    return "\n".join(lines)


def _budget_tier(value: Any) -> str | None:
    if _is_na(value):
        return None
    budget = float(value)
    for threshold, label in BUDGET_TIERS:
        if budget < threshold:
            return label
    return BUDGET_TIER_TOP


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Engineer the four derived features V1 reserves columns for.

    * ``decade`` — the MCP ``decade`` filter binds directly to it, and it is the
      only way "movies from the 90s" becomes a SQL predicate instead of a hope.
    * ``budget_tier`` — turns a raw dollar amount into the vocabulary users
      actually search with ("small budget", "blockbuster").
    * ``rating_score_delta`` — IMDB (rescaled to 0-100) minus Rotten Tomatoes.
      Positive means audiences liked it more than critics did; it separates
      "critically acclaimed" from "crowd-pleaser", which no single rating does.
    * ``blockbuster_flag`` — commercial outcome, which budget alone misses.
    """
    work = df.copy()

    years = _numeric_series(work, "release_year")
    work["decade"] = (years // 10 * 10).astype("Int64")

    observed_budget = _observed_series(work, "production_budget")
    work["budget_tier"] = observed_budget.map(_budget_tier).astype("object")

    observed_imdb = _observed_series(work, "imdb_rating")
    observed_rt = _observed_series(work, "rt_rating")
    work["rating_score_delta"] = (observed_imdb * 10.0) - observed_rt

    gross = _numeric_series(work, "worldwide_gross")
    # max(floor, 2 x budget) where the budget was observed, else just the floor.
    bar = (observed_budget * BLOCKBUSTER_RETURN_MULTIPLE).fillna(BLOCKBUSTER_GROSS_FLOOR)
    bar = bar.clip(lower=BLOCKBUSTER_GROSS_FLOOR)
    work["blockbuster_flag"] = (gross >= bar).astype("boolean").mask(gross.isna())

    return work


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Numeric view of a column, or an all-NA series when it is absent."""
    if column not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def _observed_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Numeric view of a column with imputed cells masked back out to NA."""
    values = _numeric_series(df, column)
    if column not in df.columns:
        return values
    flag_column = f"{column}_imputed"
    if flag_column in df.columns:
        values = values.mask(df[flag_column].fillna(False).astype(bool))
    return values


def augment(df: pd.DataFrame) -> tuple[pd.DataFrame, AugmentationReport]:
    """Add derived features and the augmented_text column."""
    report = AugmentationReport()
    work = add_derived_features(df)

    work["augmented_text"] = work.apply(build_augmented_text, axis=1)

    report.derived_features = [
        "decade",
        "budget_tier",
        "rating_score_delta",
        "blockbuster_flag",
    ]
    for feature in report.derived_features:
        report.feature_coverage[feature] = int(work[feature].notna().sum())

    tier_counts = work["budget_tier"].value_counts(dropna=True)
    report.budget_tier_counts = {str(k): int(v) for k, v in tier_counts.items()}

    line_counts = work["augmented_text"].map(lambda text: len(text.splitlines()) if text else 0)
    report.augmented_text_rows = int((work["augmented_text"].str.len() > 0).sum())
    report.augmented_text_empty = int((work["augmented_text"].str.len() == 0).sum())
    report.mean_text_lines = round(float(line_counts.mean()), 2) if len(work) else 0.0

    return work, report
