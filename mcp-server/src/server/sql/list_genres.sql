-- Distinct genres for list_genres. Nulls skipped; sorted for stable output.

SELECT DISTINCT major_genre
FROM movies
WHERE major_genre IS NOT NULL
ORDER BY 1;
