-- V1 — initial schema (Part 2)
-- Managed by Flyway. Forward-only. Safe to re-run locally after
-- `docker compose down -v` while this phase is still in flux.
--
-- Dimensionality: vector(768) matches nomic-embed-text (Ollama).
-- Unique key: (lower(title), release_year) WHERE both are non-null —
-- the same natural key 1.1 cleaning uses. title is nullable so the one
-- untitled 2006 Vega row is not rejected by the schema; the 1.5 loader skips
-- it at load time and counts it, because a NULL title cannot participate in
-- the unique index and would therefore re-insert on every run.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS movies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Core metadata (1.1 snake_case). title is nullable: one untitled row.
    title               TEXT,
    release_date        DATE,
    release_year        INTEGER,
    major_genre         TEXT,
    mpaa_rating         TEXT,
    director            TEXT,
    distributor         TEXT,
    creative_type       TEXT,
    source              TEXT,

    -- Numerics produced by 1.1. us_dvd_sales is cleaned but omitted (too sparse).
    imdb_rating         NUMERIC(3,1),
    imdb_votes          INTEGER,
    rt_rating           INTEGER,
    production_budget   BIGINT,
    us_gross            BIGINT,
    worldwide_gross     BIGINT,
    running_time_min    INTEGER,

    -- Derived features (Part 1.3; filled by the pipeline, empty until then).
    budget_tier         TEXT,
    decade              INTEGER,
    rating_score_delta  NUMERIC,
    blockbuster_flag    BOOLEAN,

    -- Imputation provenance (Part 1.2; filled by the pipeline, empty until then).
    imdb_rating_imputed         BOOLEAN NOT NULL DEFAULT FALSE,
    rt_rating_imputed           BOOLEAN NOT NULL DEFAULT FALSE,
    production_budget_imputed   BOOLEAN NOT NULL DEFAULT FALSE,
    running_time_min_imputed    BOOLEAN NOT NULL DEFAULT FALSE,

    -- Search payload. embedding stays nullable until the 1.5 loader writes it.
    augmented_text      TEXT,
    embedding           vector(768),

    -- Audit
    pipeline_version    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent upsert target for 1.5. Partial so NULL title/year rows (the
-- untitled 2006 record, any unparseable date) are excluded from uniqueness;
-- Postgres unique indexes do not collide on NULL anyway. The loader's
-- ON CONFLICT target must match this index definition exactly.
CREATE UNIQUE INDEX IF NOT EXISTS uq_movies_title_year
    ON movies (lower(title), release_year)
    WHERE title IS NOT NULL AND release_year IS NOT NULL;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_movies_updated_at ON movies;
CREATE TRIGGER trg_movies_updated_at
    BEFORE UPDATE ON movies
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
