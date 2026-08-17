# Section 2 — Vector Database Report

Living report for PostgreSQL 16 + pgvector (Part 2 of the assessment). Schema and
indexes live under `database/migrations/`; the hybrid query is documented (not
applied by Flyway) at `database/queries/hybrid_search.sql`.

The plan this part was built from: [plans/part-2-vector-db.plan.md](plans/part-2-vector-db.plan.md).

**How to apply**

```bash
docker compose up -d postgres
docker compose run --rm migrate
```

The `mcp-server` and `atlas` services wait on `migrate` completing. The full
pipeline writes to this database; only `--dry-run` (transform stages 1.1–1.3)
runs without it:

```bash
docker compose run --rm pipeline                       # clean → … → load
docker compose run --rm --no-deps pipeline --dry-run   # no DB, no model server
```

**Resetting after schema edits**

Flyway versions are forward-only. While V1/V2 are still being edited in place,
wipe the local volume before re-applying:

```bash
docker compose down -v
```

Do not add a separate seed script. The brief says the seed **is** the pipeline
(Part 1.5 / `loader.py`).

---

## Flyway, not Alembic

The brief allows either. We keep Flyway (already wired in Compose).

- The stack is polyglot (Python pipeline + MCP, .NET API). SQL-first DDL is the
  shared language; Alembic would tie migrations to the Python service.
- pgvector types, HNSW opclasses, and partial indexes are clearer as raw SQL
  than as SQLAlchemy ops.
- The same files run locally and later on RDS (Part 6). `CREATE EXTENSION IF NOT
  EXISTS vector` / `pg_trgm` stay RDS-safe for `rds_superuser`.

---

## Unique-key contract with 1.1

1.1 cleaning de-duplicates on **`(normalized title, release_year)`** and states
that the loader's `ON CONFLICT (lower(title), release_year)` must agree.

V1 implements that as a **partial unique index**:

```sql
CREATE UNIQUE INDEX uq_movies_title_year
    ON movies (lower(title), release_year)
    WHERE title IS NOT NULL AND release_year IS NOT NULL;
```

No separate `natural_key` column. Remakes with different years survive
(*The Mummy* 1999 vs 2002).

**Untitled row — resolved.** The live Vega file has one row with a null title
(`Release_Date` = 2006-11-03). `title` is **nullable** so the schema does not
reject it, but Postgres unique indexes do not collide on NULL, so that row has
no natural key and would re-insert on every run. This report previously left
the choice — drop, or synthesise a title — open for 1.5.

**The loader skips it and counts it** (`rows_skipped_no_key` in the load
report, with examples). A synthetic `"(untitled)"` was rejected: it would be
returned to API clients and embedded into the Atlas map as though it were a
real title, trading a visible one-row gap for an invisible fabrication. One
unsearchable row out of 3,201 is the cheaper failure, and the count makes it
auditable. The partial `WHERE` keeps the hole explicit in the schema rather
than hiding it.

**1.5 upsert shape** (as implemented in `pipeline/src/pipeline/loader.py`):

```sql
INSERT INTO movies (...)
VALUES (...)
ON CONFLICT (lower(title), release_year)
    WHERE title IS NOT NULL AND release_year IS NOT NULL
DO UPDATE SET ... , updated_at = NOW();
```

The `ON CONFLICT` target must match `uq_movies_title_year` exactly or Postgres
cannot infer the index and the upsert silently becomes an insert;
`pipeline/tests/test_loader.py` asserts the two agree.

---

## Column map

| Column | Source | Why it is here |
| ------ | ------ | -------------- |
| `id` | generated UUID | Public identity for MCP `get_similar_movies` / API `GET /movies/{id}` |
| `title` | 1.1 | Search + unique key; nullable for the untitled row |
| `release_date`, `release_year` | 1.1 Point 3 | Year is the unique-key half and the decade input |
| `major_genre`, `mpaa_rating`, `director`, `distributor`, `creative_type`, `source` | 1.1 | MCP filters + NL queries + Atlas colour-by-genre |
| `imdb_rating`, `imdb_votes`, `rt_rating`, `production_budget`, `us_gross`, `worldwide_gross`, `running_time_min` | 1.1 Point 4 | Filters, stats, "small budget" / RT queries |
| `budget_tier`, `decade`, `rating_score_delta`, `blockbuster_flag` | 1.3 (empty until then) | MCP `decade` filter + derived-feature brief |
| `*_imputed` booleans | 1.2 (empty until then) | Provenance so search never treats filled values as observed |
| `augmented_text`, `embedding vector(768)` | 1.4 / 1.5 | Embedding payload; 768 = `nomic-embed-text` |
| `pipeline_version`, `created_at`, `updated_at` | audit | Brief requirement; trigger stamps `updated_at` |

**Omitted:** `us_dvd_sales`. 1.1 cleans it, but it is too sparse for search and
is not in the augmented-text template.

`embedding` and `augmented_text` stay nullable until the loader writes them.
The HNSW index is partial `WHERE embedding IS NOT NULL` for the same reason.

---

## Indexes (V2)

- **HNSW cosine** on `embedding` (`vector_cosine_ops`), partial. ~3,200 rows;
  default `m` / `ef_construction` are enough. The planner may seq-scan + sort
  at this size; the index still matches the brief and will matter if the corpus
  grows.
- **Btrees** on `major_genre`, `decade`, `imdb_rating`, `mpaa_rating` — the
  hybrid filters on `search_movies_by_description` / `GET /api/v1/movies/search`.
- **GIN trigram** on `title` for `get_movie_by_title` fuzzy match (`%` /
  `similarity()`). Requires `pg_trgm` (created in V1).

---

## Hybrid query

Documented at `database/queries/hybrid_search.sql`. Vector cosine distance
(`<=>`) plus optional genre / decade / min IMDB / MPAA filters. Similarity is
returned as `1 - distance`, tagged `match_type = 'semantic'` so callers can
tell it apart from the trigram score `title_fuzzy.sql` returns on the same
field (see `reports/section-3.md`).

Example: *"action movies from the 90s with high IMDB ratings"* binds
`$2 = 'Action'`, `$3 = 1990`, `$4 = 7.5`, `$5` null.

Part 3 binds `$1` as the `search_query:` embedding from Ollama. That prefix is
an MCP concern, not schema.

### Testing

`pipeline/tests/test_hybrid_search_query.py` pins the SQL text and the V1/V2
contract. Text assertions cannot catch a query Postgres would reject, so
`mcp-server/tests/test_sql_execution.py` applies these migrations to a
throwaway database and executes every query for real:

```bash
MCP_TEST_DSN=postgresql://movies:change_me_local_only@localhost:5432/movies pytest
```

It skips without that variable and has not been run here — no Docker daemon on
this machine — so the migrations remain applied-by-Flyway-in-Compose only.

---

## Follow-ups (not Part 2)

- **Part 3** uses `hybrid_search.sql` and registers an asyncpg `vector` codec.
- **Part 6** runs the same Flyway SQL against RDS (pgvector + pg_trgm allowed).
- CI has no Postgres service, so `MCP_TEST_DSN` / `PIPELINE_TEST_DSN` tests
  never run there. Adding a `services: postgres` block to the Python job would
  turn both suites on.
