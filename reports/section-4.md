# Section 4 — .NET 10 Web API

Living report for Part 4. The API is a JWT-protected BFF over MCP; it does **not**
talk to Postgres. Part 3 can land independently: the API is built against
`IMovieSearchClient`, with a fake implementation for tests and local work.

The plan this part was built from: [plans/part-4-dotnet-api.plan.md](plans/part-4-dotnet-api.plan.md).

## Decisions

- **Minimal APIs** rather than controllers: seven routes, OpenAPI 3.1 is first-class
  in .NET 10, less ceremony for a thin BFF.
- **RBAC (strict):** `reader` may call only `GET /api/v1/movies/search`. `admin` may
  call every `/api/v1/*` route. Health, metrics, OpenAPI, Swagger, and `/auth/token`
  are anonymous.
- **Auth:** `POST /auth/token` client-credentials. Env clients `AUTH_READER_*` and
  `AUTH_ADMIN_*`. JWT claim `role` = `reader` | `admin`.
- **Get-by-id:** there is no `get_movie_by_title` mapping. The API calls
  **`get_movie_by_id(movie_id)`**.

## Ask for Part 3 — `get_movie_by_id` — **resolved**

Part 3 now registers this tool, so `GET /api/v1/movies/{id}` works against the
real MCP server and `MCP_CLIENT=fake` is no longer a workaround for it.

```python
@mcp.tool()
async def get_movie_by_id(movie_id: str) -> MovieResult | None:
    """Retrieve a specific movie by its unique identifier."""
```

Frozen DTO field set (snake_case on the MCP wire, camelCase on the REST API):

- `MovieResult`: `id`, `title`, `release_year`, `major_genre`, `mpaa_rating`,
  `director`, `distributor`, `imdb_rating`, `rt_rating`, `similarity`,
  and now `match_type` (`semantic` | `exact` | `fuzzy` | `lookup`) which says
  how to read `similarity`. `McpMovieDto` ignores unknown properties, so this
  is additive; map it into the REST DTO if it becomes useful to clients.
- `DatasetStats`: `total_movies`, `genres`, `year_min`, `year_max`, `avg_imdb_rating`

SSE endpoint expected by the .NET client: `{MCP_SERVER_URL}/sse`
(default `http://mcp-server:8000/sse`).

The mismatch was invisible to both test suites — .NET tests substitute
`FakeMovieSearchClient`, and the Python tests never read the C#.
`mcp-server/tests/test_dotnet_contract.py` now closes that hole from the Python
side: it parses `McpMovieSearchClient.cs` for every tool name and argument key
and asserts each exists in the FastMCP registry. A .NET-side integration test
against a live server is still worth adding.

## Layout

```
api/src/MovieSearch.Api             entry point, JWT, OpenAPI, rate limit, OTel
api/src/MovieSearch.Application     use cases + cache-aside decorator
api/src/MovieSearch.Domain          Movie, DatasetStats, SearchQuery, IMovieSearchClient
api/src/MovieSearch.Infrastructure  FakeMovieSearchClient, McpMovieSearchClient
api/tests/MovieSearch.Tests         WebApplicationFactory against the fake client
```

## Cross-cutting

- Response cache: `IMemoryCache` around MCP calls, TTL `CACHE_TTL_SECONDS` (default 60).
- Rate limit: 60/min per JWT `sub`.
- Timeout: 30s default.
- Serilog JSON console + `logs/api-.log`.
- OpenTelemetry traces → Jaeger OTLP; metrics → `/metrics` (Prometheus).
- Histogram `mcp_tool_call_duration` tagged with `mcp.tool`.

## How to run

```bash
# Tests (no MCP)
dotnet test api/MovieSearch.sln

# API only, fake MCP
MCP_CLIENT=fake docker compose run --no-deps --service-ports api

# Full stack (Compose waits for a healthy mcp-server)
docker compose up --build api
```
