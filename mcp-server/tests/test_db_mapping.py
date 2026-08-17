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
    )
    movie = row_to_movie(row)  # type: ignore[arg-type]
    assert movie.id == str(movie_id)
    assert movie.title == ""
    assert movie.imdb_rating == 8.7
    assert movie.similarity == 0.95
    assert movie.release_year == 1999
