"""Stage 1.3 — Feature augmentation.

Builds the rich text representation used as embedding input, and engineers
derived features (at minimum two, with documented rationale).
"""

from __future__ import annotations

import pandas as pd

AUGMENTED_TEXT_TEMPLATE = """\
Title: {title}
Genre: {genre}
Director: {director}
MPAA Rating: {mpaa_rating}
Release Year: {year}
Runtime: {runtime} minutes
IMDB Rating: {imdb_rating}/10 ({imdb_votes} votes)
Rotten Tomatoes: {rt_rating}%
Budget: ${budget}
Distributor: {distributor}
Creative Type: {creative_type}
Source: {source}"""


def build_augmented_text(row: pd.Series) -> str:
    """Render a single movie row into the embedding-input text block."""
    raise NotImplementedError


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Engineer derived features.

    TODO (>= 2, documented):
      - decade (from release year)
      - budget_tier (quantile buckets: indie / mid / blockbuster)
      - rating_score_delta (IMDB vs Rotten Tomatoes normalized gap)
      - blockbuster_flag (budget + gross heuristic)
    """
    raise NotImplementedError


def augment(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived features and the augmented_text column."""
    raise NotImplementedError
