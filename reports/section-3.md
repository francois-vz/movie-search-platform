# Section 3 — Python MCP Server (FastMCP)

Living report for the FastMCP server (Part 3 of the assessment). Tools live in
`mcp-server/src/server/tools.py`; SQL is loaded from `mcp-server/src/server/sql/`
(the hybrid query is a copy of `database/queries/hybrid_search.sql`).

**How to run**

```bash
docker compose up -d postgres migrate embeddings mcp-server
curl -s http://localhost:8000/health
```

`mcp-server` waits on `migrate` (schema) and `embeddings` (Ollama). Search
returns an empty list until the 1.5 loader writes embeddings. Unit tests do not
need Docker:

```bash
cd mcp-server && uv pip install -e ".[dev]" && pytest
```

---

## Tools (3.1)

Signatures match the brief. Empty corpus / unknown id → empty list or `None`,
not an error. `top_k` is clamped to 1–50.

| Tool | Behaviour |
| ---- | --------- |
| `search_movies_by_description` | Parse filters → embed `search_query: {query}` → `hybrid_search.sql` |
| `get_movie_by_title` | Exact `lower(title)` then pg_trgm `title % $1` |
| `get_similar_movies` | Vector kNN excluding `movie_id`; invalid UUID → `[]` |
| `list_genres` | Distinct non-null `major_genre`, sorted |
| `get_dataset_stats` | Count, distinct genres, min/max year, avg IMDB |

`MovieResult.title` is `str`; a null DB title becomes `""` (the untitled 2006
row). UUIDs are returned as strings.

---

## Hybrid SQL

Part 2 bind params `$1`–`$6` are unchanged. The SELECT list was widened to
`MovieResult` columns (`release_year`, `mpaa_rating`, `director`, `distributor`,
`rt_rating`). The MCP image build context is `./mcp-server`, so the file is
copied to `mcp-server/src/server/sql/hybrid_search.sql`.
`tests/test_sql_sync.py` asserts the copy matches the canonical file.

---

## NL filter extraction

When genre / decade / min IMDB / MPAA are omitted, they are parsed from `query`.
Explicit arguments always win.

| Cue | Filter |
| --- | ------ |
| Vega major-genre phrases (`action`, `drama`, `thriller`, …) | `genre_filter` |
| `90s` / `1990s` / `nineties` | `decade=1990` |
| `high IMDB` / `highly rated` / `critically acclaimed` | `min_imdb_rating=7.5` |
| `PG-13`, `R-rated`, … | `mpaa_rating` |

Director, distributor, budget, Rotten Tomatoes, sci-fi, animated, and family
are **not** SQL filters. They are not Vega `major_genre` values (sci-fi is
Creative Type) and they are not in the tool signature. They ride on the
embedding because they appear in the 1.3 `augmented_text` template.

3.3 mapping:

| Query | Extracted | Left to embedding |
| ----- | --------- | ----------------- |
| action movies from the 90s with high IMDB ratings | Action, 1990, 7.5 | — |
| critically acclaimed drama films with small budgets | Drama, 7.5 | small budgets |
| animated family movies distributed by Disney | — | animated, family, Disney |
| sci-fi films directed by James Cameron | — | sci-fi, James Cameron |
| dark psychological thrillers with low Rotten Tomatoes scores | Thriller/Suspense | dark, psychological, low RT |

---

## Server (3.2)

- **Transport:** `MCP_TRANSPORT` (default `sse`). `stdio` is supported for
  local MCP clients. Production can switch to FastMCP HTTP without code changes.
- **Pool:** asyncpg, `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE`,
  `pgvector.asyncpg.register_vector` on connect.
- **Health:** `GET /health` — 200 after `SELECT 1`, else 503. The image
  installs `curl` so Compose's healthcheck works.
- **Logging:** structlog JSON (`tool`, `duration_ms`, `status`, `trace_id`).
  `TraceIdMiddleware` binds W3C `traceparent` (or `x-request-id`, or a generated
  id) so Part 4 can propagate context later.
- **Config:** `mcp-server/src/config.py` — no hardcoded DSNs or model names.

Embeddings: Ollama `POST /api/embed` with `search_query:` prefix (pipeline 1.4
will store `search_document:`). Dimension is asserted against `EMBEDDING_DIM`
(768). The client is duplicated here rather than shared with the pipeline —
separate images.

---

## Follow-ups (not Part 3)

- **1.4 / 1.5** must write embeddings before live 3.3 queries return ranked
  hits. Until then `/health` is green and tools return empty results.
- **Part 4** calls these tools over SSE (`MCP_SERVER_URL`).
