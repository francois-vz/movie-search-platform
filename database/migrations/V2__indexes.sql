-- V2 — indexes (Part 2)
-- Search indexes only. Uniqueness lives in V1 (uq_movies_title_year).

-- Cosine HNSW for semantic kNN. Partial: skip rows the loader has not
-- embedded yet. ~3k rows; default m / ef_construction are enough.
CREATE INDEX IF NOT EXISTS idx_movies_embedding_hnsw
    ON movies USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

-- Hybrid metadata filters used by MCP search_movies_by_description /
-- GET /api/v1/movies/search.
CREATE INDEX IF NOT EXISTS idx_movies_genre ON movies (major_genre);
CREATE INDEX IF NOT EXISTS idx_movies_decade ON movies (decade);
CREATE INDEX IF NOT EXISTS idx_movies_imdb ON movies (imdb_rating);
CREATE INDEX IF NOT EXISTS idx_movies_mpaa ON movies (mpaa_rating);

-- Fuzzy title match for get_movie_by_title (pg_trgm % / similarity()).
CREATE INDEX IF NOT EXISTS idx_movies_title_trgm
    ON movies USING gin (title gin_trgm_ops);
