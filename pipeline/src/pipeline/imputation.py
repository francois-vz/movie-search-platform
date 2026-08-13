"""Stage 1.2 — Imputation.

Decide how to handle missing values across numeric and categorical fields.
Strategy per field is documented in the README "Data Decisions" section and
recorded in the ImputationReport so downstream consumers can trust provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ImputationReport:
    """Per-field imputation counts and the strategy applied."""

    strategy_by_field: dict[str, str] = field(default_factory=dict)
    imputed_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


def impute(df: pd.DataFrame) -> tuple[pd.DataFrame, ImputationReport]:
    """Impute missing values and return the frame + report.

    TODO (document rationale for each in README):
      - numeric ratings/budget/runtime: median or model-based; add *_imputed flags
      - categorical (MPAA, Director, Distributor): "Unknown" sentinel vs mode
      - never fabricate values that would mislead semantic search
    """
    raise NotImplementedError
