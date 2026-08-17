# Section 4 — .NET 10 Web API

Living report for Part 4. The API is a JWT-protected BFF over the MCP server; it
does **not** talk to Postgres. Everything below the transport is reached through
`IMovieSearchClient`, which has a fake implementation for tests and local work.

The plan this part was built from: [plans/part-4-dotnet-api.plan.md](plans/part-4-dotnet-api.plan.md).

---

## Decisions

### Minimal APIs, not controllers

The brief asks for a justification either way. Seven routes, no model binding
beyond query strings, no view concerns and no filters worth inheriting — that is
below the threshold where controller conventions repay their ceremony. .NET 10's
OpenAPI generation treats endpoint metadata as first-class, so `TypedResults` plus
`Produces` gives an accurate document without attribute plumbing, and route groups
carry the auth policy, rate-limit policy and shared 429 metadata for all six
`/api/v1` routes in one place.

The trade is real: controllers would give model-state validation and a more
familiar place for cross-cutting filters if this grew a write surface. For a
read-only façade over six MCP tools, they would be scaffolding around nothing.

### A BFF that owns no data

The API holds no database connection. Every read goes through the MCP server, which
means the vector query, the filter parsing and the embedding call live in exactly
one place rather than being reimplemented in C#. It also matches the flow the brief
draws — pipeline → pgvector → MCP → API — instead of quietly bypassing the middle.

The cost is one more network hop on the critical path and a hard dependency for
readiness. Both are visible: `mcp_tool_call_duration` measures the hop, and
`/health/ready` fails when MCP is unreachable.

### Caching as a decorator, not a concern inside the client

`CachingMovieSearchClient` wraps whichever `IMovieSearchClient` is registered.
Neither the MCP client nor the fake knows caching exists, and the cache cannot
drift between them. The alternative — caching inside `McpMovieSearchClient` — would
have left the fake uncached and the tests exercising a different code path than
production.

### `get_movie_by_id` is a sixth MCP tool

The brief lists five tools and none of them retrieves by id, but
`GET /api/v1/movies/{id}` needs exactly that. Resolving it by title would be wrong:
titles are neither unique nor stable, and the id in the URL is the UUID primary key
the search results already return. Part 3 registers the extra tool; reasoning in
[`section-3.md`](section-3.md#get_movie_by_id-the-sixth-tool).

---

## 4.1 Endpoints

| Route | Auth | Notes |
| ----- | ---- | ----- |
| `GET /health` | anonymous | Liveness. Unconditionally 200 while the process is up |
| `GET /health/ready` | anonymous | Readiness. 503 when the MCP server cannot be reached |
| `GET /api/v1/movies/search` | reader or admin | Natural-language search with filters |
| `GET /api/v1/movies/{id}` | admin | By UUID; 404 when unknown |
| `GET /api/v1/movies/{id}/similar` | admin | kNN excluding the seed |
| `GET /api/v1/movies/genres` | admin | Distinct `major_genre` |
| `GET /api/v1/stats` | admin | Dataset statistics |
| `POST /auth/token` | anonymous | Client-credentials token issue |
| `GET /metrics` | anonymous | Prometheus scrape |

Search parameters are the brief's: `q` (required), `top_k` (default 10, **max 50**,
clamped rather than rejected), `genre`, `min_imdb_rating`, `mpaa_rating`, `decade`.

**Liveness and readiness are split**, which the brief's single `GET /health` line
does not require. One probe cannot serve both purposes: a liveness check that fails
when a *dependency* is down invites the orchestrator to kill a perfectly healthy
process, while a readiness check that ignores dependencies routes traffic into
guaranteed 502s. Compose and ECS both probe `/health` and gate traffic on
`/health/ready`.

---

## 4.2 Authentication and authorization

`POST /auth/token` implements client credentials against two configured clients —
`AUTH_READER_*` and `AUTH_ADMIN_*` — and returns a JWT carrying a `role` claim of
`reader` or `admin`. Tokens live `JWT_EXPIRY_MINUTES` (default 60) and are signed
HS256 with `JWT_SIGNING_KEY`.

**Symmetric HS256, not RS256.** The issuer and the validator are the same process,
so an asymmetric pair would add key distribution and a JWKS endpoint to protect
nothing: there is no third party that needs to verify a token without being able to
mint one. If token issuing ever moved to a real identity provider, RS256 becomes the
right answer immediately, and the change is confined to `TokenService` plus the
`TokenValidationParameters`. On AWS the signing key is a `random_password` in
Secrets Manager injected as a task secret, so it is never in a tfvars file, a CI
variable or the repository.

**RBAC is read strictly.** The brief says *reader (search only)* and *admin (stats +
all endpoints)*, so `reader` may call `GET /api/v1/movies/search` and nothing else —
not genres, not by-id. The looser reading, where reader gets everything except
stats, would make the word "only" mean nothing. Two policies express it:
`ReaderOrAdmin` on search, `AdminOnly` on the other four.

`/health`, `/health/ready`, `/metrics`, `/openapi/v1.json`, `/swagger` and
`/auth/token` are anonymous by necessity — a probe or a scraper cannot hold a token,
and requiring one to obtain one is a bootstrap paradox.

**Failures are `application/problem+json`.** `JwtBearerEvents.OnChallenge` and
`OnForbidden` are overridden because the framework default returns an empty 401 with
a `WWW-Authenticate` header, which tells a client nothing. 401, 403, 404, 429 and
500 all carry a ProblemDetails body, and the 403 says explicitly that reader may
only call search. `ClockSkew` is 30 seconds rather than the 5-minute default, which
is generous for containers sharing a host clock and keeps a revoked-by-expiry token
from lingering.

---

## 4.3 Architecture

The brief's four-project layout, with the tests alongside:

```
api/src/MovieSearch.Api             entry point, JWT, OpenAPI, rate limit, OTel
api/src/MovieSearch.Application     use cases + cache-aside decorator
api/src/MovieSearch.Domain          Movie, DatasetStats, SearchQuery, IMovieSearchClient
api/src/MovieSearch.Infrastructure  FakeMovieSearchClient, McpMovieSearchClient
api/tests/MovieSearch.Tests         WebApplicationFactory, contract and live-MCP tests
```

**`IMovieSearchClient` is declared in Domain, not Infrastructure.** That is the
decision that makes the layering real rather than decorative: the arrow points
inward, so Application depends on the interface, Infrastructure implements it, and
only `Api` — the composition root — knows which implementation is registered. It is
why `MCP_CLIENT=fake` is a configuration switch instead of a code change, and why the
entire HTTP surface can be tested without an MCP server running.

The brief puts tests at `src/MovieSearch.Tests`; they live at
`api/tests/MovieSearch.Tests` here, which keeps `src/` to shipped code and matches
the convention the Python packages already follow in this repository.

---

## 4.4 Observability

- **Serilog** to console as JSON (`RenderedCompactJsonFormatter`) and to a rolling
  file sink at `logs/api-.log` (`CompactJsonFormatter`), as the brief asks, plus
  `UseSerilogRequestLogging()` for one completion line per request.
- **Logs join to traces without an enricher.** Serilog 3 populates
  `LogEvent.TraceId` and `SpanId` from the ambient `Activity`, and both compact
  formatters render them as the format's standard `@tr` and `@sp` fields. Observed
  on a live request: `"@tr": "eabe1576fb374cbe2ab15464006763cf"`,
  `"@sp": "e9f0f904fae2ba51"` on both the Kestrel and the request-completion lines,
  matching the trace in Jaeger. Worth stating because the configuration reads as
  though correlation is missing — there is no `Enrich.WithSpan()` and no
  `Serilog.Enrichers.Span` dependency — and adding one would duplicate what the
  formatter already emits.
- **OpenTelemetry traces** over OTLP to Jaeger locally. ASP.NET Core and
  `HttpClient` instrumentation, plus a manual span per MCP tool call.
- **Metrics** at `/metrics` in Prometheus format, including
  `mcp_tool_call_duration` tagged by `mcp.tool`.
- **Trace context propagation** to the Python MCP server over W3C `traceparent`.
  One Jaeger trace spans `GET /api/v1/movies/search` →
  `mcp.search_movies_by_description` → the MCP server, and the server's structlog
  JSON carries the same `trace_id`.
- **Grafana dashboard** at `monitoring/grafana/dashboards/movie-search.json`, with
  the five panels the brief names: request rate, latency p50/p95/p99, error rate
  (5xx), MCP tool call latency, and active requests/connections — the last built
  from `http_server_active_requests` and `kestrel_active_connections`, which are
  the two different things "active connections" can mean, so the panel shows both.

### Production tracing switches to X-Ray

`AWS_XRAY_ENABLED` (default false) swaps in an X-Ray-compatible id generator via
`AddXRayTraceId()` and puts `AWSXRayPropagator` first in a composite propagator.

Both halves are necessary and the reason is not obvious: X-Ray **rejects**
W3C-random trace ids, because it requires the first 8 hex characters to be the
request timestamp in epoch seconds. So the id generator has to change, not just the
exporter. The composite keeps `tracecontext` alongside the AWS propagator so the
MCP server — which only understands `traceparent` — still joins the same trace. It
is off locally so Jaeger keeps ordinary W3C ids, and the ECS task definition sets it
on.

Verified locally with the flag forced on: an inbound
`X-Amzn-Trace-Id: Root=1-5759e988-bd862e3fe1be46a994272793` produced spans on trace
`5759e988bd862e3fe1be46a994272793`, and a trace started at 14:17:14 UTC carried the
prefix `6a8317ea`, which is that instant in epoch seconds. Never observed in X-Ray
itself, because nothing is deployed — the untested hop is ADOT sidecar to the X-Ray
service.

### The metric that was wrong by 75×

`McpTelemetry.ToolDuration` records **seconds** and declared no explicit bucket
boundaries, so OpenTelemetry applied its default advice — buckets sized for
milliseconds, `0, 5, 10, 25, …`. Every real call landed in the first bucket, and the
p95 the Grafana panel drew was a histogram artefact rather than a measurement. The
histogram now declares second-scale boundaries.

Worth recording because no test could have caught it: the metric was emitted, the
panel rendered, the number was plausible. Only comparing it against a stopwatch
revealed it, which argues for at least one assertion about observability output
rather than only about its existence.

---

## 4.5 Performance

| Requirement | Implementation |
| ----------- | -------------- |
| Response caching, configurable TTL | `IMemoryCache` via `CachingMovieSearchClient`, `CACHE_TTL_SECONDS` (default 60) |
| Rate limit 60/minute per user | Fixed window partitioned on the JWT `sub`, `RATE_LIMIT_PER_MINUTE` |
| Request timeout, default 30s | `AddRequestTimeouts` and the MCP client's own timeout, `REQUEST_TIMEOUT_SECONDS` |
| p95 under 500 ms | **Observed 17 ms**, and 608 µs over 4,795 requests at 80 req/s with the limit raised |
| Load test script | `scripts/load_test.js` (k6) |

**The limiter partitions on `sub`, not on IP.** The brief says per authenticated
user, and an IP partition would lump every client behind one NAT together. Fixed
window rather than sliding or token bucket: "60 requests per minute" is exactly what
a fixed window means, so the implementation matches the documented promise, and the
burst behaviour at a window edge is easier to explain to a client than a
continuously refilling bucket. `QueueLimit = 0` — a rate-limited request should be
told 429 immediately, not held open until it times out.

An in-memory limiter is per-instance, so N tasks permit 60N requests per minute.
That is fine at one task and wrong at scale; the fix is a shared store, which is
noted below rather than pretended away.

### The load test could not pass its own thresholds

`scripts/load_test.js` ramped to 20 virtual users against a 60 request/minute limit
scoped to a single client, so **2,019 of 2,080 requests were throttled** and the
script failed the thresholds it set for itself. It now derives its arrival rate
from the configured limit.

It had never been run. That is the whole explanation, and it is the cheapest bug on
this list to have avoided.

---

## 4.6 OpenAPI

OpenAPI 3.1 is auto-generated and served at `/openapi/v1.json`, with Swagger UI at
`/swagger` and the document exported to `openapi.json` in the repository root.

**Examples on every model, parameter and 200 response**, which the brief asks for
and generation does not give you. `OpenApi/OpenApiConfiguration.cs` adds a schema
transformer and a document transformer; the example payloads live in
`OpenApi/OpenApiExamples.cs`. The effect worth having is that Swagger UI's **Try it
out** is usable without typing anything.

Two generation gaps were fixed rather than documented around:

- **The token endpoint had no documented request body.** Its handler takes
  `HttpRequest` so it can accept both JSON and form encoding, and there is
  consequently nothing for .NET to infer a schema from. `.Accepts<TokenRequest>(…)`
  states it explicitly.
- **429 was undeclared.** `.Produces(429)` on a route group does not attach to the
  group's endpoints, so the rate-limited responses were absent from the document.
  Group-level `ProducesResponseTypeMetadata` fixes it.

**The committed `openapi.json` cannot drift.** `OpenApiSpecTests` boots the app,
generates the document and compares it to the committed file, so a route or example
change that is not exported fails the build. `scripts/export_openapi.sh` regenerates
it (`UPDATE_OPENAPI=1`). Two further tests assert that every schema carries an
example and that every 200 response and documented parameter does too, so the
examples requirement is enforced rather than merely satisfied once.

Generation is made deterministic by pinning `document.Servers`, which otherwise
varies with the host and port the generating process happens to bind.

---

## Testing

| Suite | Result |
| ----- | ------ |
| `dotnet test` | **22 passed**, 5 skipped |
| `dotnet test` with `MCP_INTEGRATION_URL` | **27 passed** — the 5 live-MCP tests run |
| `dotnet format --verify-no-changes` | clean |

`WebApplicationFactory` against `FakeMovieSearchClient` covers routing, auth, RBAC,
caching, rate limiting and the OpenAPI document. `LiveMcpTests` covers what a fake
cannot.

### The bug the fake client hid

`McpMovieSearchClient` deserialized FastMCP's `{"result": …}` payload straight into
the target type. MCP requires `structuredContent` to be an object, so FastMCP wraps
every tool whose return type is not one — five of the six here. **Search, similar,
genres and by-id all returned 500.** Only `get_dataset_stats`, which returns a bare
object, worked. The client now unwraps the envelope.

Both test suites were green. The .NET tests substitute a fake client, so they never
serialize anything FastMCP produced; the Python contract test checked tool *names*
and argument keys, not response *shape*. A boundary that both sides mock is a
boundary nobody tests.

Three things now cover it: `test_dotnet_contract.py` parses
`McpMovieSearchClient.cs` for tool names and argument keys and asserts each exists
in the live FastMCP registry, `LiveMcpTests` runs the real SSE handshake and asserts
on **deserialized fields** rather than status codes, and CI runs those tests inside
the Compose job.

`LiveMcpTests` skips with a reason unless `MCP_INTEGRATION_URL` is set, via a custom
`RequiresLiveMcpAttribute`. It runs in an `IntegrationTesting` environment, which
exists because the `Testing` environment deliberately forces the fake client — the
one thing an integration test must not do.

---

## Contract with Part 3

Snake case on the MCP wire, camelCase on the REST API.

- `MovieResult`: `id`, `title`, `release_year`, `major_genre`, `mpaa_rating`,
  `director`, `distributor`, `imdb_rating`, `rt_rating`, `similarity`, `match_type`.
- `DatasetStats`: `total_movies`, `genres`, `year_min`, `year_max`,
  `avg_imdb_rating`.
- SSE endpoint: `{MCP_SERVER_URL}/sse`, default `http://mcp-server:8000/sse`.

`match_type` (`semantic` | `exact` | `fuzzy` | `lookup`) says how to read
`similarity`, which otherwise means three incomparable things depending on the tool
that produced it — see [`section-3.md`](section-3.md#match-semantics). `McpMovieDto`
ignores unknown properties, so adding it needed no API change; it is not yet mapped
into the REST DTO.

---

## How to run

```bash
dotnet test api/MovieSearch.sln                        # no MCP needed

MCP_CLIENT=fake docker compose run --no-deps --service-ports api

docker compose up --build api                          # waits for a healthy mcp-server

MCP_INTEGRATION_URL=http://localhost:8000 dotnet test api/MovieSearch.sln
```

If a host-side `dotnet build` fails with `Permission denied` on `obj/*.tmp`, the
`obj` and `bin` directories are root-owned from a previous run inside the
`mcr.microsoft.com/dotnet/sdk` image. Either `sudo chown -R "$USER" api` or build
with `--artifacts-path /tmp/msart`.

---

## Known gaps

- **The two sides name the trace field differently.** The API emits `@tr` (compact
  JSON's standard field) while the MCP server's structlog emits `trace_id`. Both
  carry the same value, so a joined query across the two services needs to know
  both names. Harmless locally, mildly annoying in CloudWatch Logs Insights, and
  the sort of thing a shared logging convention would settle.
- **The rate limiter is per-instance.** Two ECS tasks permit 120 requests per
  minute against a documented 60. A shared store — Redis, or ElastiCache on
  AWS — is the correct fix; the current arrangement is honest only at one replica.
- **The response cache is per-instance too**, for the same reason, though the
  consequence is merely a lower hit rate rather than a broken promise.
- **X-Ray has never been seen in X-Ray**, per 4.4.
- **`similarity` and `match_type` are not surfaced to REST clients.** The DTO
  carries them from MCP but the API response omits them, so a client cannot rank or
  threshold on score. Additive whenever a client needs it.
