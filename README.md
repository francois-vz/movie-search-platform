# Intelligent Movie Search Platform

An end-to-end semantic movie search system: a Python data pipeline vectorizes the
Vega movies dataset into pgvector, a FastMCP server exposes semantic search tools,
and a .NET 10 Web API serves secured, observable endpoints to clients. The whole
platform runs locally via Docker Compose and deploys to AWS via Terraform.

> Status: Part 4 (.NET 10 API) is implemented against a fake MCP client so it can
> land in parallel with Part 3. Set `MCP_CLIENT=mcp` (Compose default) once the
> FastMCP server is healthy. Other README sections are still filled in as each
> part lands.

---

## 1. Architecture Diagram

```
Data Pipeline (Python) --> pgvector (PostgreSQL 16) --> MCP Server (FastMCP) --> .NET 10 API --> client
                                  ^                                                   |
                            Embedding Atlas (bonus)                     Observability: Prometheus / Grafana / Jaeger
```

<!-- TODO: replace with detailed ASCII/image diagram -->

## 2. Prerequisites

<!-- TODO: exact versions -->
- Docker + Docker Compose
- Python 3.12+
- .NET 10 SDK
- Terraform
- PostgreSQL 16 + pgvector 0.7+ (via container)

## 3. Quick Start (≤5 commands)

```bash
git clone <repo-url> && cd movie-search-platform
cp .env.example .env
docker compose up --build
docker compose run --rm pipeline   # ingest + embed the dataset
# open http://localhost:8080/swagger
```

## 4. Service Endpoints

| Service     | URL                        | Port  |
| ----------- | -------------------------- | ----- |
| .NET API    | http://localhost:8080      | 8080  |
| MCP server  | http://localhost:8000      | 8000  |
| Embeddings  | http://localhost:8001      | 8001  |
| Postgres    | localhost:5432             | 5432  |
| Prometheus  | http://localhost:9090      | 9090  |
| Grafana     | http://localhost:3000      | 3000  |
| Jaeger      | http://localhost:16686     | 16686 |
| Atlas       | http://localhost:7000      | 7000  |
| Swagger UI  | http://localhost:8080/swagger | 8080 |
| OpenAPI     | http://localhost:8080/openapi/v1.json | 8080 |
| Prometheus metrics | http://localhost:8080/metrics | 8080 |

### Embedding Atlas (bonus)

`http://localhost:7000` is Apple Embedding Atlas over the Part 2 `movies`
vectors. The service polls until 1.5 has written embeddings, exports Parquet,
then runs UMAP (cosine, seed 42). Decisions: [`reports/section-5.md`](reports/section-5.md).

**Colour by genre:** Color by Field → `major_genre`.

**How to read it:** same-colour blobs are genres that cluster in embedding space
(Action vs Drama). Mixed neighbourhoods are genre-ambiguous plots or thin
augmented text. Isolated points are outliers — titles whose nearest neighbours
are not their billed genre. Cross-check with MCP `get_similar_movies`.

## 5. Data Pipeline
<!-- TODO: how it works, how to re-run, how to verify -->

1.1 cleaning (no database): `docker compose run --rm --no-deps pipeline`.
Schema is applied by the Flyway `migrate` job. After editing
`database/migrations/`, reset local Postgres with `docker compose down -v`.

## 6. Data Decisions
<!-- TODO: imputation strategies chosen and why -->

## 7. Embedding Strategy
<!-- TODO: model choice + rationale, container wiring, text construction, dimensionality -->

## 8. MCP Server

FastMCP on port 8000 (SSE by default). Five tools; optional hybrid filters are
parsed from the query when the caller omits them. Full decisions:
[`reports/section-3.md`](reports/section-3.md).

| Tool | What it does |
| ---- | ------------ |
| `search_movies_by_description` | Semantic search + genre / decade / min IMDB / MPAA |
| `get_movie_by_title` | Exact then trigram fuzzy match |
| `get_similar_movies` | Nearest neighbours of a movie UUID |
| `list_genres` | Distinct `major_genre` values |
| `get_dataset_stats` | Counts, year range, average IMDB |

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

Search returns `[]` until `docker compose run --rm pipeline` has loaded
embeddings (Part 1.4 / 1.5). Unit tests: `cd mcp-server && pytest`.


## 9. API Documentation

The public API is **.NET 10 Minimal APIs** (not controllers): seven routes, first-class
OpenAPI 3.1, and little ceremony for a BFF that only orchestrates MCP tools.

Frozen spec: [`openapi.json`](openapi.json) (repo root) and live at
`http://localhost:8080/openapi/v1.json`. Swagger UI: `http://localhost:8080/swagger`.

The API never talks to Postgres. It calls FastMCP over SSE (`MCP_SERVER_URL`).
While Part 3 is incomplete, set `MCP_CLIENT=fake` to serve deterministic fixtures.

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
| Logs | JSON on the API container stdout; rolling files under `/app/logs` (Serilog) |
| Traces | Jaeger UI `http://localhost:16686` (OTLP gRPC `jaeger:4317`). Trace context is propagated on MCP HTTP calls. |
| Metrics | Prometheus `http://localhost:9090` scrapes `api:8080/metrics`. Grafana `http://localhost:3000` (admin/admin from `.env`) loads the **Movie Search** dashboard: request rate, latency p50/p95/p99, 5xx rate, MCP tool latency, active connections. |

## 12. Terraform Deployment
<!-- TODO: step-by-step AWS deployment guide -->

## 13. Running Tests

```bash
# Unit + WebApplicationFactory tests (fake MCP, no Docker required once the .NET 10 SDK is installed)
dotnet test api/MovieSearch.sln

# CI equivalent
dotnet format api/MovieSearch.sln --verify-no-changes
dotnet test api/MovieSearch.sln --configuration Release

# Load test against a running API (p95 < 500ms on search). Needs k6 and a live stack
# (or MCP_CLIENT=fake).
k6 run scripts/load_test.js
```

## 14. Known Limitations & Future Improvements

- `GET /api/v1/movies/{id}` calls MCP `get_movie_by_id`, which is not in the original
  five-tool brief. Part 3 needs to add it (`reports/section-4.md`). Until then, run
  the API with `MCP_CLIENT=fake`.
- Reader tokens are search-only; a richer catalog UI would need a broader reader role.
- Load-test p95 < 500ms is a full-stack check (`k6 run scripts/load_test.js`) and
  depends on a healthy MCP server plus embeddings.
- Atlas (`:7000`) stays waiting / unhealthy until the 1.5 loader writes
  `movies.embedding`. There is no separate seed.
