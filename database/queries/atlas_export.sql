-- Atlas export: embeddings + metadata for Embedding Atlas (Part 5).
-- Not executed by Flyway. Consumed by scripts/export_embeddings_atlas.py.
--
-- Reads the Part 2 movies table. No separate seed — rows exist only after
-- the 1.5 loader writes embeddings. Untitled / unembedded rows are skipped.
--
-- Columns:
--   id, title, augmented_text     identity + hover text
--   major_genre                   colour-by field in the Atlas UI
--   decade, mpaa_rating, director, distributor, imdb_rating, rt_rating,
--   budget_tier, blockbuster_flag metadata filters / charts
--   embedding                     vector(768) (nomic-embed-text); parsed to a
--                                 768-float list in Parquet for --vector
--
-- Cosine space matches idx_movies_embedding_hnsw (vector_cosine_ops).
-- Atlas projects with --umap-metric cosine --umap-random-state 42.
-- us_dvd_sales is omitted (not in V1).

SELECT
    id,
    title,
    major_genre,
    decade,
    mpaa_rating,
    director,
    distributor,
    imdb_rating,
    rt_rating,
    budget_tier,
    blockbuster_flag,
    augmented_text,
    embedding
FROM movies
WHERE embedding IS NOT NULL;
