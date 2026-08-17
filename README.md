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

| Part | Area | State |
| ---- | ---- | ----- |
| 1 | Data pipeline (clean → impute → augment → embed → load) | Complete, run end to end against live Ollama + Postgres |
| 2 | pgvector schema, Flyway migrations, hybrid query | Complete |
| 3 | FastMCP server, 6 tools | Complete |
| 4 | .NET 10 Web API | Complete |
| 5 | Embedding Atlas (bonus) | Complete, opens already coloured by Major Genre |
| 6 | Docker Compose, Terraform, CI/CD | Compose and CI/CD complete and verified; `terraform plan` clean against a real account, never applied ⚠️ |
| — | Walkthrough video | Not recorded ⚠️ |

**What is verified, by observation.** Full evidence log, including the five bugs
the first end-to-end run exposed and why the test suites could not see them:
[`reports/verification.md`](reports/verification.md). The platform has been
brought up from an empty Docker state (`docker compose down -v` then
`docker compose up --build`) and exercised the length of the chain:

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
  0 to destroy**, no errors or warnings. Nothing has been applied.
- p95 on search is **17ms** at the default 60/minute limit and **608µs** over
  4,795 requests at 80 req/s with the limit raised — against a 500ms target.
- `ruff`, `mypy` and `pytest` are green: 66 passed in `pipeline` and 64 in
  `mcp-server` with `PIPELINE_TEST_DSN`/`MCP_TEST_DSN` pointed at a throwaway
  pgvector container (62 + 4 skipped and 58 + 6 skipped without one). CI now
  provides that container, so all ten database-backed tests run there too.

**What is still not verified.** `terraform apply`. The dev plan is clean against a
real account, which raises [§12](#12-terraform-deployment) well above a
code-review claim — the plan resolves every data source and every value it
asserts — but no resource has been created, so nothing is proven to *run* on AWS.

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
│  │  5 semantic tools       │                                                 │
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

### Embedding Atlas (bonus)

`http://localhost:7000` is Apple Embedding Atlas over the Part 2 `movies`
vectors. The service polls until 1.5 has written embeddings, exports Parquet,
then runs UMAP (cosine, seed 42). Decisions: [`reports/section-5.md`](reports/section-5.md).

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
[`reports/section-1.md`](reports/section-1.md).

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

### Schema changes

Schema is applied by the Flyway `migrate` job. Flyway versions are forward-only,
so after editing `database/migrations/` reset the local volume:

```bash
docker compose down -v && docker compose up --build
```

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

The public API is **.NET 10 Minimal APIs** (not controllers): seven routes, first-class
OpenAPI 3.1, and little ceremony for a BFF that only orchestrates MCP tools.

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
| Logs | JSON on the API container stdout (Serilog `RenderedCompactJsonFormatter`); rolling files at `/app/logs/api-*.log`. The MCP server logs structured JSON via structlog. The pipeline logs plain text to stdout and `reports/pipeline.log`. |
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
timestamp in their prefix. ⚠️ Never observed in X-Ray itself — no AWS account.

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

**1. Bootstrap the state backend** (once per AWS account):

```bash
cd terraform/bootstrap
terraform init
terraform apply -var=aws_region=eu-west-1
terraform output   # note the bucket name: movie-search-tfstate-<account-id>
```

This is the only configuration in the repo that keeps state locally. It creates
a versioned, encrypted, public-access-blocked S3 bucket and a
point-in-time-recovery DynamoDB lock table, both with `prevent_destroy`.

**2. Configure the environment root:**

```bash
cd ../environments/dev
cp backend.hcl.example backend.hcl              # fill in the bucket from step 1
cp terraform.tfvars.example terraform.tfvars    # region, TLS, alarm email
```

Both files are gitignored: the bucket name embeds the AWS account id. For TLS,
set either `certificate_arn` (an existing ACM certificate) or `domain_name` +
`route53_zone_id` (Terraform requests and DNS-validates one). With neither, the
ALB serves HTTP only and the plan says so.

**3. Plan:**

```bash
terraform init -backend-config=backend.hcl
terraform plan
```

**4. Create the ECR repositories and push images.** The services need images
that do not exist yet on a fresh account, so apply the registry module alone
first — a no-op on every later run:

```bash
terraform apply -target=module.platform.module.ecr
aws ecr get-login-password --region eu-west-1 \
  | docker login --username AWS --password-stdin <account>.dkr.ecr.eu-west-1.amazonaws.com

TAG=$(git rev-parse --short=12 HEAD)
for svc in api mcp-server pipeline; do
  docker buildx build --push \
    -t <account>.dkr.ecr.eu-west-1.amazonaws.com/movie-search-dev/$svc:$TAG ./$svc
done
docker buildx build --push \
  -t <account>.dkr.ecr.eu-west-1.amazonaws.com/movie-search-dev/migrate:$TAG ./database
```

Tags are the 12-character git SHA because the repositories are tag-immutable: a
tag names exactly one image, so a rollback is a redeploy of an older SHA rather
than a re-tag.

**5. Apply:**

```bash
terraform apply -var="image_tag=$TAG"
```

**6. Migrate the schema and seed the data.** Both are run-to-completion ECS
tasks; the helper reads the `awsvpc` configuration from the Terraform outputs
and waits for the task to exit:

```bash
# still in terraform/environments/dev
terraform output -json run_task_network_configuration > /tmp/netcfg.json
CLUSTER=$(terraform output -raw ecs_cluster_name)
SCRIPTS=../../../scripts

"$SCRIPTS"/run_ecs_task.sh "$CLUSTER" "$(terraform output -raw migrate_task_definition_arn)"  /tmp/netcfg.json
"$SCRIPTS"/run_ecs_task.sh "$CLUSTER" "$(terraform output -raw pipeline_task_definition_arn)" /tmp/netcfg.json
```

`run_ecs_task.sh` exists because `aws ecs run-task` is fire-and-forget: it
returns as soon as the task is accepted, so a migration that exits 1 still looks
like a successful API call. The helper waits for the task to stop, reads the
container exit code and surfaces the stop reason.

**7. Verify:**

```bash
terraform output api_url
BASE_URL=$(terraform output -raw api_url) "$SCRIPTS"/smoke_test.sh
terraform output -raw cloudwatch_dashboard_url
```

Prod is the same sequence in `environments/prod`, but CD promotes the exact
digests dev validated rather than rebuilding — see
[§CI/CD](#cicd) below.

**Teardown:** `terraform destroy`. Dev sets `db_deletion_protection = false` so
this succeeds; prod does not, by design.

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

⚠️ `terraform fmt -check` and `validate` pass on all four roots, and a dev
`terraform plan` against a real account is clean — 143 to add, 0 to change, 0 to
destroy, no warnings — which is where the resolved values above come from rather
than from reading HCL. The exception is the HTTPS row: with no certificate the
plan plans a single port-80 listener, exactly as described above. **Never
applied**, so there is no cost figure and no confirmation that the ECS task
definitions start cleanly. Evidence:
[`reports/verification.md`](reports/verification.md#terraform-against-a-real-aws-account).

### CI/CD

**`ci.yml`** runs on every pull request to `main`, in four parallel jobs:

- **Python** — `ruff check`, `mypy` on both `pipeline` and `mcp-server`, then
  `pytest` on each.
- **.NET** — `dotnet format --verify-no-changes`, then `dotnet test` in Release.
- **Docker** — builds every image with `docker buildx bake` (GitHub Actions
  layer cache), brings the stack up with `docker compose up -d --wait api`, and
  runs `scripts/smoke_test.sh` against it. The `pipeline` and `atlas` data jobs
  are excluded: both embed the full dataset, which would dominate CI runtime
  without testing anything the smoke test does not already cover.
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

- **`terraform apply` has never run.** The dev plan is clean (143 to add, no
  errors, no warnings) against a real account, and it confirms the resolved
  values §12 claims — RDS private and encrypted, flow logs on all traffic, CPU
  and memory autoscaling on every service. What a plan cannot prove is that the
  resources come up and talk to each other. This is the one remaining gap of
  consequence.
- The plan ran with the S3 backend temporarily overridden to a local one, because
  `terraform/bootstrap` has not been applied, so the state bucket and DynamoDB
  lock table do not exist yet. The backend and locking configuration is therefore
  still unexercised.
- CI's `terraform plan` step needs the OIDC role, so on a fork it is skipped. It
  now emits a warning annotation and a run-summary note rather than passing
  quietly as though all three checks ran.
- X-Ray trace-id generation and propagation are verified locally (see
  [§11](#11-observability)) but have never been seen in X-Ray itself.
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
