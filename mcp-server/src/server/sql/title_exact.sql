-- Exact title match for get_movie_by_title (case-insensitive).
-- $1  text  user-supplied title

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
    NULL::double precision AS similarity
FROM movies
WHERE title IS NOT NULL
  AND lower(title) = lower($1)
LIMIT 1;
