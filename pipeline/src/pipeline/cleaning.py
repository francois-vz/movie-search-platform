"""Stage 1.1 — Data cleaning.

Responsibilities:
  * de-duplicate records
  * standardize string fields (whitespace, casing, known inconsistencies)
  * parse/normalize Release Date -> datetime
  * validate + constrain numeric fields to sensible ranges
  * produce a structured cleaning report
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class CleaningReport:
    """Counts of issues found and actions taken during cleaning."""

    rows_in: int = 0
    rows_out: int = 0
    duplicates_removed: int = 0
    dates_parsed: int = 0
    dates_unparseable: int = 0
    numeric_out_of_range: dict[str, int] = field(default_factory=dict)
    strings_normalized: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Clean the raw movies dataframe and return the cleaned frame + report.

    TODO:
      - drop/flag duplicates (by normalized Title + Release Date)
      - strip/normalize string columns
      - parse Release Date with explicit format handling + 2-digit year fix
      - clamp/flag impossible numerics (negative budgets, ratings out of scale)
    """
    raise NotImplementedError
