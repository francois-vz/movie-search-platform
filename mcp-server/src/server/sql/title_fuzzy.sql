-- Fuzzy title match for get_movie_by_title (pg_trgm, idx_movies_title_trgm).
-- Used only when the exact lookup misses. $1  text  user-supplied title.
-- similarity() here is trigram similarity, not cosine — still higher-is-better.

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
    similarity(title, $1)::double precision AS similarity,
    'fuzzy'::text AS match_type
FROM movies
WHERE title IS NOT NULL
  AND title % $1
ORDER BY similarity(title, $1) DESC
LIMIT 1;
