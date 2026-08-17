"""Lightweight NL → hybrid-search filter extraction.

Explicit tool arguments always win. Cues that are not hybrid-search columns
(director, distributor, budget, Rotten Tomatoes, sci-fi/animated/family) are
left on the query string so the embedding can match augmented_text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HIGH_IMDB_THRESHOLD = 7.5

# Longer phrases first so "romantic comedy" is not captured as "comedy".
# Patterns allow simple plurals (thrillers, comedies). Only Vega major_genre
# values — Creative Type (Science Fiction) and informal labels (animated,
# family, sci-fi) stay on the embedding.
_GENRE_PHRASES: tuple[tuple[str, str], ...] = (
    (r"psychological\s+thrillers?", "Thriller/Suspense"),
    (r"romantic\s+comed(?:y|ies)", "Romantic Comedy"),
    (r"black\s+comed(?:y|ies)", "Black Comedy"),
    (r"concerts?(?:\s*/\s*performances?)?", "Concert/Performance"),
    (r"thrillers?", "Thriller/Suspense"),
    (r"suspense", "Thriller/Suspense"),
    (r"documentar(?:y|ies)", "Documentary"),
    (r"adventures?", "Adventure"),
    (r"westerns?", "Western"),
    (r"musicals?", "Musical"),
    (r"horrors?", "Horror"),
    (r"comed(?:y|ies)", "Comedy"),
    (r"dramas?", "Drama"),
    (r"actions?", "Action"),
)

_GENRE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{phrase}\b", re.IGNORECASE), genre)
    for phrase, genre in _GENRE_PHRASES
)

_HIGH_IMDB_RE = re.compile(
    r"\b(?:high(?:ly)?\s+rated|high\s+imdb|critically\s+acclaimed)\b",
    re.IGNORECASE,
)

_MPAA_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bnc[-\s]?17\b", re.IGNORECASE), "NC-17"),
    (re.compile(r"\bpg[-\s]?13\b", re.IGNORECASE), "PG-13"),
    (re.compile(r"\bnot\s+rated\b|\bunrated\b", re.IGNORECASE), "Not Rated"),
    (re.compile(r"\br[-\s]?rated\b|\brating\s+r\b", re.IGNORECASE), "R"),
    (re.compile(r"\bpg[-\s]?rated\b", re.IGNORECASE), "PG"),
    (re.compile(r"\bg[-\s]?rated\b", re.IGNORECASE), "G"),
)

_FOUR_DIGIT_DECADE_RE = re.compile(r"\b((?:19|20)\d0)s\b", re.IGNORECASE)
_TWO_DIGIT_DECADE_RE = re.compile(r"\b(\d{2})s\b", re.IGNORECASE)

_NAMED_DECADES: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\bnineties\b", re.IGNORECASE), 1990),
    (re.compile(r"\beighties\b", re.IGNORECASE), 1980),
    (re.compile(r"\bseventies\b", re.IGNORECASE), 1970),
    (re.compile(r"\bsixties\b", re.IGNORECASE), 1960),
    (re.compile(r"\bfifties\b", re.IGNORECASE), 1950),
)


@dataclass(frozen=True)
class SearchFilters:
    genre_filter: str | None = None
    decade: int | None = None
    min_imdb_rating: float | None = None
    mpaa_rating: str | None = None


def extract_filters(query: str) -> SearchFilters:
    """Infer hybrid filters from a natural-language query."""
    return SearchFilters(
        genre_filter=_extract_genre(query),
        decade=_extract_decade(query),
        min_imdb_rating=HIGH_IMDB_THRESHOLD if _HIGH_IMDB_RE.search(query) else None,
        mpaa_rating=_extract_mpaa(query),
    )


def resolve_filters(
    query: str,
    *,
    genre_filter: str | None,
    decade: int | None,
    min_imdb_rating: float | None,
    mpaa_rating: str | None,
) -> SearchFilters:
    """Merge explicit tool args (winner) with filters parsed from query."""
    extracted = extract_filters(query)
    return SearchFilters(
        genre_filter=genre_filter if genre_filter is not None else extracted.genre_filter,
        decade=decade if decade is not None else extracted.decade,
        min_imdb_rating=(
            min_imdb_rating if min_imdb_rating is not None else extracted.min_imdb_rating
        ),
        mpaa_rating=mpaa_rating if mpaa_rating is not None else extracted.mpaa_rating,
    )


def _extract_genre(query: str) -> str | None:
    for pattern, genre in _GENRE_PATTERNS:
        if pattern.search(query):
            return genre
    return None


def _extract_mpaa(query: str) -> str | None:
    for pattern, rating in _MPAA_PATTERNS:
        if pattern.search(query):
            return rating
    return None


def _extract_decade(query: str) -> int | None:
    match = _FOUR_DIGIT_DECADE_RE.search(query)
    if match:
        return int(match.group(1))
    for pattern, decade in _NAMED_DECADES:
        if pattern.search(query):
            return decade
    match = _TWO_DIGIT_DECADE_RE.search(query)
    if match:
        year = int(match.group(1))
        return 1900 + year if year >= 20 else 2000 + year
    return None
