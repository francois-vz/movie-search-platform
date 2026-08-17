-- Direct lookup by primary key for get_movie_by_id.
-- $1  uuid  movie id
--
-- Backs GET /api/v1/movies/{id} in the .NET API, which follows an id returned
-- by search_movies_by_description or get_similar_movies.
--
-- No matching happens here, so similarity is NULL and match_type is 'lookup'.

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
    NULL::double precision AS similarity,
    'lookup'::text AS match_type
FROM movies
WHERE id = $1::uuid;
