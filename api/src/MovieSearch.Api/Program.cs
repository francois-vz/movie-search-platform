// Entry point for the Movie Search .NET 10 Web API.
//
// TODO (Part 4):
//   - Serilog (JSON console + file sink)
//   - OpenTelemetry traces (Jaeger/X-Ray) + metrics (Prometheus /metrics)
//   - JWT bearer auth + /auth/token (reader/admin roles)
//   - MCP client (Infrastructure) wired via DI
//   - Endpoints: /health, /api/v1/movies/search, /{id}, /{id}/similar,
//                /api/v1/movies/genres, /api/v1/stats
//   - Response caching, rate limiting (60/min), request timeout (30s)
//   - OpenAPI 3.1 at /openapi/v1.json + Swagger UI at /swagger

var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }));

app.Run();
