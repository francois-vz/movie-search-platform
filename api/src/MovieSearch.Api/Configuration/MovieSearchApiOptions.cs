using Microsoft.Extensions.Configuration;

namespace MovieSearch.Api.Configuration;

public sealed class MovieSearchApiOptions
{
    public string McpClient { get; init; } = "mcp";
    public string McpServerUrl { get; init; } = "http://mcp-server:8000";
    public int CacheTtlSeconds { get; init; } = 60;
    public int RateLimitPerMinute { get; init; } = 60;
    public int RequestTimeoutSeconds { get; init; } = 30;
    public string JwtIssuer { get; init; } = "movie-search";
    public string JwtAudience { get; init; } = "movie-search-clients";
    public string JwtSigningKey { get; init; } = "";
    public int JwtExpiryMinutes { get; init; } = 60;
    public string ReaderClientId { get; init; } = "reader";
    public string ReaderClientSecret { get; init; } = "";
    public string AdminClientId { get; init; } = "admin";
    public string AdminClientSecret { get; init; } = "";
    public string OtlpEndpoint { get; init; } = "http://jaeger:4317";

    public bool UseFakeMcp =>
        string.Equals(McpClient, "fake", StringComparison.OrdinalIgnoreCase);

    public static MovieSearchApiOptions From(IConfiguration configuration)
    {
        return new MovieSearchApiOptions
        {
            McpClient = configuration["MCP_CLIENT"] ?? "mcp",
            McpServerUrl = configuration["MCP_SERVER_URL"] ?? "http://mcp-server:8000",
            CacheTtlSeconds = ParseInt(configuration["CACHE_TTL_SECONDS"], 60),
            RateLimitPerMinute = ParseInt(configuration["RATE_LIMIT_PER_MINUTE"], 60),
            RequestTimeoutSeconds = ParseInt(configuration["REQUEST_TIMEOUT_SECONDS"], 30),
            JwtIssuer = configuration["JWT_ISSUER"] ?? "movie-search",
            JwtAudience = configuration["JWT_AUDIENCE"] ?? "movie-search-clients",
            JwtSigningKey = configuration["JWT_SIGNING_KEY"] ?? "",
            JwtExpiryMinutes = ParseInt(configuration["JWT_EXPIRY_MINUTES"], 60),
            ReaderClientId = configuration["AUTH_READER_CLIENT_ID"] ?? "reader",
            ReaderClientSecret = configuration["AUTH_READER_CLIENT_SECRET"] ?? "reader-secret",
            AdminClientId = configuration["AUTH_ADMIN_CLIENT_ID"] ?? "admin",
            AdminClientSecret = configuration["AUTH_ADMIN_CLIENT_SECRET"] ?? "admin-secret",
            OtlpEndpoint = configuration["OTEL_EXPORTER_OTLP_ENDPOINT"] ?? "http://jaeger:4317",
        };
    }

    private static int ParseInt(string? value, int fallback) =>
        int.TryParse(value, out var parsed) ? parsed : fallback;
}
