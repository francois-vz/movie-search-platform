using MovieSearch.Api.Configuration;
using MovieSearch.Api.Endpoints;
using MovieSearch.Api.Hosting;
using MovieSearch.Api.OpenApi;
using OpenTelemetry.Metrics;
using Serilog;
using Serilog.Formatting.Compact;

var builder = WebApplication.CreateBuilder(args);
var options = MovieSearchApiOptions.From(builder.Configuration);

if (string.IsNullOrWhiteSpace(options.JwtSigningKey) || options.JwtSigningKey.Length < 32)
{
    throw new InvalidOperationException("JWT_SIGNING_KEY must be at least 32 characters.");
}

builder.Host.UseSerilog((context, _, logger) =>
{
    logger
        .ReadFrom.Configuration(context.Configuration)
        .Enrich.FromLogContext()
        .WriteTo.Console(new RenderedCompactJsonFormatter());
    if (!context.HostingEnvironment.IsTestEnvironment())
    {
        logger.WriteTo.File(
            new CompactJsonFormatter(),
            path: "logs/api-.log",
            rollingInterval: RollingInterval.Day);
    }
});

builder.Services.AddMovieSearchApi(options, builder.Environment);
builder.Services.AddMovieSearchTelemetry(options, builder.Environment);
builder.Services.AddMovieSearchOpenApi();

var app = builder.Build();

app.UseSerilogRequestLogging();
app.UseExceptionHandler(errorApp =>
{
    errorApp.Run(async context =>
    {
        var problem = new Microsoft.AspNetCore.Mvc.ProblemDetails
        {
            Status = StatusCodes.Status500InternalServerError,
            Title = "Internal Server Error",
            Detail = "An unexpected error occurred while processing the request.",
        };
        context.Response.StatusCode = problem.Status.Value;
        context.Response.ContentType = "application/problem+json";
        await context.Response.WriteAsJsonAsync(problem);
    });
});
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();
app.UseRequestTimeouts();

app.MapOpenApi("/openapi/v1.json");
app.UseSwaggerUI(swagger =>
{
    swagger.SwaggerEndpoint("/openapi/v1.json", "Movie Search API v1");
    swagger.RoutePrefix = "swagger";
});
app.MapPrometheusScrapingEndpoint("/metrics");
app.MapHealthEndpoints();
app.MapAuthEndpoints();
app.MapMovieEndpoints();

app.Run();

public partial class Program;
