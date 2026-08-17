using MovieSearch.Api.Configuration;
using MovieSearch.Domain;

namespace MovieSearch.Api.Endpoints;

public static class HealthEndpoints
{
    public static IEndpointRouteBuilder MapHealthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/health", Liveness)
            .WithName("HealthLive")
            .WithTags("Health")
            .WithSummary("Liveness probe.")
            .AllowAnonymous()
            .Produces(StatusCodes.Status200OK);

        app.MapGet("/health/ready", Readiness)
            .WithName("HealthReady")
            .WithTags("Health")
            .WithSummary("Readiness probe. Returns 503 when the real MCP client is configured and unreachable.")
            .AllowAnonymous()
            .Produces(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status503ServiceUnavailable);

        return app;
    }

    private static IResult Liveness(MovieSearchApiOptions options)
    {
        // Liveness is always 200 so Compose does not bounce the API process.
        return Results.Ok(new
        {
            status = "healthy",
            checks = new { mcp = options.UseFakeMcp ? "fake" : "deferred" },
        });
    }

    private static async Task<IResult> Readiness(
        IMovieSearchClient client,
        MovieSearchApiOptions options,
        CancellationToken cancellationToken)
    {
        var mcpOk = options.UseFakeMcp || await client.PingAsync(cancellationToken).ConfigureAwait(false);
        var payload = new
        {
            status = mcpOk ? "healthy" : "unhealthy",
            checks = new { mcp = mcpOk ? "healthy" : "unhealthy" },
        };
        return mcpOk
            ? Results.Ok(payload)
            : Results.Json(payload, statusCode: StatusCodes.Status503ServiceUnavailable);
    }
}
