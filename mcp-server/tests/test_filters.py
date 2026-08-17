"""NL filter extraction for Part 3.3 example queries."""

from __future__ import annotations

from src.server.filters import HIGH_IMDB_THRESHOLD, extract_filters, resolve_filters


def test_action_nineties_high_imdb() -> None:
    """3.3: 'action movies from the 90s with high IMDB ratings'."""
    filters = extract_filters("action movies from the 90s with high IMDB ratings")
    assert filters.genre_filter == "Action"
    assert filters.decade == 1990
    assert filters.min_imdb_rating == HIGH_IMDB_THRESHOLD
    assert filters.mpaa_rating is None


def test_critically_acclaimed_drama_small_budgets() -> None:
    """3.3: genre + high IMDB extracted; small budget left to the embedding."""
    filters = extract_filters("critically acclaimed drama films with small budgets")
    assert filters.genre_filter == "Drama"
    assert filters.min_imdb_rating == HIGH_IMDB_THRESHOLD
    assert filters.decade is None
    assert filters.mpaa_rating is None


def test_animated_family_disney_left_to_embedding() -> None:
    """3.3: animated/family/Disney are not major_genre SQL filters."""
    filters = extract_filters("animated family movies distributed by Disney")
    assert filters.genre_filter is None
    assert filters.decade is None
    assert filters.min_imdb_rating is None
    assert filters.mpaa_rating is None


def test_scifi_cameron_left_to_embedding() -> None:
    """3.3: sci-fi is Creative Type, not Vega major_genre; director is embedding-only."""
    filters = extract_filters("sci-fi films directed by James Cameron")
    assert filters.genre_filter is None
    assert filters.decade is None
    assert filters.min_imdb_rating is None
    assert filters.mpaa_rating is None


def test_psychological_thrillers_low_rt() -> None:
    """3.3: thriller → Thriller/Suspense; low RT is not a hybrid SQL filter."""
    filters = extract_filters("dark psychological thrillers with low Rotten Tomatoes scores")
    assert filters.genre_filter == "Thriller/Suspense"
    assert filters.decade is None
    assert filters.min_imdb_rating is None
    assert filters.mpaa_rating is None


def test_explicit_args_win_over_extracted() -> None:
    filters = resolve_filters(
        "action movies from the 90s with high IMDB ratings",
        genre_filter="Drama",
        decade=2000,
        min_imdb_rating=8.0,
        mpaa_rating="R",
    )
    assert filters.genre_filter == "Drama"
    assert filters.decade == 2000
    assert filters.min_imdb_rating == 8.0
    assert filters.mpaa_rating == "R"


def test_explicit_none_falls_back_to_extracted() -> None:
    filters = resolve_filters(
        "action movies from the 90s with high IMDB ratings",
        genre_filter=None,
        decade=None,
        min_imdb_rating=None,
        mpaa_rating=None,
    )
    assert filters.genre_filter == "Action"
    assert filters.decade == 1990
    assert filters.min_imdb_rating == HIGH_IMDB_THRESHOLD


def test_mpaa_and_four_digit_decade() -> None:
    filters = extract_filters("PG-13 comedies from the 1980s")
    assert filters.genre_filter == "Comedy"
    assert filters.decade == 1980
    assert filters.mpaa_rating == "PG-13"
