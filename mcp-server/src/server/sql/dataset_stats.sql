-- Summary statistics for get_dataset_stats.
-- COUNT(DISTINCT major_genre) skips nulls. AVG/MIN/MAX are null on an empty table.

SELECT
    COUNT(*)::int AS total_movies,
    COUNT(DISTINCT major_genre)::int AS genres,
    MIN(release_year) AS year_min,
    MAX(release_year) AS year_max,
    AVG(imdb_rating)::double precision AS avg_imdb_rating
FROM movies;
