-- V1 — initial schema (Part 2)
-- Managed by Flyway. Extend as needed; keep migrations forward-only.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS movies (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title             TEXT NOT NULL,
    release_year      INTEGER,
    major_genre       TEXT,
    mpaa_rating       TEXT,
    director          TEXT,
    distributor       TEXT,
    imdb_rating       NUMERIC(3,1),
    rt_rating         INTEGER,
    production_budget BIGINT,
    running_time_min  INTEGER,
    budget_tier       TEXT,
    decade            INTEGER,
    augmented_text    TEXT,
    embedding         vector(768),          -- TODO: match chosen model dimensionality
    pipeline_version  TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Natural key for idempotent upserts from the pipeline.
CREATE UNIQUE INDEX IF NOT EXISTS uq_movies_title_year
    ON movies (lower(title), release_year);
