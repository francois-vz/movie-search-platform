-- V2 — indexes (Part 2)
-- HNSW index for cosine vector similarity search.
CREATE INDEX IF NOT EXISTS idx_movies_embedding_hnsw
    ON movies USING hnsw (embedding vector_cosine_ops);

-- Supporting indexes for hybrid (metadata + vector) queries.
CREATE INDEX IF NOT EXISTS idx_movies_genre  ON movies (major_genre);
CREATE INDEX IF NOT EXISTS idx_movies_decade ON movies (decade);
CREATE INDEX IF NOT EXISTS idx_movies_imdb   ON movies (imdb_rating);
