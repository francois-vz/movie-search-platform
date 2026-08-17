# Section 3 — Python MCP Server (FastMCP)

Living report for the FastMCP server (Part 3 of the assessment). Tools live in
`mcp-server/src/server/tools.py`; SQL is loaded from `mcp-server/src/server/sql/`
(the hybrid query is a copy of `database/queries/hybrid_search.sql`).

The plan this part was built from: [plans/part-3-mcp-server.plan.md](plans/part-3-mcp-server.plan.md).

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
not an error. `top_k` is clamped to `[1, MCP_TOP_K_MAX]`.

| Tool | Behaviour |
| ---- | --------- |
| `search_movies_by_description` | Parse filters → embed `search_query: {query}` → `hybrid_search.sql` |
| `get_movie_by_title` | Exact `lower(title)` then pg_trgm `title % $1` |
| `get_movie_by_id` | Direct lookup on the UUID primary key; invalid UUID → `None` |
| `get_similar_movies` | Vector kNN excluding `movie_id`; invalid UUID → `[]` |
| `list_genres` | Distinct non-null `major_genre`, sorted |
| `get_dataset_stats` | Count, distinct genres, min/max year, avg IMDB |

`MovieResult.title` is `str`; a null DB title becomes `""` (the untitled 2006
row). UUIDs are returned as strings.

### `get_movie_by_id` (the sixth tool)

The brief lists five tools, and this is a sixth. It exists because Part 4's
`GET /api/v1/movies/{id}` needs it: `McpMovieSearchClient.GetByIdAsync` calls
`get_movie_by_id(movie_id)`, and until now that tool did not exist, so the
endpoint failed against the real server while passing its own tests (they run
against a fake client). `section-4.md` asked for it; this closes the request.

`movie_by_id.sql` is a primary-key lookup, not a search, so `similarity` is
`NULL` and `match_type` is `'lookup'`.

**The test that keeps it honest.** `tests/test_dotnet_contract.py` reads
`McpMovieSearchClient.cs`, extracts every `CallAsync("…")` tool name and every
`["…"] =` argument key, and asserts each one exists in the live FastMCP
registry. A mismatch between the C# and the Python is now a failing Python
test rather than a 500 in production. This is the specific class of bug that
neither test suite could see on its own.

### Match semantics

`similarity` previously meant three different things depending on which tool
produced the row: cosine similarity from vector search, trigram similarity from
a fuzzy title match, and `NULL` from an exact one. A client sorting or
thresholding on that field was comparing incomparable numbers.

Every row now carries `match_type` alongside it:

| `match_type` | Produced by | `similarity` is |
| ------------ | ----------- | --------------- |
| `semantic` | `search_movies_by_description`, `get_similar_movies` | cosine similarity, `1 - (embedding <=> $1)` |
| `exact` | `get_movie_by_title` (exact hit) | `1.0` — a perfect match should outrank a fuzzy one |
| `fuzzy` | `get_movie_by_title` (trigram fallback) | pg_trgm `similarity(title, $1)` |
| `lookup` | `get_movie_by_id` | `NULL` — nothing was matched |

The .NET DTO deserializes with `JsonNamingPolicy.SnakeCaseLower` and ignores
unknown properties, so adding the field did not require an API change.

### Input validation (Pydantic v2)

The brief asks for Pydantic v2 models for tool inputs **and** outputs. Outputs
were modelled; inputs were plain typed arguments.

Tools still take flat, named parameters — that is the MCP convention and what
the .NET client sends — but each one now validates through a model in
`models.py` (`SearchMoviesInput`, `TitleLookupInput`, `MovieIdInput`,
`SimilarMoviesInput`). A single nested model argument would have been the more
literal reading of the brief, but it would change every tool call to
`{"input": {…}}` and break the .NET client for no gain.

Constraints live only in the models: non-empty `query` and `title`,
`min_imdb_rating` in `[0, 10]`, `decade` in `[1880, 2100]`, and `extra="forbid"`
so a typo'd argument name is an error rather than a silently ignored filter.
The signatures carry `Field(description=…)` only, which is what reaches the
JSON schema an LLM caller reads.

`top_k` is deliberately *not* constrained in the model. It is clamped instead:
asking for 1,000 results returns the maximum rather than an error, which is
friendlier for an LLM caller that cannot read the schema's bounds reliably.

---

## Hybrid SQL

Part 2 bind params `$1`–`$6` are unchanged. The SELECT list was widened to
`MovieResult` columns (`release_year`, `mpaa_rating`, `director`, `distributor`,
`rt_rating`, `match_type`). The MCP image build context is `./mcp-server`, so
the file is copied to `mcp-server/src/server/sql/hybrid_search.sql`.
`tests/test_sql_sync.py` asserts the copy matches the canonical file.

### Testing the SQL, not just its text

Three layers, cheapest first:

| Test | Runs | Catches |
| ---- | ---- | ------- |
| `test_sql_sync.py` | always | the two `hybrid_search.sql` copies drifting apart |
| `test_sql_contract.py` | always | a query that omits a column `row_to_movie` indexes, or forgets its `match_type` |
| `test_sql_execution.py` | with `MCP_TEST_DSN` | **invalid SQL** — plus ranking, filters, and fuzzy fallback against real pgvector |

The first two are string matching. They pin the contract but would pass on SQL
Postgres cannot parse, which was the honest weakness of the original contract
tests. The third applies V1/V2 to a throwaway database, seeds three rows with
768-dim vectors, and runs every query through asyncpg and `row_to_movie`:

```bash
docker compose up -d postgres
MCP_TEST_DSN=postgresql://movies:change_me_local_only@localhost:5432/movies pytest
```

It TRUNCATEs `movies`, so never point it at a database that matters. It skips
by default and has **not** been run here — no Docker daemon on this machine.

---

## NL filter extraction

When genre / decade / min IMDB / MPAA are omitted, they are parsed from `query`.
Explicit arguments always win.

| Cue | Filter |
| --- | ------ |
| Vega major-genre phrases (`action`, `drama`, `thriller`, …) | `genre_filter` |
| `90s` / `1990s` / `nineties` | `decade=1990` |
| `high IMDB` / `highly rated` / `critically acclaimed` | `min_imdb_rating=HIGH_IMDB_THRESHOLD` (default 7.5) |
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
- **Config:** `mcp-server/src/config.py`. See below.

### Trace correlation

`TraceIdMiddleware` binds the caller's W3C `traceparent` (or `x-request-id`, or
a generated id) into structlog contextvars, and `merge_contextvars` puts it on
every line. That was reported here as covering tool logs. It did not: under SSE
the tool body runs in the stream's task, not in the POST that delivered the
message, so the middleware's binding is frequently not visible by the time a
tool executes — and under `stdio` there is no HTTP request at all.

`_tool_span` now resolves the id itself. If one is already bound it is left
alone, so an HTTP-derived id still wins; otherwise it reads `traceparent` /
`x-request-id` from FastMCP's request context and falls back to a generated id.
No tool log line is uncorrelated, and none is silently attributed to the wrong
request. Both paths are covered in `tests/test_tool_contracts.py`.

### Configuration

Previously claimed as "no hardcoded values", which held for DSNs and model
names but not for three decisions that are policy rather than structure:

| Value | Was | Now |
| ----- | --- | --- |
| "highly rated" rating floor | `HIGH_IMDB_THRESHOLD = 7.5` in `filters.py` | `HIGH_IMDB_THRESHOLD` env var |
| `top_k` ceiling | `TOP_K_MAX = 50` in `tools.py` | `MCP_TOP_K_MAX` env var |
| Embedding HTTP timeout | `timeout=60.0` in `embeddings.py` | `EMBEDDING_TIMEOUT_SECONDS` env var |

`TOP_K_MIN = 1` and the default `top_k` of 10 stay in code: one is a structural
invariant, the other is fixed by the brief. `get_settings()` is now
`lru_cache`d because tools read it on every call.

Embeddings: Ollama `POST /api/embed` with `search_query:` prefix (pipeline 1.4
will store `search_document:`). Dimension is asserted against `EMBEDDING_DIM`
(768). The client is duplicated here rather than shared with the pipeline —
separate images.

---

## Follow-ups (not Part 3)

- **Part 4** calls these tools over SSE (`MCP_SERVER_URL`). The tool-name and
  argument contract is now enforced from the Python side
  (`test_dotnet_contract.py`), but nothing yet exercises a real SSE handshake
  end to end.
- The 3.3 ranking quality remains unmeasured: it needs a live Ollama and a
  loaded corpus, neither of which has run on this machine. Filter extraction is
  fully tested; what the embedding half retrieves is not.
