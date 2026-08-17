# Intelligent Movie Search Platform

An end-to-end semantic movie search system: a Python data pipeline vectorizes the
Vega movies dataset into pgvector, a FastMCP server exposes semantic search tools,
and a .NET 10 Web API serves secured, observable endpoints to clients. The whole
platform runs locally via Docker Compose and deploys to AWS ECS Fargate via Terraform.

---

## 0. Status

The brief invites partial submissions provided the gaps are documented. This
section is that documentation; every `⚠️` below is repeated in context in the
section it affects, and collected in [§14](#14-known-limitations--future-improvements).
Two indexes sit after it: [§15](#15-design-decisions--trade-offs) is every
deliberate choice with the alternative it beat and what it costs, and
[§16](#16-requirements-coverage) maps each requirement in the brief to where it is
answered.

| Part | Area | State |
| ---- | ---- | ----- |
| 1 | Data pipeline (clean → impute → augment → embed → load) | Complete, run end to end against live Ollama + Postgres |
| 2 | pgvector schema, Flyway migrations, hybrid query | Complete |
| 3 | FastMCP server, 6 tools | Complete |
| 4 | .NET 10 Web API | Complete |
| 5 | Embedding Atlas (bonus) | Complete, opens already coloured by Major Genre |
| 6 | Docker Compose, Terraform, CI/CD | Compose and CI/CD complete and verified; dev applied to a real AWS account and serving, seed pipeline not yet run there ⚠️ |
| — | Walkthrough video | Not recorded ⚠️ |

**What is verified, by observation.** The platform has been brought up from an
empty Docker state (`docker compose down -v` then `docker compose up --build`) and
exercised the length of the chain. Each part's report under `reports/` carries its
own evidence, including the bugs the first end-to-end run exposed and why the test
suites could not see them — indexed in
[§16](#16-requirements-coverage).

- All ten services reach healthy; `migrate` and `pipeline` exit 0.
- Stages 1.4 and 1.5 run for real: 3,201 augmented texts embedded through the
  containerized Ollama at 768 dimensions, 3,200 rows upserted into pgvector, 1
  row skipped (the untitled 2006 record). Re-running leaves the table at 3,200,
  so idempotency holds in practice and not just in unit tests.
- The five natural-language queries from the brief all return relevant results
  through the .NET API, and hybrid filters (`genre`, `min_imdb_rating`,
  `decade`) constrain correctly. `scripts/e2e_test.sh` asserts all of this.
- Trace context propagates: a single Jaeger trace spans
  `GET /api/v1/movies/search` → `mcp.search_movies_by_description` → the MCP
  server, and the MCP server's JSON logs carry the same `trace_id`.
- Rate limiting enforces 60 requests/minute per client (57 × 200, 8 × 429 over
  65 rapid calls). Prometheus scrapes the API; the Grafana dashboard provisions.
- `dotnet test` passes (22 tests) and `dotnet format --verify-no-changes` is
  clean. Five further tests run only against a live MCP server
  (`MCP_INTEGRATION_URL`) and pass: they exercise the real SSE client for all six
  tools, which is what the rest of the .NET suite cannot do because it
  substitutes a fake.
- OpenAPI: the served document carries examples on every model, parameter and
  200 response, and the committed root `openapi.json` is generated from it by
  `scripts/export_openapi.sh`, with a test asserting the two match.
- X-Ray trace-id generation and `X-Amzn-Trace-Id` propagation verified locally
  with `AWS_XRAY_ENABLED=true` — see [§11](#11-observability).
- Atlas opens with points already coloured by `major_genre`, data table intact,
  confirmed in a browser against the shipped image.
- `terraform plan` for dev against a real AWS account: **143 to add, 0 to change,
  0 to destroy**, no errors or warnings — the Terraform artefact the brief asks to
  see.
- That plan was then **applied**, in `eu-west-1` on 2026-08-17: 143 resources
  created, exactly the count the plan predicted. State landed in S3 with DynamoDB
  locking, so the backend is genuinely exercised rather than inferred. All three
  long-lived ECS services (`api` 2/2, `mcp-server` 1/1, `embeddings` 1/1) report
  `COMPLETED` rollouts, the ALB answers `GET /health` with 200, and the Flyway
  `migrate` task exits 0 against the live RDS instance. Getting `mcp-server` there
  took a forced redeployment around a real Terraform dependency bug, recorded in
  [§14](#14-known-limitations--future-improvements).
- p95 on search is **17ms** at the default 60/minute limit and **608µs** over
  4,795 requests at 80 req/s with the limit raised — against a 500ms target.
- `ruff`, `mypy` and `pytest` are green: 66 passed in `pipeline` and 64 in
  `mcp-server` with `PIPELINE_TEST_DSN`/`MCP_TEST_DSN` pointed at a throwaway
  pgvector container (62 + 4 skipped and 58 + 6 skipped without one). CI now
  provides that container, so all ten database-backed tests run there too.

**What is still not verified.** The deployment stops short of proving data flows
on AWS. The `pipeline` task has not been run against the deployed database, so
that database is migrated but **empty**, and `scripts/smoke_test.sh` and
`scripts/e2e_test.sh` have not been run against the ALB — meaning the search path
is proven only under Compose, not on Fargate. X-Ray has still never been seen in
X-Ray, since generating traces needs that same traffic. There is no cost figure
yet, only a rough estimate. Prod has never been applied. One thing to know before
reading §12 that the apply confirmed rather than changed: the ALB serves a single
plain-HTTP listener on port 80, because HTTPS needs a certificate and there is no
domain to get one for.

---

## 1. Architecture Diagram

```
                       LOCAL  (docker compose up --build)
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│   vega_datasets                                                              │
│   data.movies()                                                              │
│        │  3,201 rows                                                         │
│        ▼                                                                     │
│  ┌──────────────────┐        embed        ┌────────────────────────────┐     │
│  │  pipeline        │────────────────────▶│  embeddings        :8001   │     │
│  │  Python 3.12     │◀────────────────────│  Ollama · nomic-embed-text │     │
│  │  1.1 clean       │   768-dim vectors   │  (own container, no        │     │
│  │  1.2 impute      │                     │   in-process download)     │     │
│  │  1.3 augment     │                     └────────────────────────────┘     │
│  │  1.4 embed       │                                                        │
│  │  1.5 load        │  upsert on (lower(title), release_year)                │
│  └────────┬─────────┘                                                        │
│           │                     ┌──────────────────┐                         │
│           ▼                     │  migrate         │  Flyway V1 schema       │
│  ┌─────────────────────────┐    │  (runs, exits)   │  V2 indexes             │
│  │  postgres        :5432  │◀───┴──────────────────┘                         │
│  │  PostgreSQL 16          │                                                 │
│  │  + pgvector (HNSW)      │──────────────┐                                  │
│  │  + pg_trgm (fuzzy)      │              │ read-only                        │
│  └───────────┬─────────────┘              ▼                                  │
│              │ asyncpg pool   ┌────────────────────────────┐                 │
│              ▼                │  atlas             :7000   │                 │
│  ┌─────────────────────────┐  │  Embedding Atlas (bonus)   │                 │
│  │  mcp-server      :8000  │  │  Parquet export → UMAP     │                 │
│  │  FastMCP over SSE       │  └────────────────────────────┘                 │
│  │  6 MCP tools            │                                                 │
│  └───────────┬─────────────┘                                                 │
│              │ MCP over SSE (traceparent propagated)                         │
│              ▼                                                               │
│  ┌─────────────────────────┐                                                 │
│  │  api             :8080  │  JWT · RBAC · cache · rate limit                │
│  │  .NET 10 Minimal APIs   │  OpenAPI 3.1 + Swagger UI                       │
│  └───────────┬─────────────┘                                                 │
│              │                                                               │
│              ▼  client (curl / Swagger UI)                                   │
│                                                                              │
│  Observability spans every service:                                          │
│    jaeger :16686  ◀── OTLP gRPC :4317 ── traces                              │
│    prometheus :9090 ── scrapes api:8080/metrics ──▶ grafana :3000            │
└──────────────────────────────────────────────────────────────────────────────┘

                       AWS  (terraform apply · ECS Fargate)
┌──────────────────────────────────────────────────────────────────────────────┐
│  Route53 ─▶ ACM ─▶ ALB (:443, HTTP→HTTPS redirect)   [public subnets]        │
│                      │                                                       │
│                      ▼                                                       │
│  ECS Fargate cluster                                  [private subnets]      │
│    api ──▶ mcp-server ──▶ embeddings                                         │
│    pipeline / migrate  (run-to-completion tasks)                             │
│                      │                                                       │
│                      ▼                                                       │
│  RDS PostgreSQL 16 + pgvector  (private only, encrypted)                     │
│                                                                              │
│  Secrets Manager · IAM task roles · ECR · CloudWatch + X-Ray · VPC Flow Logs │
│  State: S3 (versioned, encrypted) + DynamoDB lock table                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Prerequisites

Only Docker is required to run the platform. Everything else is needed solely to
develop or test outside containers.

| Tool | Version | Required for |
| ---- | ------- | ------------ |
| Docker Engine | 24+ (developed on 29.5.3) | everything |
| Docker Compose | v2 (`docker compose`, not `docker-compose`) | everything |
| Python | 3.12 (`requires-python = ">=3.12"`) | running `pipeline` / `mcp-server` outside Docker |
| uv | 0.5+ | `uv sync --all-packages --dev`, the workspace resolver CI uses |
| .NET SDK | 10.0.x | `dotnet test`, `dotnet format` |
| Terraform | >= 1.9 (CI pins 1.9.8) | Part 6 |
| AWS CLI | v2 | Part 6 deployment and the ECS run-task steps |
| k6 | 0.50+ | `scripts/load_test.js` |

Pinned container images (all from `docker-compose.yml`, so no local install is
needed):

| Image | Version | Notes |
| ----- | ------- | ----- |
| `pgvector/pgvector` | `pg16` | PostgreSQL 16; the tag tracks current pgvector, satisfying the brief's 0.7+ |
| `ollama/ollama` | `0.6.8` | serves `nomic-embed-text`, 768 dimensions |
| `flyway/flyway` | `10.22.0` | migrations |
| `prom/prometheus` | `v3.1.0` | metrics |
| `grafana/grafana` | `11.5.1` | dashboards |
| `jaegertracing/all-in-one` | `1.65.0` | tracing |
| `mcr.microsoft.com/dotnet/{sdk,aspnet}` | `10.0` | API build and runtime |
| `python` | `3.12-slim` | pipeline, MCP server, Atlas |

Resource footprint: the Ollama container pulls `nomic-embed-text` (~275 MB) on
first start into a named volume, so the first `up` is slower than later ones.
Budget roughly 8 GB RAM and 10 GB disk for the full stack.

## 3. Quick Start (≤5 commands)

```bash
git clone <repo-url> && cd movie-search-platform
cp .env.example .env
docker compose up --build          # brings up every service; `pipeline` runs and exits
# open http://localhost:8080/swagger
```

`pipeline` is an ordinary Compose service, so `up` already ingests, embeds and
loads the dataset once `postgres`, `migrate` and `embeddings` are healthy. It is
idempotent, so a later `up` re-runs it as a no-op upsert. To re-run it on demand
without restarting the stack:

```bash
docker compose run --rm pipeline
```

Verified from an empty Docker state: all ten services reach healthy, `migrate`
and `pipeline` exit 0, and the dataset lands in pgvector — see [§0](#0-status).
Run `./scripts/e2e_test.sh` afterwards to assert the whole chain.

## 4. Service Endpoints

| Service | URL | Port |
| ------- | --- | ---- |
| .NET API | http://localhost:8080 | 8080 |
| Swagger UI | http://localhost:8080/swagger | 8080 |
| OpenAPI 3.1 | http://localhost:8080/openapi/v1.json | 8080 |
| Prometheus metrics (API) | http://localhost:8080/metrics | 8080 |
| MCP server | http://localhost:8000 (SSE at `/sse`, health at `/health`) | 8000 |
| Embeddings (Ollama) | http://localhost:8001 | 8001 |
| Postgres | `postgresql://movies:***@localhost:5432/movies` | 5432 |
| Prometheus | http://localhost:9090 | 9090 |
| Grafana | http://localhost:3000 (admin/admin from `.env`) | 3000 |
| Jaeger | http://localhost:16686 | 16686 |
| Embedding Atlas | http://localhost:7000 | 7000 |

`migrate` (Flyway) and `pipeline` are run-to-completion jobs and expose no port.

**Health checks and ordering.** Every long-lived service has a health check, and
every `depends_on` names an explicit condition — `service_healthy` for the eight
that hold a healthy state, `service_completed_successfully` for the two jobs that
do not (a run-to-completion container is never "healthy", it exits). The probes
are specific rather than a port ping: `embeddings` greps `ollama list` so it is
healthy only once the model is resident, and Jaeger is probed on its admin port
14269 because 16686 serves the UI. Three of them use busybox `wget --spider`,
since those images ship no `curl`.

### Embedding Atlas (bonus)

`http://localhost:7000` is Apple Embedding Atlas over the Part 2 `movies`
vectors. The service runs
[`scripts/export_embeddings_atlas.py`](scripts/export_embeddings_atlas.py) — the
path the brief specifies — which polls until 1.5 has written embeddings, dumps
Parquet from `database/queries/atlas_export.sql`, and hands it to Atlas, which
projects with UMAP (cosine, seed 42). Decisions:
[`reports/section-5.md`](reports/section-5.md).

The same script runs standalone against a populated database:

```bash
python scripts/export_embeddings_atlas.py --output atlas_export/movies.parquet
```

**Colour by genre:** already applied on load — no clicking. Atlas has no `--color`
flag and the CLI serves its props verbatim, so `scripts/atlas/atlas_color_by.py`
injects `defaultChartsConfig.embedding.data.category` in-process, loaded via
`--with`. `ATLAS_COLOR_BY` picks the column and an empty value restores stock
behaviour (Color by Field → `major_genre` by hand). Why it works this way, and why
`initialState.charts` would have hidden the data table:
[`reports/section-5.md`](reports/section-5.md#why-this-needed-a-patch).

**How to read it:** same-colour blobs are genres that cluster in embedding space
(Action vs Drama). Mixed neighbourhoods are genre-ambiguous plots or thin
augmented text. Isolated points are outliers — titles whose nearest neighbours
are not their billed genre. Cross-check with MCP `get_similar_movies`.

## 5. Data Pipeline

Five stages, each its own module under `pipeline/src/pipeline/`, chained by
`pipeline/src/main.py`. Full narrative with per-decision rationale:
[`reports/section-1.md`](reports/section-1.md). The brief's README outline has no
section of its own for Part 2, so the schema the pipeline writes into — including
the Flyway justification and the documented hybrid query — is
[the last subsection here](#vector-database-part-2).

| Stage | Module | What it does |
| ----- | ------ | ------------ |
| 1.1 Cleaning | `cleaning.py` | Rename to snake_case → standardize strings → parse dates → de-duplicate → validate numeric ranges |
| 1.2 Imputation | `imputation.py` | Group-median for numerics (flagged), `"Unknown"` sentinel for descriptive categoricals, NULL for facets |
| 1.3 Augmentation | `augmentation.py` | Renders `augmented_text` from observed facts only; adds 4 derived features |
| 1.4 Embedding | `embedding.py` | Batched HTTP calls to the `embeddings` container; per-vector dimension check |
| 1.5 Load | `loader.py` | Chunked `executemany` upsert into `movies`, in one transaction |

### How to run

```bash
docker compose run --rm pipeline              # full run: needs postgres, migrate, embeddings
docker compose run --rm --no-deps pipeline --dry-run   # 1.1–1.3 only, no DB, no model server
```

`--dry-run` is the fast feedback loop while iterating on transforms: it prints
the same 1.1–1.3 summaries and writes the same report artifacts, but skips the
embedding and database stages.

### Idempotency

Re-running never duplicates. The loader upserts on the partial unique index V1
declares — `(lower(title), release_year) WHERE title IS NOT NULL AND
release_year IS NOT NULL` — which is the same natural key 1.1 de-duplicates on.
Updates are stamped by the V1 `updated_at` trigger.

One row of 3,201 (the untitled 2006-11-03 record) has no natural key. Postgres
does not collide NULLs, so that row would be re-inserted on every run; it is
therefore **skipped and counted** in the load report rather than given a
synthetic title that would be served to clients as though it were real.

### How to verify

```bash
# 1. Stage summaries on stdout, plus the required log file
docker compose run --rm pipeline
cat reports/pipeline.log

# 2. Machine-readable per-stage report
jq '.cleaning, .imputation, .augmentation, .embedding, .load' reports/section-1-pipeline.json

# 3. Rows and vectors actually landed
docker compose exec postgres psql -U movies -d movies -c \
  "SELECT count(*) AS rows,
          count(embedding) AS embedded,
          vector_dims(embedding) AS dims
   FROM movies GROUP BY 3;"

# 4. Idempotency: the count must not change
docker compose run --rm pipeline
docker compose exec postgres psql -U movies -d movies -c "SELECT count(*) FROM movies;"
```

Artifacts written to `reports/` on every run: `pipeline.log` (full run log),
`section-1-pipeline.json` (every stage report), `section-1-cleaning.json` (the
1.1 cleaning report on its own).

### Observed results (full run, 1.1–1.5)

**1.1 Cleaning.** 3,201 rows in, 3,201 out. 0 duplicates dropped (the 24 repeated
titles are remakes with distinct years, which the `(title, year)` key preserves).
9 titles arrived as JSON integers (`300`, `2012`, `1776`) and were stringified;
11 titles normalized in total. 22 pre-1950 classics were stored with two-digit
years expanded into 2015–2046 and were century-corrected back to 1915–1946. 66
`us_gross` and 47 `worldwide_gross` placeholder zeros were nulled rather than
treated as real $0. No value fell outside a sensible numeric range.

**1.2 Imputation.** 1,992 `running_time_min`, 880 `rt_rating`, 213 `imdb_rating`
and 1 `production_budget` filled by group median (global median as fallback);
1,331 `director`, 605 `mpaa_rating`, 446 `creative_type`, 365 `source` and 232
`distributor` filled with the `Unknown` sentinel. `major_genre` is left NULL.

**1.3 Augmentation.** 3,201 rows carry `augmented_text` (mean 10.02 lines), none
empty. Budget tiers: 1,305 indie, 1,197 mid, 527 major, 171 blockbuster.

**1.4 Embedding.** 3,201 vectors of dimension 768 from `nomic-embed-text` over
HTTP to the `embeddings` container, in batches of 32 — roughly 80 seconds.

**1.5 Load.** 3,200 rows upserted; 1 skipped (the untitled 2006 record, which has
no natural key). A second run reports the same 3,200 total, confirming the
`ON CONFLICT (lower(title), release_year)` upsert is idempotent in practice.

### Vector database (Part 2)

PostgreSQL 16 with pgvector is both the structured store and the vector store —
one table, no separate vector service. The schema is
`database/migrations/V1__initial_schema.sql`, the indexes are `V2__indexes.sql`,
and the Flyway `migrate` job applies both. Full reasoning:
[`reports/section-2.md`](reports/section-2.md).

`movies` extends the brief's minimum schema rather than restating it:

| Group | Columns | Why |
| ----- | ------- | --- |
| Identity | `id UUID PRIMARY KEY` | Public identity for `GET /movies/{id}` and `get_similar_movies` |
| Core metadata | `title`, `release_date`, `release_year`, `major_genre`, `mpaa_rating`, `director`, `distributor`, `creative_type`, `source` | Filters, natural-language queries, Atlas colour-by-genre. `title` is nullable for the one untitled row |
| Numerics | `imdb_rating`, `imdb_votes`, `rt_rating`, `production_budget`, `us_gross`, `worldwide_gross`, `running_time_min` | Hybrid filters, `/stats`, the "small budget" and Rotten Tomatoes queries |
| Derived (1.3) | `budget_tier`, `decade`, `rating_score_delta`, `blockbuster_flag` | The `decade` filter binds directly to a column; the rest feed Atlas facets |
| Provenance (1.2) | `imdb_rating_imputed`, `rt_rating_imputed`, `production_budget_imputed`, `running_time_min_imputed` | Beyond the brief: search never has to treat a filled value as observed |
| Search payload | `augmented_text`, `embedding vector(768)` | 768 matches `nomic-embed-text`; both stay nullable until the loader writes them |
| Audit | `pipeline_version`, `created_at`, `updated_at` | The brief's three audit columns; a V1 trigger stamps `updated_at` on every update |

`us_dvd_sales` is cleaned by 1.1 but not stored — too sparse to help search and
absent from the text template.

Uniqueness is a **partial** unique index, which is what makes the loader
idempotent and keeps remakes:

```sql
CREATE UNIQUE INDEX uq_movies_title_year
    ON movies (lower(title), release_year)
    WHERE title IS NOT NULL AND release_year IS NOT NULL;
```

The loader's `ON CONFLICT` target restates that predicate exactly — otherwise
Postgres cannot infer the index and every upsert silently becomes an insert.
`pipeline/tests/test_loader.py` asserts the two agree.

#### Flyway, not Alembic

The brief allows either. Flyway, for three reasons:

- The stack is polyglot. SQL-first DDL is the one language the Python pipeline,
  the Python MCP server and the .NET API all share; Alembic would tie the
  schema to a Python service that the API does not depend on.
- pgvector types, HNSW operator classes and partial indexes read far more
  clearly as raw SQL than as SQLAlchemy operations.
- The same files apply locally and on RDS. `CREATE EXTENSION IF NOT EXISTS
  vector` / `pg_trgm` are both RDS-safe for `rds_superuser`, so Part 6 needed no
  separate migration path — only a way to *run* Flyway inside the VPC, which is
  what `database/Dockerfile` is for.

The cost is that Flyway versions are forward-only, so local schema edits mean
resetting the volume:

```bash
docker compose down -v && docker compose up --build
```

There is no seed script, deliberately: the brief specifies that the seed **is**
the pipeline (1.5 `loader.py`).

#### Indexes (V2)

| Index | Serves |
| ----- | ------ |
| HNSW `vector_cosine_ops` on `embedding`, partial `WHERE embedding IS NOT NULL` | Semantic kNN. Defaults for `m` / `ef_construction`; at 3,200 rows the planner may still sequential-scan, and the index is what makes growth cheap |
| B-trees on `major_genre`, `decade`, `imdb_rating`, `mpaa_rating` | The four hybrid filters |
| GIN trigram on `title` (`pg_trgm`) | `get_movie_by_title`'s fuzzy fallback |

#### Hybrid query: vector similarity + metadata filters

The documented query the brief asks for is
[`database/queries/hybrid_search.sql`](database/queries/hybrid_search.sql) — not
applied by Flyway, and the same text Part 3 executes (`test_sql_sync.py` fails if
the copy baked into the MCP image drifts):

```sql
SELECT id, title, release_year, major_genre, mpaa_rating, director, distributor,
       imdb_rating, rt_rating,
       1 - (embedding <=> $1::vector) AS similarity,
       'semantic'::text AS match_type
FROM movies
WHERE embedding IS NOT NULL
  AND ($2::text    IS NULL OR major_genre = $2)
  AND ($3::int     IS NULL OR decade      = $3)
  AND ($4::numeric IS NULL OR imdb_rating >= $4)
  AND ($5::text    IS NULL OR mpaa_rating = $5)
ORDER BY embedding <=> $1::vector
LIMIT $6;
```

Every filter is `NULL`-guarded, so one prepared statement covers all sixteen
filter combinations instead of assembling SQL per request. `<=>` is cosine
*distance*, which is what the HNSW `vector_cosine_ops` index is built for;
similarity is reported as `1 - distance` so callers see a higher-is-better score
in `[0, 1]`, tagged `match_type = 'semantic'` so it is never confused with the
trigram score a fuzzy title match returns on the same field.

*"action movies from the 90s with high IMDB ratings"* binds `$1` to the
`search_query:`-prefixed embedding, `$2 = 'Action'`, `$3 = 1990`, `$4 = 7.5`,
`$5 = NULL`, `$6 = 10`. Run it by hand:

```bash
docker compose exec postgres psql -U movies -d movies -c \
  "SELECT title, release_year, major_genre, imdb_rating
   FROM movies
   WHERE embedding IS NOT NULL AND major_genre = 'Action' AND decade = 1990
     AND imdb_rating >= 7.5
   ORDER BY embedding <=> (SELECT embedding FROM movies WHERE title = 'The Matrix')
   LIMIT 5;"
```

That substitutes a stored vector for a live query embedding, which is the one
part of the path `psql` cannot do on its own. `mcp-server/tests/test_sql_execution.py`
executes the real query against pgvector with `MCP_TEST_DSN` set.

## 6. Data Decisions

Full reasoning: [`reports/section-1.md`](reports/section-1.md). The governing
principle across both cleaning and imputation is **flag rather than silently
mutate** — cleaning fixes structure and unambiguous errors, and anything
uncertain is left to imputation and counted. Ratings, budgets, genres and years
are never invented.

### Cleaning

| Decision | Rationale |
| -------- | --------- |
| De-duplicate on `(normalized title, release_year)`, not title alone | Remakes must survive (*The Mummy* 1999 vs 2002). The key also has to match the loader's `ON CONFLICT` target or re-runs stop being idempotent. |
| Keep the **most complete** row in a duplicate group, tie-broken by `imdb_votes` | Preserves the most search signal; deterministic given a stable input order. |
| Rows without a usable key are kept and counted, never auto-dropped | Dropping data to satisfy a key is a silent loss. The loader makes the same row's fate explicit instead. |
| Out-of-range numerics are **nulled, not clamped** | A clamped value is indistinguishable from a measured one. Null is honest and 1.2 can fill it with provenance. |
| Zero money treated as missing | In this file, unknown box office is encoded as `0` (*12 Angry Men*, *1776*). Counted separately from "out of range" so the two are not conflated. |
| No blind `.title()` on genres or distributors | It corrupts `20th Century Fox` → `20Th Century Fox` and `Based on Book/Short Story` → `Based On Book/Short Story`. The file is already consistently capitalised. |
| Century correction cut off at **2011**, not "> current year" | A `year > today` rule (2026) would miss *Ben-Hur* (stored 2025 → 1925) and 21 similar pre-1950 titles. Every title stored as 2015–2046 is a known 1915–1946 film; the newest genuine titles are 2011. This constant is dataset-specific to the frozen Vega file and must be revisited if the source is replaced. |

### Imputation

Strategy is chosen by the field's **role**, not its dtype.

| Field | Missing | Strategy | Why |
| ----- | ------: | -------- | --- |
| `imdb_rating` | 213 | median by `major_genre`, else global (6.4) | Genre is the strongest available conditioner; a Horror rating is a better guess than a dataset-wide one. |
| `rt_rating` | 880 | median by `major_genre`, else global (55) | Same. |
| `running_time_min` | 1,992 | median by `major_genre`, else global (107) | Same; runtime varies far more by genre than at random. |
| `production_budget` | 1 | median by `decade`, else global | Nominal budgets inflate over time, so decade beats genre here. |
| `mpaa_rating` | 605 | `"Unknown"` sentinel | Descriptive, not inferable. |
| `director` | 1,331 | `"Unknown"` sentinel | Mode-imputation would attribute 1,331 films to one person — and the brief's own example query is *"sci-fi films directed by James Cameron"*. A wrong fact is worse than an absent one. |
| `distributor` | 232 | `"Unknown"` sentinel | Same. |
| `creative_type` | 446 | `"Unknown"` sentinel | Same. |
| `source` | 365 | `"Unknown"` sentinel | Same. |
| `major_genre` | — | **left NULL** | It is a facet: `list_genres` advertises it and `genre_filter` matches on it, so `"Unknown"` would become a browsable category and a selectable filter value. |

Three supporting decisions:

- **Group median with a floor.** A group median computed from fewer than 10
  observations is noise, so those rows fall back to the global median. The split
  is reported per field: of 1,992 runtime fills, 1,653 used a genre median and
  339 the global one. `genre × decade` was measured and rejected — 28 of its 75
  cells hold fewer than 5 rows.
- **Provenance, not just values.** Every filled numeric cell sets a
  `<column>_imputed` boolean, which V1 reserves as a real column. Downstream
  consumers can tell an observed 6.4 from a filled one.
- **Imputation fills columns, not the embedding input.** 1.3 renders only
  observed facts, so a filled runtime never reaches the embedding model. See
  [§7](#7-embedding-strategy).

## 7. Embedding Strategy

### Model choice

**`nomic-embed-text` v1.5, served by Ollama, 768 dimensions.**

| Criterion | Reasoning |
| --------- | --------- |
| Open and locally-runnable | Brief forbids paid/hosted APIs. Nomic Embed is Apache-2.0 and the brief names it as the suggested option. |
| Dimensionality | 768 matches the brief's example `vector(768)` exactly, so the schema needs no adjustment and the HNSW index stays at a size where cosine search on ~3.2k rows is trivial. |
| Retrieval quality | Nomic Embed outperforms `text-embedding-ada-002` on MTEB short- and long-context retrieval, which is the task here. |
| Context window | 8,192 tokens — far beyond the ~10-line augmented text, so no truncation strategy is needed. |
| Serving | Ollama gives a single pinned image with a batch endpoint and a model cache, rather than assembling a sentence-transformers container by hand. |

### Container wiring

The model runs as **its own Compose service**; neither the pipeline nor the MCP
server downloads a model in-process.

```yaml
embeddings:
  image: ollama/ollama:0.6.8
  command: ollama serve & … ollama pull ${EMBEDDING_MODEL} … wait
  ports: ["8001:11434"]          # host 8001 → container 11434, per the brief's table
  volumes: [ollama:/root/.ollama]  # model cached across restarts
  healthcheck:
    test: ollama list | grep -q ${EMBEDDING_MODEL}   # healthy only once pulled
```

The healthcheck greps `ollama list` rather than pinging the HTTP port, so the
service is healthy only when the model is actually resident. `pipeline` and
`mcp-server` both declare `depends_on: embeddings: condition: service_healthy`
and reach it at `EMBEDDING_BASE_URL=http://embeddings:11434`. Every knob is
environment-driven (`EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_BATCH_SIZE`).

### Text construction

`augmented_text` follows the brief's 12-line template, with one deliberate
departure: **a line is omitted when its value was not observed** — missing,
`"Unknown"`, or flagged by a `<column>_imputed` boolean. Two alternatives were
rejected:

- *Rendering the filled value.* `Runtime: 107 minutes` on the 62% of rows whose
  runtime was never recorded embeds a fact the dataset does not support.
- *Rendering `Runtime: Unknown`.* That string is byte-identical across every
  affected row, so it pulls unrelated films together in vector space purely
  because they share a gap. Silence carries no such signal.

Observed coverage: 3,201 of 3,201 rows produce non-empty text, averaging 10.02
of the 12 possible lines.

A fully-observed row (the fixture asserted in `pipeline/tests/test_augmentation.py`):

```
Title: Titanic
Genre: Drama
Director: James Cameron
MPAA Rating: PG-13
Release Year: 1997
Runtime: 194 minutes
IMDB Rating: 7.4/10 (240,732 votes)
Rotten Tomatoes: 82%
Budget: $200,000,000
Distributor: Paramount Pictures
Creative Type: Historical Fiction
Source: Original Screenplay
```

### Derived features

Four, against the brief's minimum of two.

| Feature | Coverage | Rationale |
| ------- | -------: | --------- |
| `decade` | 3,201 | The MCP `decade` filter binds directly to it. It is what turns "movies from the 90s" into a SQL predicate instead of a hope. |
| `budget_tier` | 3,200 | Maps a dollar amount onto the vocabulary users search with. Fixed industry thresholds (<$15M indie, <$50M mid, <$100M major, else blockbuster) rather than sample quartiles, so a "$15M indie" means the same thing if the corpus changes. Observed: 1,305 / 1,197 / 527 / 171. |
| `rating_score_delta` | 2,260 | IMDB rescaled to 0–100 minus Rotten Tomatoes. Positive means audiences liked it more than critics did — it separates "critically acclaimed" from "crowd-pleaser", which neither rating does alone. |
| `blockbuster_flag` | 3,147 | Commercial outcome, which budget alone misses. Requires clearing $100M worldwide *and* doubling its budget, so a $200M film that cost $250M is not flagged. |

Derived features are computed from **observed** inputs only and are NULL
otherwise, for the same reason the text omits filled lines: they feed Atlas
facets and API responses, where a guess would be indistinguishable from a
measurement.

### Asymmetric prefixes

Nomic Embed is an asymmetric model and expects a task prefix. Stored documents
use `search_document: ` (`pipeline/src/pipeline/embedding.py`); the MCP server
prefixes user queries with `search_query: `. Mixing the two silently degrades
retrieval rather than failing, so each side asserts its own prefix.

### Batching and failure handling

Batches of `EMBEDDING_BATCH_SIZE` (default 32) are POSTed to `/api/embed`, with
a one-time fallback to the legacy per-text `/api/embeddings` if the server
returns 404. Transport errors and HTTP failures retry 4 times with exponential
backoff (tenacity). Progress is logged per batch. Every returned vector is
length-checked against `EMBEDDING_DIM`, and a batch that still fails **raises
rather than yielding a short vector** — a partial load would leave the corpus
quietly incomplete, which is much harder to notice than a failed run.

## 8. MCP Server

FastMCP on port 8000 (SSE by default). Six tools; optional hybrid filters are
parsed from the query when the caller omits them. Full decisions:
[`reports/section-3.md`](reports/section-3.md).

| Tool | What it does | `match_type` |
| ---- | ------------ | ------------ |
| `search_movies_by_description` | Semantic search + genre / decade / min IMDB / MPAA | `semantic` |
| `get_movie_by_title` | Exact then trigram fuzzy match | `exact` / `fuzzy` |
| `get_movie_by_id` | Direct lookup by UUID | `lookup` |
| `get_similar_movies` | Nearest neighbours of a movie UUID | `semantic` |
| `list_genres` | Distinct `major_genre` values | — |
| `get_dataset_stats` | Counts, year range, average IMDB | — |

Every result carries `similarity` **and** `match_type`. They travel together
because the score means different things per tool: cosine similarity for
`semantic`, trigram similarity for `fuzzy`, `1.0` for `exact`, and `null` for a
direct `lookup`. Without `match_type`, a 0.42 is unreadable.

Arguments are validated by Pydantic v2 models (`mcp-server/src/server/models.py`);
`top_k` is clamped to `MCP_TOP_K_MAX` rather than rejected.

### Server requirements (3.2)

| Requirement | How |
| ----------- | --- |
| Transport: SSE locally, configurable for production | `MCP_TRANSPORT`, default `sse`. `stdio`, `http` and `streamable-http` are supported with no code change |
| Pydantic v2 models for all inputs and outputs | `SearchMoviesInput`, `TitleLookupInput`, `MovieIdInput`, `SimilarMoviesInput`; `MovieResult` and `DatasetStats` out. `extra="forbid"`, so a typo'd filter is an error, not a dropped constraint |
| Connection pooling with asyncpg | `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE`, with `pgvector.asyncpg.register_vector` on connect so a `vector(768)` round-trips as a list |
| Health check at `GET /health` | 200 after `SELECT 1`, else 503. The Compose healthcheck uses the same path |
| Structured JSON logging with request tracing | structlog, one line per tool call with `tool`, `duration_ms`, `status` and `trace_id`. `_tool_span` resolves the id itself, because under SSE the tool body runs in the stream's task rather than the POST that delivered it |
| Environment-based configuration, no hardcoded values | `mcp-server/src/config.py`. Policy values are env vars too: `HIGH_IMDB_THRESHOLD`, `MCP_TOP_K_MAX`, `EMBEDDING_TIMEOUT_SECONDS` |

### The five example queries (3.3)

All five return relevant results through the API, asserted by
`scripts/e2e_test.sh`. Filters are extracted from the query text when the caller
omits them, and an explicit argument always wins. What the SQL constrains and
what rides on the embedding is a deliberate split:

| Query | Becomes a SQL filter | Carried by the embedding |
| ----- | -------------------- | ------------------------ |
| action movies from the 90s with high IMDB ratings | `Action`, `decade=1990`, `imdb ≥ 7.5` | — |
| critically acclaimed drama films with small budgets | `Drama`, `imdb ≥ 7.5` | small budgets |
| animated family movies distributed by Disney | — | animated, family, Disney |
| sci-fi films directed by James Cameron | — | sci-fi, James Cameron |
| dark psychological thrillers with low Rotten Tomatoes scores | `Thriller/Suspense` | dark, psychological, low RT |

Director, distributor, budget and Rotten Tomatoes are not in the tool signature,
and `sci-fi`, `animated` and `family` are not Vega `major_genre` values —
`sci-fi` is a Creative Type. They retrieve because 1.3 wrote them into
`augmented_text`, which means those constraints are soft: a James Cameron query
can return a near miss. Making them hard filters would mean extending the tool
signature past what the brief specifies.

```bash
# readiness (Compose healthcheck uses the same path)
curl -s http://localhost:8000/health

# call a tool from Python (server must be up)
python - <<'PY'
import asyncio
from fastmcp import Client

async def main() -> None:
    async with Client("http://localhost:8000/sse") as client:
        print(await client.call_tool("list_genres", {}))
        print(await client.call_tool(
            "search_movies_by_description",
            {"query": "action movies from the 90s with high IMDB ratings"},
        ))

asyncio.run(main())
PY
```

Search returns `[]` until the pipeline has loaded embeddings. Unit tests:
`cd mcp-server && pytest`.

To execute the SQL against a real database rather than just asserting on its
text — this is what catches an invalid query — point the suite at a throwaway
Postgres:

```bash
MCP_TEST_DSN=postgresql://movies:change_me_local_only@localhost:5432/movies pytest
```

## 9. API Documentation

The public API is **.NET 10 Minimal APIs** (not controllers): seven routes,
first-class OpenAPI 3.1, and little ceremony for a BFF that only orchestrates MCP
tools. Controllers would add MVC conventions, attribute routing and filter
pipelines to a surface that has one shape — read a query, call a tool, map a DTO
— so the cost of the choice is that those extension points are not there if the
surface later grows.

Four projects plus tests, as the brief's 4.3 layout specifies:

```
api/
├── MovieSearch.sln
├── src/MovieSearch.Api/              entry point, JWT, RBAC policies, OpenAPI,
│                                     rate limiting, timeouts, OpenTelemetry
├── src/MovieSearch.Application/      use cases + the cache-aside decorator
├── src/MovieSearch.Domain/           Movie, DatasetStats, SearchQuery,
│                                     IMovieSearchClient (no dependencies)
├── src/MovieSearch.Infrastructure/   McpMovieSearchClient (SSE), FakeMovieSearchClient
└── tests/MovieSearch.Tests/          unit + WebApplicationFactory integration tests
```

Dependencies point inwards: `Domain` references nothing, and both
`Application` and `Infrastructure` depend on its `IMovieSearchClient` rather than
on each other. That is what lets `MCP_CLIENT=fake` swap the entire data source at
the DI boundary.

Frozen spec: [`openapi.json`](openapi.json) (repo root) and live at
`http://localhost:8080/openapi/v1.json`. Swagger UI: `http://localhost:8080/swagger`.

The API never talks to Postgres. It calls FastMCP over SSE (`MCP_SERVER_URL`).
Set `MCP_CLIENT=fake` to serve deterministic fixtures with no MCP server at all.

| Method | Path | Role | MCP tool |
| ------ | ---- | ---- | -------- |
| POST | `/auth/token` | anonymous | — |
| GET | `/health` | anonymous | liveness |
| GET | `/health/ready` | anonymous | MCP ping when `MCP_CLIENT=mcp` |
| GET | `/api/v1/movies/search` | reader, admin | `search_movies_by_description` |
| GET | `/api/v1/movies/{id}` | admin | `get_movie_by_id` |
| GET | `/api/v1/movies/{id}/similar` | admin | `get_similar_movies` |
| GET | `/api/v1/movies/genres` | admin | `list_genres` |
| GET | `/api/v1/stats` | admin | `get_dataset_stats` |

```bash
# Token
TOKEN=$(curl -s http://localhost:8080/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"reader","client_secret":"reader-secret"}' \
  | jq -r .access_token)

# Search (reader)
curl -s "http://localhost:8080/api/v1/movies/search?q=action%20movies%20from%20the%2090s&top_k=10" \
  -H "Authorization: Bearer $TOKEN"

# Admin-only endpoint as reader → 403
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/v1/stats \
  -H "Authorization: Bearer $TOKEN"

ADMIN=$(curl -s http://localhost:8080/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"grant_type":"client_credentials","client_id":"admin","client_secret":"admin-secret"}' \
  | jq -r .access_token)

curl -s http://localhost:8080/api/v1/stats -H "Authorization: Bearer $ADMIN"
```

Search query parameters: `q` (required), `top_k` (default 10, max 50), `genre`,
`min_imdb_rating`, `mpaa_rating`, `decade`.

### Example responses

`POST /auth/token` → `200`:

```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs…", "token_type": "Bearer", "expires_in": 3600, "role": "reader" }
```

`GET /api/v1/movies/search?q=action+movies+from+the+90s` → `200`, ranked by
cosine similarity, descending. `GET /api/v1/movies/{id}` and `/similar` return
the same object and the same array respectively:

```json
[
  {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "The Matrix",
    "releaseYear": 1999,
    "majorGenre": "Action",
    "mpaaRating": "R",
    "director": "Lana Wachowski",
    "distributor": "Warner Bros.",
    "imdbRating": 8.7,
    "rtRating": 87,
    "similarity": 0.91
  }
]
```

`GET /api/v1/movies/genres` → `200`, a flat array of the distinct non-null
genres: `["Action", "Adventure", "Comedy", …]`.

`GET /api/v1/stats` → `200`:

```json
{ "totalMovies": 3200, "genres": 12, "yearMin": 1915, "yearMax": 2011, "avgImdbRating": 6.4 }
```

`GET /health` → `200` unconditionally (liveness, so Compose does not bounce the
process); `GET /health/ready` returns the same shape with `503` when the real MCP
client is configured and unreachable:

```json
{ "status": "healthy", "checks": { "mcp": "deferred" } }
```

Errors return an RFC 9457 `ProblemDetails` body — `400` for a blank `q`, `401`
without a token, `403` for a reader on an admin route, `429` past the rate limit
— with the exception of `404` for an unknown movie id, which has no body. All of
them are declared in the served OpenAPI document, and every model, parameter and
200 response carries an example, which is what pre-fills Swagger UI's "Try it
out".

### Performance and limits (4.5)

| Requirement | Setting | Observed |
| ----------- | ------- | -------- |
| Response caching for repeated identical queries, configurable TTL | `IMemoryCache` around every MCP call, `CACHE_TTL_SECONDS` (default 60) | Cache hits assert in `ApiTests`; the decorator is `CachingMovieSearchClient` |
| Rate limiting, 60 requests/minute per authenticated user | `RATE_LIMIT_PER_MINUTE`, partitioned on the JWT `sub` | 57 × 200 and 8 × 429 over 65 rapid calls |
| Request timeout, configurable, default 30s | `REQUEST_TIMEOUT_SECONDS` | — |
| All endpoints under 500ms at p95 | — | **17ms** p95 on search at the default limit; **608µs** over 4,795 requests at 80 req/s with the limit raised |
| k6 load test against the search endpoint | `scripts/load_test.js`, arrival rate derived from the configured limit | `k6 run scripts/load_test.js` — see [§13](#13-running-tests) |

API-only iteration (no MCP/Postgres): `MCP_CLIENT=fake docker compose run --no-deps --service-ports api`

The generated spec carries schemas, the Bearer scheme and examples on every
model, parameter and 200 response, so Swagger UI's "Try it out" is pre-filled.
The root `openapi.json` is generated from the served document by
`scripts/export_openapi.sh`, and `OpenApiSpecTests` asserts the two match, so
drift fails CI rather than accumulating.

## 10. Authentication

Client-credentials JWT. Two env-configured clients (see `.env.example`):

| client_id | client_secret (default) | role | Access |
| --------- | ----------------------- | ---- | ------ |
| `reader` | `reader-secret` | `reader` | **only** `GET /api/v1/movies/search` |
| `admin` | `admin-secret` | `admin` | all `/api/v1/*` including stats |

`POST /auth/token` accepts JSON or form-urlencoded (`grant_type=client_credentials`).
Response: `{ "access_token", "token_type": "Bearer", "expires_in", "role" }`.

Send `Authorization: Bearer <token>` on every `/api/v1/*` call. Missing token → 401;
reader on an admin route → 403. Signing key / issuer / audience come from
`JWT_SIGNING_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`. Rate limit: 60 requests/minute per
`sub` (client id). Request timeout: 30s (`REQUEST_TIMEOUT_SECONDS`).

## 11. Observability

| Signal | Where |
| ------ | ----- |
| Logs | JSON on the API container stdout (Serilog `RenderedCompactJsonFormatter`); rolling files at `/app/logs/api-*.log`. Both carry `@tr` and `@sp`, compact JSON's trace and span ids, so a line joins to its Jaeger span. The MCP server logs structured JSON via structlog with the same id as `trace_id`. The pipeline logs plain text to stdout and `reports/pipeline.log`. |
| Traces | Jaeger UI `http://localhost:16686` (OTLP gRPC `jaeger:4317`). The MCP server reads `traceparent` off inbound HTTP; the .NET side propagates it through `HttpClientInstrumentation`. Verified: one trace spans `GET /api/v1/movies/search` → `mcp.search_movies_by_description` → the MCP server, whose JSON logs carry the same `trace_id`. |
| Metrics | Prometheus `http://localhost:9090` scrapes `api:8080/metrics`. Grafana `http://localhost:3000` (admin/admin from `.env`) loads the **Movie Search** dashboard: request rate, latency p50/p95/p99, 5xx rate, MCP tool latency, active connections. |

### Production tracing (AWS X-Ray)

Local and production differ only in trace-id format and the propagator, both
switched by `AWS_XRAY_ENABLED` (false locally, set true by the ECS task
definition):

| | Local | ECS |
| --- | --- | --- |
| Exporter | OTLP → Jaeger | OTLP → ADOT collector sidecar → X-Ray |
| Trace ids | W3C random | X-Ray (`AddXRayTraceId`: high 32 bits are the trace-start epoch seconds) |
| Propagator | `tracecontext` + `baggage` | `AWSXRayPropagator` first, then `tracecontext` + `baggage` |

X-Ray rejects W3C-random ids, which is why the id generator has to change and not
just the exporter. The composite keeps `tracecontext` so the MCP server — which
only understands `traceparent` — still joins the same trace.

Verified locally with the flag forced on: an inbound
`X-Amzn-Trace-Id: Root=1-5759e988-bd862e3fe1be46a994272793` produced spans on
trace `5759e988bd862e3fe1be46a994272793`, and generated ids carried the request
timestamp in their prefix. ⚠️ Never observed in X-Ray itself, because nothing is
deployed — the ADOT-sidecar-to-X-Ray hop is the untested part.

## 12. Terraform Deployment

Deploys to **AWS ECS Fargate**. Module-level detail: [`terraform/README.md`](terraform/README.md).

**Why ECS Fargate over EKS.** This platform is five long-lived containers and two
run-to-completion jobs. Fargate removes the control-plane cost and the node
lifecycle entirely, and ECS service auto-scaling, ALB target groups, Secrets
Manager injection and CloudWatch logging are all first-party rather than
add-ons. EKS would buy portability and a richer scheduling model that nothing
here needs, at the cost of managing an upgrade cadence.

### Layout

```
terraform/
├── bootstrap/            # S3 state bucket + DynamoDB lock table (run once per account)
├── modules/
│   ├── networking/       # VPC, public/private subnets, NAT, SGs, VPC Flow Logs
│   ├── compute/          # ECS cluster, task definitions, services, auto-scaling
│   ├── rds/              # PostgreSQL 16 + pgvector, private, encrypted
│   ├── ecr/              # tag-immutable repositories with lifecycle policies
│   ├── alb/              # ALB, ACM certificate, HTTPS listener, HTTP→HTTPS redirect
│   ├── iam/              # task/execution roles, GitHub OIDC deploy role
│   ├── monitoring/       # CloudWatch dashboard, alarms, X-Ray
│   └── secrets/          # Secrets Manager entries
├── environments/{dev,prod}/   # roots: backend, provider, per-env sizing
├── main.tf, variables.tf, outputs.tf, versions.tf   # composition module
└── README.md
```

`terraform/` is a *composition module*, not a root: it declares no provider and
no backend. The roots are `environments/dev` and `environments/prod`, which own
the S3 backend, the provider (including `default_tags`) and the sizing. Dev is
cost-shaped — one NAT gateway, `db.t4g.micro`, single-AZ, 1-day backups — but
structurally identical to prod, so a dev plan is a meaningful rehearsal.

### Step-by-step

None of this has been applied — the ⚠️ under
[Infrastructure requirements](#infrastructure-requirements) is the limit of the
evidence. What follows is the execution order the modules and the dev plan imply,
with the checkpoint after each phase that separates "the command returned" from
"the phase worked". Budget 45–60 minutes for a first run, most of it spent
waiting on RDS and on image pushes.

**0. One shell, three variables.** The provider takes its region from
`aws_region`, which the dev root defaults to `eu-west-1`, but
[`scripts/run_ecs_task.sh`](scripts/run_ecs_task.sh) and the ECR login and push
commands pass no `--region` and so follow whatever the AWS CLI's own default is.
If the two differ, those commands fail in a way that reads like a missing
cluster, so set the region explicitly and keep one shell for the whole session:

```bash
export AWS_REGION=eu-west-1
export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export TAG=$(git rev-parse --short=12 HEAD)
```

**1. Bootstrap the state backend** (once per AWS account):

```bash
cd terraform/bootstrap
terraform init
terraform apply -var=aws_region="$AWS_REGION"   # no default for this variable here
terraform output
```

This is the only configuration in the repo that keeps state locally, because it
creates the bucket the other roots store state in. It creates a versioned,
encrypted, public-access-blocked S3 bucket — `movie-search-tfstate-<account-id>`,
noncurrent versions expiring at 90 days — and a point-in-time-recovery DynamoDB
lock table, both with `prevent_destroy`.

**Checkpoint:**

```bash
aws s3api head-bucket --bucket "movie-search-tfstate-${ACCOUNT}" && echo "bucket ok"
aws dynamodb describe-table --table-name movie-search-tf-locks \
  --query 'Table.TableStatus' --output text      # ACTIVE
```

**2. Configure the environment root:**

```bash
cd ../environments/dev
cp backend.hcl.example backend.hcl              # bucket from step 1, and the region
cp terraform.tfvars.example terraform.tfvars    # region, GitHub repo, TLS, alarm email
```

Both files are gitignored: the bucket name embeds the AWS account id. Two inputs
decide what the plan even contains:

- **`github_repository`** (`<owner>/<repo>`) reaches further than CD. Every OIDC
  resource in `modules/iam` is gated on
  `local.enable_oidc = var.github_repository != null`, so leaving it unset
  silently drops the GitHub provider and the deploy role from the plan and the
  resource count no longer matches.
- **TLS** switches on with either `certificate_arn` (an existing ACM
  certificate) or `domain_name` + `route53_zone_id` (Terraform requests and
  DNS-validates one). With neither, the ALB serves HTTP only and the plan says
  so, for the reason the note on the missing HTTPS listener at the end of this
  section gives.

**3. Init onto the S3 backend, then plan:**

```bash
terraform init -reconfigure -backend-config=backend.hcl
terraform plan -out=dev.tfplan
```

`-reconfigure` is required if the root was ever initialised against a different
backend — the recorded plan used a temporary local one, because bootstrap had
not been applied — since otherwise Terraform tries to migrate that state instead
of adopting the S3 backend.

**Checkpoint:** for dev with `github_repository` set and TLS left unset, the plan
is **143 to add, 0 to change, 0 to destroy**. A lower count is most often a
missing `github_repository`. Expect exactly one warning, about the deprecated
`dynamodb_table`, which both roots set deliberately alongside `use_lockfile`; it
is not a failure. This phase is also the first real exercise of the S3 backend
and the lock table — to watch the lock being taken, run a second `terraform plan`
in another shell while a long apply holds it, and it should refuse with a lock
error naming the holder.

**4. Create the ECR repositories and push images.** The repositories are
tag-immutable and `image_tag` defaults to `"latest"`, which is never pushed, so
the images have to exist before the main apply — and the main apply is what
creates the services that need them. Break the cycle by applying the registry
module alone; it is a no-op on every later run:

```bash
terraform apply -target=module.platform.module.ecr

aws ecr get-login-password | docker login --username AWS \
  --password-stdin "${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"

REG="${ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/movie-search-dev"
cd ../../..                                     # repo root, for the build contexts
for svc in api mcp-server pipeline; do
  docker buildx build --push -t "$REG/$svc:$TAG" "./$svc"
done
docker buildx build --push -t "$REG/migrate:$TAG" ./database
cd terraform/environments/dev
```

Four images, not five: `atlas` is a local-only bonus and is not deployed, which
also spares its ~9.6 GB push. Tags are the 12-character git SHA because the
repositories are tag-immutable: a tag names exactly one image, so a rollback is a
redeploy of an older SHA rather than a re-tag. The task definitions declare
`cpu_architecture = X86_64`, so on an arm host add `--platform linux/amd64` or
the tasks fail to start with an exec format error.

**Checkpoint:** all four tags resolve.

```bash
for svc in api mcp-server pipeline migrate; do
  aws ecr describe-images --repository-name "movie-search-dev/$svc" \
    --image-ids imageTag="$TAG" --query 'imageDetails[0].imagePushedAt' --output text
done
```

**5. Apply:**

```bash
terraform apply -var="image_tag=$TAG"
```

15–20 minutes, dominated by the RDS instance. The services set
`wait_for_steady_state = false`, so **the apply returns before the platform is
serving** — deliberate, because a first apply with a missing image would
otherwise become a fifteen-minute timeout instead of a legible "cannot pull
image" event, and the reason step 6 waits explicitly.

**Checkpoint:**

```bash
terraform output api_url                                             # http://movie-search-dev-…elb.amazonaws.com
aws s3 ls "s3://movie-search-tfstate-${ACCOUNT}/movie-search/dev/"   # state landed in S3
```

**6. Wait for the platform, then migrate and seed the data.** Compose expresses
this ordering with `depends_on`; `aws ecs run-task` has no equivalent, so wait
first. It matters most for `embeddings`, whose container health check greps
`ollama list` with a 300-second start period — the service only reaches steady
state once the model is resident on the EFS volume, and a pipeline task started
before that retries four times and fails.

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)

aws ecs wait services-stable --cluster "$CLUSTER" \
  --services movie-search-dev-embeddings movie-search-dev-mcp-server movie-search-dev-api
```

Then the two run-to-completion tasks, in this order. The helper reads the
`awsvpc` configuration from the Terraform outputs and waits for the task to exit:

```bash
terraform output -json run_task_network_configuration > /tmp/netcfg.json
SCRIPTS=../../../scripts

"$SCRIPTS"/run_ecs_task.sh "$CLUSTER" "$(terraform output -raw migrate_task_definition_arn)"  /tmp/netcfg.json
"$SCRIPTS"/run_ecs_task.sh "$CLUSTER" "$(terraform output -raw pipeline_task_definition_arn)" /tmp/netcfg.json
```

`run_ecs_task.sh` exists because `aws ecs run-task` is fire-and-forget: it
returns as soon as the task is accepted, so a migration that exits 1 still looks
like a successful API call. The helper waits for the task to stop, reads the
container exit code and surfaces the stop reason.

**Checkpoint:** both print `Exit code: 0`, and the pipeline's own log reports
3,200 rows upserted and 1 skipped — the same numbers as a local run, since it is
the same dataset. Embedding 3,201 texts takes about 80 seconds locally; expect
longer on a 1 vCPU task against a cold model.

```bash
aws logs tail /ecs/movie-search-dev/pipeline --since 20m | tail -30
```

**7. Verify:**

```bash
BASE_URL=$(terraform output -raw api_url) "$SCRIPTS"/smoke_test.sh
BASE_URL=$(terraform output -raw api_url) "$SCRIPTS"/e2e_test.sh
terraform output -raw cloudwatch_dashboard_url
```

Run both, in that order: `smoke_test.sh` asserts routing, authentication and role
enforcement and passes against an empty database, while `e2e_test.sh` is the one
that proves data flowed the length of the chain ([§13](#13-running-tests)). Both
speak plain HTTP as long as TLS is off. The client secrets are generated per
environment and live in Secrets Manager, so the `.env` values that work locally
do not apply here.

Prod is the same sequence in `environments/prod`, but CD promotes the exact
digests dev validated rather than rebuilding — see
[§CI/CD](#cicd) below.

**Teardown:**

```bash
terraform destroy -var="image_tag=$TAG"
```

Clean in dev by design: `db_deletion_protection = false` (so
`skip_final_snapshot` is true), `force_destroy` on the ALB access-log bucket, and
`force_delete` on the ECR repositories, which is what lets them go while still
holding images. Prod sets `db_deletion_protection = true`, so the same command
does not succeed there without a deliberate change.

The bootstrap bucket and lock table **survive**, since both carry
`prevent_destroy` — leave them, as an empty versioned bucket and an on-demand
table cost cents and are what makes the next apply a two-command affair.

**Checkpoint:** `terraform show` reports no resources, and the two expensive
things are gone. Check them explicitly rather than trusting the destroy summary:

```bash
aws ec2 describe-nat-gateways \
  --filter 'Name=state,Values=available' --query 'NatGateways[].NatGatewayId'
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
```

### Deployment troubleshooting

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| `ResourceNotFoundException` on the cluster, or ECR login rejected | `AWS_REGION` is not set in this shell, so the CLI uses its own default while Terraform uses `eu-west-1`; the scripts pass no `--region` | `export AWS_REGION=eu-west-1` and re-run in that shell |
| `Backend configuration changed` on init | `.terraform` is initialised against a different backend | `terraform init -reconfigure -backend-config=backend.hcl` |
| Plan shows fewer resources than expected | `github_repository` unset, so every OIDC resource is skipped | Set it in `terraform.tfvars` |
| Tasks stuck in `PENDING`, then `CannotPullContainerError` | Image tag missing from ECR, or built for the wrong architecture | Re-run step 4; on arm hosts add `--platform linux/amd64` |
| A service sits at 0 running with `deployment failed: tasks failed to start`, and its events show `ResourceNotFoundException ... staging label: AWSCURRENT` | The service was created before the secret's *value* was written — see [§14](#14-known-limitations--future-improvements). The circuit breaker gives up and will not retry | Confirm the value exists (`aws secretsmanager describe-secret --secret-id <name> --query VersionIdsToStages`), then `aws ecs update-service --cluster <cluster> --service <service> --force-new-deployment` |
| The cluster or its services appear not to exist at all | The console or CLI is in a different region; the platform is in `eu-west-1` and passes no `--region` in the scripts | `export AWS_REGION=eu-west-1`, and switch the console region picker to Ireland |
| `embeddings` never reaches steady state | The first-boot model pull comes from Docker Hub through the single NAT gateway and can hit anonymous rate limits | Check `aws logs tail /ecs/movie-search-dev/embeddings`; retry, or point `embeddings_image` at an ECR pull-through cache |
| Pipeline task exits non-zero with embedding timeouts | It ran before `embeddings` was healthy | Wait for `services-stable`, then re-run — the loader is idempotent |
| Pipeline task fails fetching the dataset | `vega_datasets` fetches the CSV at runtime and needs NAT egress | Confirm the task ran in a private subnet with the NAT route |
| Smoke test returns 401 everywhere | Secrets are generated per environment, so local `.env` credentials do not apply | Read the client secrets from Secrets Manager |
| `data.aws_elb_service_account` error | Only affects regions opened after August 2022, which have no ELB service account | The data source has to be removed for such a region |

### Infrastructure requirements

Every requirement in §6.2 of the brief is implemented:

| Requirement | Where |
| ----------- | ----- |
| All secrets via Secrets Manager, none hardcoded | `modules/secrets`, `modules/rds` (DB credential + full DSN); injected into tasks as `secrets`, never `environment` |
| Tasks use IAM roles, no access keys | `modules/iam` task + execution roles; GitHub Actions authenticates via OIDC |
| RDS in private subnets only | `modules/rds`: `publicly_accessible = false`, dedicated subnet group, `storage_encrypted = true` |
| ALB with HTTPS (ACM) | `modules/alb`: `:443` listener, configurable `ssl_policy`, `:80` redirects to `:443` — but **dormant until a certificate is supplied**, and no domain exists to get one for ([§14](#14-known-limitations--future-improvements)) |
| Auto-scaling (CPU and memory) | `modules/compute`: two `aws_appautoscaling_policy` target-tracking policies per service |
| VPC Flow Logs | `modules/networking`, retention configurable |
| S3 backend + DynamoDB locking | `terraform/bootstrap`; roots set `dynamodb_table` *and* `use_lockfile` so locking survives the Terraform 1.11 deprecation |
| Tags: Environment, Project, ManagedBy | `default_tags` on the provider in each root |

`terraform fmt -check` and `validate` pass on all four roots, and a dev
`terraform plan` against a real account is clean — 143 to add, 0 to change, 0 to
destroy, no warnings — which is where the resolved values above come from rather
than from reading HCL. That plan has since been **applied**: all 143 resources
exist in `eu-west-1`, the ECS task definitions do start cleanly, and the state is
in S3 under a DynamoDB lock. ⚠️ Two caveats remain: the ECS services can outrun
the secret values they read, a dependency bug covered in
[§14](#14-known-limitations--future-improvements), and there is still no measured
cost figure. Evidence, including the table of requirements read off the plan:
[`reports/section-6.md`](reports/section-6.md#terraform).

**Why there is no HTTPS listener.** The ALB has exactly one listener — HTTP on
port 80, in the plan and now in the applied environment — which looks like the
HTTPS row above is unmet. It
is not a missing feature but a missing input. TLS is not a boolean: the module
turns it on when a certificate becomes available, either `certificate_arn` for one
that already exists or `domain_name` plus `route53_zone_id`, in which case
Terraform requests an ACM certificate and validates it by DNS. ACM public
certificates require domain validation, so a certificate cannot exist without a
domain, and this account has no hosted zone — hence no certificate, hence the
`:443` listener and the `:80` redirect are both `count = 0` and never reach the
account. Supply either input and all three appear, along with an alias record.
Deliberate, documented in [§14](#14-known-limitations--future-improvements), and
the one requirement above that the deployment cannot corroborate on its own.

### CI/CD

**`ci.yml`** runs on every pull request to `main`, in four parallel jobs:

- **Python** — `ruff check`, `mypy` on both `pipeline` and `mcp-server`, then
  `pytest` on each against a `pgvector/pgvector:pg16` service container, plus two
  steps that fail if the database-backed modules skipped.
- **.NET** — `dotnet format --verify-no-changes`, then `dotnet test` in Release.
- **Docker** — builds every image (including `database/Dockerfile`, which Compose
  never builds because it bind-mounts the SQL instead), starts the whole platform
  with `docker compose up -d --wait`, blocks on `docker compose wait pipeline`,
  then runs `scripts/smoke_test.sh`, `scripts/e2e_test.sh` and the live-MCP .NET
  tests against it. Starting everything rather than just `api` and its dependency
  closure is what makes CI exercise the embed-and-load path and the real SSE
  client; the cost is a slow job that has to free disk space first.
- **Terraform** — `fmt -check -recursive`, then `init -backend=false` and
  `validate` on all four roots so validation needs no AWS credentials. A real
  `plan` runs only when the OIDC role variable is configured, so forks still get
  the first two.

**`cd.yml`** runs on push to `main`. It reuses `ci.yml` wholesale — a red CI
never reaches an environment — then builds and pushes SHA-tagged images to ECR,
applies dev, runs the Flyway migration task, waits for the ECS services to
stabilise, and smoke-tests dev. Prod is gated behind GitHub environment
reviewers; on approval it promotes the exact digests dev validated (nothing is
rebuilt between environments), applies prod, migrates, and smoke-tests prod.

## 13. Running Tests

```bash
# Python: lint, types, unit tests (the exact CI gates)
uv sync --all-packages --dev
uv run ruff check .
(cd pipeline   && uv run mypy src && uv run pytest -q)   # 62 passed, 4 skipped
(cd mcp-server && uv run mypy src && uv run pytest -q)   # 58 passed, 6 skipped

# .NET: unit + WebApplicationFactory tests (fake MCP, no Docker needed)
dotnet test api/MovieSearch.sln              # 22 passed, 5 skipped (live-MCP)
dotnet format api/MovieSearch.sln --verify-no-changes

# The 5 skipped tests are the only ones that speak to a real MCP server.
# Point them at a running one to include them:
MCP_INTEGRATION_URL=http://localhost:8000 \
  dotnet test api/MovieSearch.sln --filter "FullyQualifiedName~LiveMcpTests"   # 5 passed

# Regenerate the committed openapi.json from the live document. The same test
# asserts it in CI, so drift fails the build.
./scripts/export_openapi.sh

# Without a local .NET SDK, run the same gates in the SDK image:
docker run --rm -v "$PWD/api":/src -w /src mcr.microsoft.com/dotnet/sdk:10.0 \
  bash -c "dotnet restore MovieSearch.sln && dotnet test MovieSearch.sln -c Release --no-restore"

# Compose integration smoke test (routing, auth, roles — no data required)
docker compose up -d --wait api
BASE_URL=http://localhost:8080 ./scripts/smoke_test.sh

# Full end-to-end verification. `up --wait` returns once containers are running,
# so wait for the one-shot pipeline to exit before asserting on data.
docker compose up -d --wait
docker compose wait pipeline
./scripts/e2e_test.sh

# Load test (p95 < 500ms on search). Needs k6 and a live stack (or MCP_CLIENT=fake).
k6 run scripts/load_test.js

# Terraform
terraform fmt -check -recursive terraform/
terraform -chdir=terraform validate
```

**The two Compose test scripts differ in intent.** `smoke_test.sh` asserts only
routing, authentication and role enforcement, so it passes against a freshly
migrated (empty) database — which also means it cannot detect a broken
embed-and-load path.
`e2e_test.sh` is the opposite: it assumes the pipeline has run and asserts that
data flows the length of the chain, checking that every row carries a 768-dim
vector, that the brief's five natural-language queries return results, that
hybrid filters actually constrain, that `similar` excludes its source movie, and
that `/stats` agrees with the row count in pgvector.

**Database-backed tests.** Ten tests skip unless a DSN is provided:
`test_loader_integration.py` needs `PIPELINE_TEST_DSN` and
`test_sql_execution.py` needs `MCP_TEST_DSN`. Both **`TRUNCATE movies`** — point
them at a throwaway database, never one you care about, and re-run the pipeline
afterwards:

```bash
export PIPELINE_TEST_DSN=postgresql://movies:change_me_local_only@localhost:5432/movies
export MCP_TEST_DSN="$PIPELINE_TEST_DSN"
(cd pipeline && uv run pytest -q)     # 66 passed
(cd mcp-server && uv run pytest -q)   # 64 passed
docker compose run --rm pipeline      # restore the dataset
```

CI runs all ten: the Python job has a `pgvector/pgvector:pg16` service and sets
both DSNs. Because these modules skip themselves when a DSN is missing, CI also
asserts they actually ran, so a broken DSN fails the job instead of quietly
dropping the coverage.

## 14. Known Limitations & Future Improvements

**Verification gaps** (the honest list, expanded in [§0](#0-status)):

- **The deployed database is empty.** Dev is applied and serving, but the
  `pipeline` task has not been run against it, so nothing has been embedded or
  loaded on AWS. `scripts/smoke_test.sh` and `scripts/e2e_test.sh` have likewise
  not been run against the ALB. Routing, auth, service discovery and the Flyway
  migration are all proven on Fargate; **search is not**. That is the honest limit
  of the deployed evidence, and it is the gap to close first — the pipeline task
  definition already exists, so it is one `scripts/run_ecs_task.sh` away.
- **ECS services can start before their secrets have values.** ⚠️ A real
  dependency bug, not a transient. `modules/rds` publishes the secret ARN from
  `aws_secretsmanager_secret` rather than from `aws_secretsmanager_secret_version`,
  so nothing in Terraform's graph stops `modules/compute` creating a service that
  reads a secret which is still empty. On the first apply this took `mcp-server`
  down: its tasks started four minutes before the DSN was written, failed with
  `ResourceNotFoundException ... staging label: AWSCURRENT`, and the deployment
  circuit breaker gave up rather than retrying into success. It does not
  self-heal; `aws ecs update-service --force-new-deployment` recovers it once the
  value exists. `api` survived only because its secrets happened to be written
  before its tasks launched, which is luck rather than design, and it means a
  rebuild from scratch could just as easily take `api` down instead. The fix is to
  reference the `_version` resource's `arn`, which is the same ARN but adds the
  missing edge.
- **No measured cost figure.** The estimate in §12 predates the applied
  environment and has not been checked against Cost Explorer, which lags a day.
- CI's `terraform plan` step needs the OIDC role, so on a fork it is skipped. It
  now emits a warning annotation and a run-summary note rather than passing
  quietly as though all three checks ran.
- **Prod has never been applied.** Only `environments/dev` has run against a real
  account; the prod root remains plan- and validate-only.
- CI's `terraform plan` step needs the OIDC role, so on a fork it is skipped. It
  now emits a warning annotation and a run-summary note rather than passing
  quietly as though all three checks ran.
- X-Ray trace-id generation and propagation are verified locally (see
  [§11](#11-observability)) but have never been seen in X-Ray itself. The
  environment that would show them now exists; what is missing is the traffic,
  which is blocked on the empty database above.
- No walkthrough video yet.

**Fixed while verifying the stack end to end** (each had shipped unnoticed
because no run had ever exercised the full chain):

- The .NET MCP client deserialized FastMCP's `{"result": ...}` envelope directly
  into the target type. MCP requires `structuredContent` to be an object, so
  FastMCP wraps every tool whose return type is not one — five of the six here.
  Search, similar, genres and by-id all returned 500; only `get_dataset_stats`,
  which returns a bare object, worked. `McpMovieSearchClient` now unwraps it, and
  `test_dotnet_contract.py` pins the contract on both sides.
- The MCP server's `TraceIdMiddleware` subclassed Starlette's
  `BaseHTTPMiddleware`, which is incompatible with streaming responses: every
  `GET /sse` raised `AssertionError: Unexpected message` and logged a traceback.
  It is now raw ASGI middleware.
- The 1.5 loader bound an explicit NULL for any absent imputation flag, which
  the `NOT NULL DEFAULT FALSE` columns rejected — a DEFAULT only applies to an
  omitted column, and the loader always binds all of them. Absent now maps to
  `FALSE`.
- `test_sql_execution.py` seeded collinear fixture vectors (`[0.10] * 768`,
  `[0.11] * 768`, `[0.90] * 768`). Cosine ignores magnitude, so all three tied at
  similarity 1.0 and the "ranks by cosine" assertions were really asserting
  physical row order. The fixtures now differ in direction.
- `scripts/load_test.js` ramped to 20 VUs against a 60 request/minute limit
  scoped to a single client, so 2,019 of 2,080 requests were throttled and the
  script could not pass its own thresholds. It now derives its arrival rate from
  the configured limit.

**Functional gaps:**

- **HTTPS is off**, because TLS switches on only when a certificate is available
  and there is no domain to get one for: ACM public certificates require domain
  validation and the account has no Route53 hosted zone. The Terraform is
  complete — supply `certificate_arn`, or `domain_name` plus `route53_zone_id` and
  Terraform requests and DNS-validates the certificate itself — at which point
  port 80 becomes a redirect, a 443 listener appears with the configured
  `ssl_policy`, and an alias record is created. Worth closing before any real
  deployment, since until then the ALB would carry bearer tokens in plaintext.
- **Atlas colour-by-genre is a patch against a third-party seam.**
  `scripts/atlas/atlas_color_by.py` wraps the `embedding-atlas` CLI's prop builder
  to set `defaultChartsConfig.embedding.data.category`, because the CLI has no
  option for colour and returns its props verbatim when serving. It works and is
  browser-verified, but it leans on internals that a minor release could move, so
  it fails open: an unexpected props shape logs a warning and serves stock Atlas.
  The mechanism, and why `initialState.charts` was the wrong instrument, are in
  [`reports/section-5.md`](reports/section-5.md#why-this-needed-a-patch).
- The Compose `api` healthcheck probes liveness `/health` rather than
  `/health/ready`, so the container reports healthy before MCP is reachable. This
  is deliberate: `/health` is unconditionally 200 so Compose does not restart the
  API while it waits for MCP, and `api` already gates on
  `mcp-server: condition: service_healthy`, so ordering is enforced by the
  dependency rather than by the probe.

**Design limitations:**

- Reader tokens are search-only; a richer catalog UI would need a broader reader
  role.
- The century-correction cutoff (2011) is specific to the frozen Vega file and
  must be revisited if the dataset is refreshed.
- One row of 3,201 (the untitled 2006 record) is skipped by the loader because
  it has no natural key and so cannot upsert idempotently.
- One value remains hardcoded despite the "no hardcoded values" goal:
  `REQUEST_TIMEOUT_SECONDS = 120.0` in `pipeline/src/pipeline/embedding.py`. The
  MCP server's policy values are all configurable — `HIGH_IMDB_THRESHOLD`,
  `MCP_TOP_K_MAX` and `EMBEDDING_TIMEOUT_SECONDS` in `mcp-server/src/config.py`.
  (`filters.py` still defines `HIGH_IMDB_THRESHOLD = 7.5`, but as the module
  default that the tool layer overrides from settings.) `TOP_K_MIN = 1` and the
  default `top_k` of 10 stay in code deliberately: one is an invariant, the other
  is fixed by the brief.
- HNSW is indexed but the planner will likely sequential-scan at 3.2k rows. The
  index matters only if the corpus grows.

## 15. Design Decisions & Trade-offs

Every row below is a choice that had a credible alternative. The second column is
what was rejected, the third is what the choice costs — because a decision
documented without its cost is only half documented. Per-part narrative lives in
`reports/section-1.md` … `section-6.md`; this is the consolidated register.
Verification gaps are a different thing and stay in [§14](#14-known-limitations--future-improvements).

One principle decides most of Part 1 and half of Part 2: **flag rather than
silently mutate, and never render a value the data does not support.** Cleaning
fixes structure and unambiguous errors; anything uncertain is nulled, counted and
left to imputation; imputation fills columns but never the embedding input. The
cost is a corpus with visible holes rather than a tidy one, which is the trade
this system is built around.

### Part 1 — Data pipeline

| Decision | Instead of | Trade-off accepted |
| -------- | ---------- | ------------------ |
| De-duplicate on `(normalized title, release_year)` | Title alone, or a surrogate key | The key must stay identical to the loader's `ON CONFLICT` target; change one and idempotency silently breaks in the other. Remakes survive, which title alone would not allow. |
| Keep the most complete row of a duplicate group, tie-broken on `imdb_votes` | First-wins or last-wins | Deterministic only while the input order is stable. |
| Null numerics outside a sensible range | Clamp to the boundary | More missingness for 1.2 to fill, in exchange for never storing a fabricated measurement that is indistinguishable from a real one. |
| Treat `0` box office as missing | Accept it as a real $0 | A genuinely zero-gross film would be recorded as unknown. In this file `0` is how unknown box office was encoded, and no such film exists. |
| Century-correct any year above 2011 | A `year > current_year` rule | A dataset-specific constant that must be revisited if the Vega file is replaced. The general-looking rule would have missed 22 pre-1950 titles, including *Ben-Hur* stored as 2025. |
| Leave capitalisation alone | `str.title()` on categoricals | Depends on the source already being consistent. Blind title-casing corrupts `20th Century Fox` and `Based on Book/Short Story`. |
| `"Unknown"` sentinel for descriptive categoricals | Mode imputation | The sentinel does reach API responses. Mode would attribute 1,331 films to one director — and "sci-fi films directed by James Cameron" is one of the brief's own queries. |
| Group median with a 10-observation floor: genre for ratings and runtime, decade for budget | `genre × decade` | A coarser conditioner than it looks like it should be. `genre × decade` was measured first: 28 of its 75 cells hold fewer than 5 rows, so its medians are noise. |
| `major_genre` stays NULL | `"Unknown"`, like the other categoricals | 275 rows are invisible to `list_genres` and the genre filter. Better than a browsable category and a selectable filter value that mean nothing. |
| Per-cell `<column>_imputed` provenance | Store values only | Four extra `NOT NULL` columns the loader must bind every time — it broke on exactly this once. Downstream can tell an observed 6.4 from a filled one. |
| Omit a template line when its value was not observed | Render the imputed value, or `Runtime: Unknown` | Rows carry unequal signal. The sentinel would have been actively worse: identical across every affected row, it pulls unrelated films together in vector space purely because they share a gap. |
| Fixed industry budget thresholds | Sample quartiles | Nominal dollars, so older films skew indie. In exchange "$15M indie" keeps its meaning if the corpus is refreshed. |
| Derived features NULL unless every input was observed | Compute them from filled values | Coverage gaps in Atlas facets and API responses (`rating_score_delta` on 2,260 of 3,201) instead of guesses that look measured. |
| A batch that fails validation raises | Yield short vectors and carry on | One bad batch fails the whole run. A quietly incomplete corpus is far harder to notice, and the loader is idempotent so a re-run is cheap. |
| Skip and count the one row with no natural key | Synthesise `"(untitled 2006-11-03)"`, or drop it silently | One row of 3,201 is unsearchable. The alternative serves a fabricated title to clients through `MovieResult.title` as though it were real. |

### Part 2 — Vector database

| Decision | Instead of | Trade-off accepted |
| -------- | ---------- | ------------------ |
| Flyway | Alembic | Forward-only, so local schema edits need `docker compose down -v`, and there is no Python-native autogenerate. Bought: SQL-first DDL in a polyglot stack, raw pgvector and HNSW syntax, and the same files applying to RDS. |
| Partial unique index on `(lower(title), release_year)` | A materialized `natural_key` column | The upsert has to restate the index predicate exactly, or Postgres cannot infer it and the upsert silently becomes an insert. `pipeline/tests/test_loader.py` pins the two together. |
| `title` nullable | `NOT NULL` | The schema accepts a row the loader then refuses, and MCP maps the NULL to `""`. The hole stays explicit in the schema rather than being hidden by a rejection. |
| Partial HNSW `WHERE embedding IS NOT NULL` | A full index | Queries must carry the same predicate for the planner to use the index — `hybrid_search.sql` does. Unembedded rows never bloat it. |
| Default `m` / `ef_construction` | Tuned HNSW parameters | Nothing is tuned for scale that does not exist. At 3,200 rows the planner will likely sequential-scan anyway. |
| Omit `us_dvd_sales` | Store it | Not filterable or searchable. It is too sparse to help ranking and is not in the brief's text template. |
| Hybrid query as a documented `.sql` file | A view or a SQL function | Two copies exist — the canonical one and the one baked into the MCP image — so `test_sql_sync.py` has to fail when they drift. In exchange the query is reviewable, and the same text is used by Part 3 and pinned by tests. |
| Return `1 - (embedding <=> $1)` as `similarity` | Return raw cosine distance | One extra arithmetic step, and a number that only means cosine when `match_type` says `semantic`. Callers get higher-is-better in `[0, 1]`. |

### Part 3 — MCP server

| Decision | Instead of | Trade-off accepted |
| -------- | ---------- | ------------------ |
| A sixth tool, `get_movie_by_id` | Serving `GET /api/v1/movies/{id}` from `get_movie_by_title` | Departs from the brief's five-tool list. Without it that endpoint had nothing to call and failed against the real server while passing its own tests. |
| Flat named parameters validated by Pydantic input models | One nested model argument, the more literal reading of "Pydantic v2 models for all inputs" | Less literal. A nested argument changes every call to `{"input": {…}}` and breaks the .NET client for no gain; validation and constraints still live in the models. |
| `top_k` clamped to `MCP_TOP_K_MAX` | Rejecting out-of-range values | A caller asking for 1,000 gets 50 and is not told. Friendlier for an LLM caller that cannot reliably read the schema's bounds. |
| `extra="forbid"` on inputs | Ignoring unknown arguments | A typo'd argument name is an error instead of a silently dropped filter. |
| Every row carries `match_type` | `similarity` on its own | An extra field clients have to read. Without it, cosine similarity, trigram similarity, `1.0` for exact and `NULL` for a lookup are four incomparable meanings on one number. |
| An exact title hit scores `1.0` | `NULL` | `1.0` is not a measured similarity, but a perfect match now outranks a fuzzy one instead of sorting last. |
| Only genre, decade, min IMDB and MPAA become SQL filters | Also parsing director, distributor, budget and Rotten Tomatoes out of the query | Those constraints stay soft: they ride on the embedding, so "directed by James Cameron" can return near misses. They are not Vega `major_genre` values and not in the tool signature. |
| Empty corpus or unknown id returns `[]` / `None` | Raising | A misconfigured deployment looks like an empty dataset rather than an error. |
| `_tool_span` resolves `trace_id` itself | Relying on the HTTP middleware's contextvar | A little duplicated work per call. Necessary: under SSE the tool body runs in the stream's task, not the POST that delivered the message, and under `stdio` there is no HTTP request at all. |
| The embedding client is duplicated, not shared with the pipeline | A shared package | Two copies to keep in step, in exchange for two independent images with no shared build context. |
| `HIGH_IMDB_THRESHOLD`, `MCP_TOP_K_MAX` and `EMBEDDING_TIMEOUT_SECONDS` are env vars; `TOP_K_MIN` and the default `top_k` of 10 are not | Everything configurable, or nothing | A larger config surface for the three that are policy. One of the two left in code is a structural invariant, the other is fixed by the brief. |

### Part 4 — .NET API

| Decision | Instead of | Trade-off accepted |
| -------- | ---------- | ------------------ |
| Minimal APIs | Controllers | Seven routes over a thin BFF, and OpenAPI 3.1 is first-class in .NET 10. Controllers would add MVC conventions, filters and attribute routing for ceremony this surface does not need; the cost is that MVC-shaped extension points are not there if the surface grows. |
| The API never touches Postgres | Reading pgvector directly for simple lookups | An extra network hop, and MCP's availability becomes the API's. In exchange there is exactly one place where SQL lives, and MCP is the single query surface for every client. |
| `reader` may call only search | `reader` as "everything except stats" | Stricter than the brief asks. A richer catalog UI would need a broader reader role. |
| `IMemoryCache` | Redis or another distributed cache | The cache is per instance, so the hit rate falls as ECS scales out. No extra service to operate for a 60-second TTL over an idempotent read. |
| Rate limit partitioned on the JWT `sub` | Per IP, or global | Every caller sharing a client id shares the 60/minute budget. It also invalidated the k6 script until that derived its arrival rate from the configured limit. |
| `MCP_CLIENT=fake` for tests and local work | Always talking to a real MCP server | The default test path never exercises the SSE client, which is how the FastMCP envelope bug shipped. Now closed from both sides by `LiveMcpTests` and `test_dotnet_contract.py`. |
| `openapi.json` generated from the served document and asserted in CI | Maintaining it by hand | Every contract change needs `scripts/export_openapi.sh` re-run. Drift fails the build instead of accumulating. |
| The Compose healthcheck probes `/health`, not `/health/ready` | Probing readiness | The container reports healthy before MCP is reachable. Deliberate: `/health` is unconditionally 200 so Compose does not restart the API while it waits, and `depends_on` already enforces ordering. |
| `AWS_XRAY_ENABLED` switches the id generator and prepends `AWSXRayPropagator` to a composite | One exporter and one propagator for both environments | Two code paths, only one exercised locally. X-Ray rejects W3C-random trace ids, so the generator has to change too; keeping `tracecontext` in the composite is what lets the MCP server still join the trace. |

### Part 5 — Embedding Atlas (bonus)

| Decision | Instead of | Trade-off accepted |
| -------- | ---------- | ------------------ |
| Parquet export, with Atlas computing UMAP at startup (cosine, seed 42) | Precomputing and storing projections | ~3,200 points project in seconds on every container start; a materially larger corpus would need precompute. The fixed seed keeps the map stable across restarts, and cosine matches the HNSW space. |
| Patch `defaultChartsConfig.embedding.data.category` in-process | `initialState.charts`, a static export, or forking the CLI | Leans on third-party internals that a minor release could move, so it fails open to stock Atlas. `initialState.charts` suppresses the default charts entirely and would have cost the data table. |
| Restate the whole channel set in the patch | Passing `category` alone | Config that looks redundant. The frontend merge is shallow, so `{data: {category: …}}` replaces `data` wholesale and loses x, y and the tooltip columns. |
| Atlas polls for embeddings | `depends_on: pipeline: service_completed_successfully` | Ordering is not declared in Compose. A failed pipeline leaves Atlas up and logging what it is waiting for, rather than never starting. |
| Atlas is a reader only | Letting it seed or cache its own copy | Re-export needs `--force-recreate`. The 1.5 loader stays the only writer to `movies`. |

### Part 6 — Infrastructure and DevOps

| Decision | Instead of | Trade-off accepted |
| -------- | ---------- | ------------------ |
| ECS Fargate | EKS | No daemonsets, colder starts, and a compute module that is AWS-specific. Buys no control-plane cost, no node patching or cluster autoscaler, and task-level IAM without IRSA — for three long-lived services and two run-to-completion tasks. |
| `terraform/` is a composition module; the roots are `environments/{dev,prod}` | One root using workspaces | Two roots to keep in step, and `terraform/` alone cannot be applied. A single root cannot hold two backends and two provider configurations. |
| Dev is cost-shaped but structurally identical to prod | A minimal dev that omits components | One NAT gateway is a zonal single point of failure in dev, saving roughly $32/month per AZ. In exchange a dev plan is a genuine rehearsal for prod. |
| Four interface VPC endpoints plus an S3 gateway endpoint | Routing ECR, Logs and Secrets traffic through NAT | About $7/month each, repaid in NAT data processing once images are pulled regularly, and those calls never traverse the public internet. |
| Immutable ECR tags, git SHA, never `latest` | Mutable `latest` | A rollback needs the SHA. In exchange a tag names exactly one image forever. |
| `modules/rds` owns the database credential; `modules/secrets` owns the rest | One secrets module | Secrets live in two modules. Assembling `DATABASE_URL` needs the RDS endpoint, so one module would have created a secrets → rds → secrets cycle. |
| Every secret generated by `random_password` | Passing them in as variables | Rotation is manual and the values land in Terraform state, which is why the bucket is encrypted, versioned and private. No credential appears in a tfvars file, a CI variable or the repository. |
| A separate execution role and one task role per service | One shared role | More roles to manage. The execution role's secret access belongs to the ECS agent, so application code can never read a secret it was not injected with. |
| The GitHub deploy role carries `PowerUserAccess` plus IAM scoped to `movie-search-*` | Enumerating every resource type Terraform touches | The honest exception, mitigated by an OIDC trust policy pinned to one repository and to `main` or the dev/prod environments. Exhaustive policies of this kind tend to fail closed at the worst moment. |
| `wait_for_steady_state = false` | Blocking on steady state | An apply can succeed before the service is actually serving. On a first apply no image exists yet, and blocking turns a legible "cannot pull image" event into a fifteen-minute timeout; the deployment circuit breaker with rollback catches real bad deploys. |
| `desired_count` in `ignore_changes` | Managing it in Terraform | Terraform no longer reports drift on replica count, and stops fighting the autoscaler. |
| Alarm thresholds above the autoscaling targets | Alarming at the target | Scaling reacts first, so an alarm means scaling has already failed rather than that load arrived. |
| Ollama's model cached on EFS, 2 vCPU / 4 GiB, low scaling ceiling | Re-pulling the model per task | EFS adds cost and a slower cold read. Without it every task replacement re-downloads the model, turning a rolling deploy into minutes of unavailability; scaling this service out multiplies memory rather than throughput. |
| CloudWatch and X-Ray on AWS | Running Prometheus, Grafana and Jaeger on Fargate | Two observability stacks to know, and the API's `/metrics` endpoint goes unused on AWS. The alternative is three more services to operate for no signal the brief asks for. |
| Migrations run as an ECS `run-task` wrapped by `scripts/run_ecs_task.sh` | A Terraform resource, or a bare `aws ecs run-task` | A deploy-time script rather than declarative state. `run-task` is fire-and-forget, so a migration that exits 1 otherwise looks like a successful API call. |
| Prod promotes the image manifests dev validated | Rebuilding from the same commit | Needs `scripts/promote_images.sh`. Rebuilding is not the same guarantee, because base images move underneath a tag. |
| A `-target` apply creates ECR first | A single apply | A non-idiomatic step, and a no-op on every later run. It breaks the cycle where the push needs repositories the main apply has not created and the services need the images. |
| `dynamodb_table` and `use_lockfile` both set | One or the other | Transitional duplication. The brief requires DynamoDB locking and Terraform 1.11+ deprecates it in favour of S3 lockfiles; this is HashiCorp's documented migration path and locks either way. |
| CI's Compose job starts the whole platform and waits for the pipeline | Starting `api` and its dependency closure only | A slower job under real disk pressure — the atlas image alone is ~9.6 GB. It is the only place the embed-and-load path and the real SSE client are exercised. |
| `ruff check` and `mypy --strict src` gate CI; `ruff format --check` and mypy over tests do not | Adding both | Eight files across Parts 1–5 are not formatter-clean, and that is a live follow-up. Test fixtures and monkeypatching trip strict mode without saying anything about the artifacts that ship. |
| HTTPS stays off | Registering a domain so ACM can validate a certificate | Bearer tokens would cross the ALB in plaintext, which is a reason not to deploy it as it stands rather than an accepted risk — nothing is deployed. The module is complete and switches on with a certificate; see [§12](#12-terraform-deployment) and [§14](#14-known-limitations--future-improvements). |

### Library choices

The brief allows any additional libraries as long as the choices are documented.
Everything here is open-source and pinned in `pyproject.toml`, `*.csproj` or
`docker-compose.yml`.

| Where | Library | Why this one |
| ----- | ------- | ------------ |
| Pipeline | `pandas` + `numpy` | The transforms in 1.1–1.3 are column-wise operations over 3,201 rows; a dataframe is the shortest path and `pandas-stubs` keeps them type-checked. |
| Pipeline | `tenacity` | Declarative exponential backoff around the embedding HTTP calls, instead of a hand-rolled retry loop. |
| Pipeline | `pyarrow` | Parquet writer for the Atlas export — the compact format for 768-float lists. |
| Pipeline | `vega-datasets` | The dataset source the brief names. It fetches over the network at runtime, which is why the container needs egress. |
| Both Python services | `pydantic` + `pydantic-settings` | Typed models for tool inputs, outputs and stage reports, and environment-based configuration with validation rather than `os.environ` reads. |
| Both Python services | `httpx` | One async HTTP client for Ollama, with timeouts as first-class configuration. |
| Both Python services | `structlog` | JSON logs with `merge_contextvars`, which is what carries `trace_id` onto every line. |
| Both Python services | `asyncpg` + `pgvector` | Async driver with a real connection pool, and `register_vector` so a `vector(768)` round-trips as a Python list instead of a string. |
| MCP server | `fastmcp` (+ `starlette`, `uvicorn`) | The brief names FastMCP. Starlette and Uvicorn come with it and carry the `/health` route and the raw ASGI trace middleware. |
| API | `ModelContextProtocol` | The official C# MCP SDK, so the SSE client is not hand-written. |
| API | `Serilog.AspNetCore` + `Serilog.Formatting.Compact` | The brief names Serilog. `RenderedCompactJsonFormatter` on the console, `CompactJsonFormatter` to a daily rolling file. |
| API | `OpenTelemetry.*` (+ `Exporter.Prometheus.AspNetCore`, `Extensions.AWS`) | Traces, metrics and instrumentation from one SDK: OTLP to Jaeger, a Prometheus scrape endpoint, and the X-Ray id generator and propagator for production. |
| API | `Microsoft.AspNetCore.OpenApi` + `Swashbuckle.AspNetCore.SwaggerUI` | .NET 10 generates the OpenAPI 3.1 document natively but ships no UI, so Swashbuckle contributes the Swagger UI assets only. |
| API | `Microsoft.AspNetCore.Authentication.JwtBearer` + `System.IdentityModel.Tokens.Jwt` | Validation and issuing of the client-credentials JWTs. |
| API | `Microsoft.Extensions.Caching.Memory` | In-process response cache behind `CACHE_TTL_SECONDS`. |
| Tests | `xunit` + `Microsoft.AspNetCore.Mvc.Testing`, `pytest` + `pytest-asyncio` | The brief names xunit and pytest. `WebApplicationFactory` gives HTTP-level tests without a container. |
| Tooling | `uv`, `ruff`, `mypy`, `dotnet format`, `k6`, Flyway, Terraform | The gates CI runs, plus the two the brief names for load testing and migrations. `uv` resolves the two Python packages as one workspace. |

## 16. Requirements Coverage

A reviewer's index. Sections [§1](#1-architecture-diagram) to
[§14](#14-known-limitations--future-improvements) above are the fourteen README
sections the brief mandates, in its order and under its titles.

**Where the brief asks for a justification or documented reasoning**, each is
answered in the README rather than only in the reports:

| The brief asks | Answered in |
| -------------- | ----------- |
| 1.2 "clearly document your reasoning for each decision" on imputation | [§6](#6-data-decisions), per field, plus the trade-off register in [§15](#15-design-decisions--trade-offs) |
| 1.3 derived features "with documented rationale" | [§7](#derived-features) — four features against a minimum of two |
| 1.4 "document your choice and its embedding dimensionality" | [§7](#7-embedding-strategy) — `nomic-embed-text` v1.5 at 768 dimensions, and how the container is wired |
| Part 2 "Migrations managed via Flyway or Alembic (your choice, justify it)" | [§5](#flyway-not-alembic) |
| Part 2 "Include a documented query showing hybrid search" | [§5](#hybrid-query-vector-similarity--metadata-filters), with the SQL and its bind-parameter contract |
| Part 4 "Minimal API or Controller-based — justify your choice" | [§9](#9-api-documentation) and [§15](#part-4--net-api) |
| Part 6 "ECS (Fargate) or EKS — choose one and justify your decision" | [§12](#12-terraform-deployment) and [§15](#part-6--infrastructure-and-devops) |
| Constraints "You may use any additional libraries — document your choices" | [§15](#library-choices) |

**Constraints and rules:**

| Rule | State |
| ---- | ----- |
| Secrets via environment variables / secrets managers, never committed | `.env` is gitignored with a complete `.env.example`; on AWS every value comes from Secrets Manager. No credential is in the tree. |
| `docker compose up --build` starts everything, no manual step beyond `.env` | Verified from an empty Docker state — [§0](#0-status), [§3](#3-quick-start-5-commands). |
| Python 3.12+ · .NET 10 · PostgreSQL 16 with pgvector 0.7+ | [§2](#2-prerequisites). `pgvector/pgvector:pg16` tracks current pgvector. |
| No OpenAI or paid/hosted embedding API | Ollama serving `nomic-embed-text` as its own Compose service — [§7](#7-embedding-strategy). |
| Code passes the linting and type checking CI configures | `ruff`, `mypy --strict` on `src`, `dotnet format --verify-no-changes` — [§13](#13-running-tests), scope explained in [§15](#part-6--infrastructure-and-devops). |

**Deliverables, by part.** The tree follows the brief's repository structure —
`README.md`, `docker-compose.yml`, `openapi.json`, `pipeline/`, `mcp-server/`,
`api/`, `database/migrations/`, `scripts/`, `monitoring/`, `terraform/` and
`.github/workflows/` — with `reports/` added for the per-part decision
narratives and run artifacts.

| Part | README | Decisions report | Code |
| ---- | ------ | ---------------- | ---- |
| 1 Data pipeline | [§5](#5-data-pipeline), [§6](#6-data-decisions), [§7](#7-embedding-strategy) | [`reports/section-1.md`](reports/section-1.md) | `pipeline/` |
| 2 Vector database | [§5](#vector-database-part-2) | [`reports/section-2.md`](reports/section-2.md) | `database/migrations/`, `database/queries/` |
| 3 MCP server | [§8](#8-mcp-server) | [`reports/section-3.md`](reports/section-3.md) | `mcp-server/` |
| 4 .NET API | [§9](#9-api-documentation), [§10](#10-authentication), [§11](#11-observability) | [`reports/section-4.md`](reports/section-4.md) | `api/`, `openapi.json` |
| 5 Embedding Atlas (bonus) | [§4](#embedding-atlas-bonus) | [`reports/section-5.md`](reports/section-5.md) | `scripts/export_embeddings_atlas.py`, `scripts/atlas/` |
| 6 Infrastructure and DevOps | [§4](#4-service-endpoints), [§12](#12-terraform-deployment) | [`reports/section-6.md`](reports/section-6.md) | `docker-compose.yml`, `terraform/`, `.github/workflows/` |

**Submission:** the repository is public at
`github.com/francois-vz/movie-search-platform` and `docker compose up --build`
has been run from a clean Docker state ([§0](#0-status)). The 5–10 minute
walkthrough video is **not recorded** ⚠️, and it is the one outstanding
deliverable. All four beats it asks for — the pipeline producing output,
natural-language searches through the API, the Grafana dashboard, and the dev
`terraform plan` — have something real behind them.
