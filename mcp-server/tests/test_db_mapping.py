"""row_to_movie mapping for UUID / Decimal / null title."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from src.server.db import row_to_movie


class _Row(dict[str, object]):
    """Minimal asyncpg.Record stand-in (supports both [] and iteration)."""


def test_row_to_movie_coerces_types() -> None:
    movie_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    row = _Row(
        id=movie_id,
        title=None,
        release_year=1999,
        major_genre="Action",
        mpaa_rating="R",
        director="The Wachowskis",
        distributor="Warner Bros.",
        imdb_rating=Decimal("8.7"),
        rt_rating=87,
        similarity=Decimal("0.95"),
        match_type="semantic",
    )
    movie = row_to_movie(row)
    assert movie.id == str(movie_id)
    assert movie.title == ""
    assert movie.imdb_rating == 8.7
    assert movie.similarity == 0.95
    assert movie.release_year == 1999
    assert movie.match_type == "semantic"


def test_row_to_movie_carries_match_type_for_fuzzy_hits() -> None:
    """A trigram score must not be mistaken for a cosine score."""
    row = _Row(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        title="The Matrix",
        release_year=1999,
        major_genre=None,
        mpaa_rating=None,
        director=None,
        distributor=None,
        imdb_rating=None,
        rt_rating=None,
        similarity=0.42,
        match_type="fuzzy",
    )
    movie = row_to_movie(row)
    assert movie.match_type == "fuzzy"
    assert movie.similarity == 0.42
