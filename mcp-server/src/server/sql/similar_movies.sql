-- Semantically similar movies for get_similar_movies.
-- $1  uuid  source movie id
-- $2  int   result limit (top_k)
-- Empty CTE (unknown id or null embedding) yields no rows.

WITH query AS (
    SELECT embedding
    FROM movies
    WHERE id = $1::uuid
      AND embedding IS NOT NULL
)
SELECT
    m.id,
    m.title,
    m.release_year,
    m.major_genre,
    m.mpaa_rating,
    m.director,
    m.distributor,
    m.imdb_rating,
    m.rt_rating,
    1 - (m.embedding <=> q.embedding) AS similarity,
    'semantic'::text AS match_type
FROM movies m
CROSS JOIN query q
WHERE m.embedding IS NOT NULL
  AND m.id <> $1::uuid
ORDER BY m.embedding <=> q.embedding
LIMIT $2;
