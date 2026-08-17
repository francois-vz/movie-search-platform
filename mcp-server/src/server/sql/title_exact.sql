-- Exact title match for get_movie_by_title (case-insensitive).
-- $1  text  user-supplied title
--
-- similarity is 1.0 rather than NULL: an exact match is a perfect match, and
-- match_type = 'exact' says the score is not a cosine distance.

SELECT
    id,
    title,
    release_year,
    major_genre,
    mpaa_rating,
    director,
    distributor,
    imdb_rating,
    rt_rating,
    1.0::double precision AS similarity,
    'exact'::text AS match_type
FROM movies
WHERE title IS NOT NULL
  AND lower(title) = lower($1)
LIMIT 1;
