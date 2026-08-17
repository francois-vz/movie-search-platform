-- Hybrid search: vector similarity + metadata filters.
-- Not executed by Flyway. Consumed by Part 3 (MCP search_movies_by_description)
-- and Part 4 (GET /api/v1/movies/search). Bind parameters:
--
--   $1  vector(768)  query embedding (MCP prefixes the text with "search_query:")
--   $2  text         major_genre filter, or NULL to skip
--   $3  int          decade filter (e.g. 1990), or NULL to skip
--   $4  numeric      minimum IMDB rating, or NULL to skip
--   $5  text         mpaa_rating filter, or NULL to skip
--   $6  int          result limit (top_k)
--
-- Operator <=> is cosine *distance* (matches idx_movies_embedding_hnsw
-- vector_cosine_ops). Similarity is reported as 1 - distance so callers
-- see a higher-is-better score in [0, 1] for normalized embeddings.
--
-- SELECT list matches MCP MovieResult (id, title, release_year, major_genre,
-- mpaa_rating, director, distributor, imdb_rating, rt_rating, similarity).
-- Bind parameters $1–$6 are unchanged from the Part 2 contract.
--
-- Example NL query this shape covers:
--   "action movies from the 90s with high IMDB ratings"
--   → $2 = 'Action', $3 = 1990, $4 = 7.5, $5 = NULL
--
-- With ~3,200 rows the planner may seq-scan + sort rather than hit HNSW;
-- the index still satisfies the brief and will be used as the corpus grows.

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
    1 - (embedding <=> $1::vector) AS similarity
FROM movies
WHERE embedding IS NOT NULL
  AND ($2::text    IS NULL OR major_genre = $2)
  AND ($3::int     IS NULL OR decade = $3)
  AND ($4::numeric IS NULL OR imdb_rating >= $4)
  AND ($5::text    IS NULL OR mpaa_rating = $5)
ORDER BY embedding <=> $1::vector
LIMIT $6;
