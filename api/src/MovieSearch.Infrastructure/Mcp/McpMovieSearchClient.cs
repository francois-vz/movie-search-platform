using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;
using MovieSearch.Domain;

namespace MovieSearch.Infrastructure.Mcp;

/// <summary>
/// MCP client over SSE using the official C# SDK. Connects lazily and reconnects after failures.
/// </summary>
public sealed class McpMovieSearchClient : IMovieSearchClient, IAsyncDisposable
{
    private readonly string _serverUrl;
    private readonly TimeSpan _timeout;
    private readonly ILoggerFactory _loggerFactory;
    private readonly ILogger<McpMovieSearchClient> _logger;
    private readonly SemaphoreSlim _gate = new(1, 1);
    private McpClient? _client;
    private bool _disposed;

    public McpMovieSearchClient(
        string serverUrl,
        TimeSpan timeout,
        ILoggerFactory loggerFactory)
    {
        _serverUrl = serverUrl.TrimEnd('/');
        _timeout = timeout;
        _loggerFactory = loggerFactory;
        _logger = loggerFactory.CreateLogger<McpMovieSearchClient>();
    }

    public Task<IReadOnlyList<Movie>> SearchByDescriptionAsync(
        SearchQuery query,
        CancellationToken cancellationToken = default)
    {
        var args = new Dictionary<string, object?>
        {
            ["query"] = query.Query,
            ["top_k"] = query.TopK,
        };
        if (query.Genre is not null)
        {
            args["genre_filter"] = query.Genre;
        }

        if (query.MinImdbRating is { } min)
        {
            args["min_imdb_rating"] = min;
        }

        if (query.MpaaRating is not null)
        {
            args["mpaa_rating"] = query.MpaaRating;
        }

        if (query.Decade is { } decade)
        {
            args["decade"] = decade;
        }

        return CallAsync(
            "search_movies_by_description",
            args,
            json =>
            {
                var movies = McpJson.Deserialize<List<McpMovieDto>>(json) ?? [];
                return (IReadOnlyList<Movie>)movies.Select(m => m.ToDomain()).ToList();
            },
            cancellationToken);
    }

    public Task<Movie?> GetByIdAsync(string movieId, CancellationToken cancellationToken = default) =>
        CallAsync(
            "get_movie_by_id",
            new Dictionary<string, object?> { ["movie_id"] = movieId },
            json =>
            {
                if (string.IsNullOrWhiteSpace(json) || json == "null")
                {
                    return (Movie?)null;
                }

                return McpJson.Deserialize<McpMovieDto>(json)?.ToDomain();
            },
            cancellationToken);

    public Task<IReadOnlyList<Movie>> GetSimilarAsync(
        string movieId,
        int topK = 5,
        CancellationToken cancellationToken = default) =>
        CallAsync(
            "get_similar_movies",
            new Dictionary<string, object?> { ["movie_id"] = movieId, ["top_k"] = topK },
            json =>
            {
                var movies = McpJson.Deserialize<List<McpMovieDto>>(json) ?? [];
                return (IReadOnlyList<Movie>)movies.Select(m => m.ToDomain()).ToList();
            },
            cancellationToken);

    public Task<IReadOnlyList<string>> ListGenresAsync(CancellationToken cancellationToken = default) =>
        CallAsync(
            "list_genres",
            new Dictionary<string, object?>(),
            json => (IReadOnlyList<string>)(McpJson.Deserialize<List<string>>(json) ?? []),
            cancellationToken);

    public Task<DatasetStats> GetStatsAsync(CancellationToken cancellationToken = default) =>
        CallAsync(
            "get_dataset_stats",
            new Dictionary<string, object?>(),
            json => McpJson.Deserialize<McpDatasetStatsDto>(json)?.ToDomain()
                    ?? throw new InvalidOperationException("MCP get_dataset_stats returned an empty payload."),
            cancellationToken);

    public async Task<bool> PingAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var client = await GetClientAsync(cancellationToken).ConfigureAwait(false);
            await client.PingAsync(cancellationToken: cancellationToken).ConfigureAwait(false);
            return true;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "MCP ping failed");
            await ResetClientAsync().ConfigureAwait(false);
            return false;
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        await ResetClientAsync().ConfigureAwait(false);
        _gate.Dispose();
    }

    private async Task<T> CallAsync<T>(
        string toolName,
        Dictionary<string, object?> arguments,
        Func<string, T> parse,
        CancellationToken cancellationToken)
    {
        using var activity = McpTelemetry.ActivitySource.StartActivity($"mcp.{toolName}", ActivityKind.Client);
        activity?.SetTag("mcp.tool", toolName);
        var start = Stopwatch.GetTimestamp();
        try
        {
            var client = await GetClientAsync(cancellationToken).ConfigureAwait(false);
            var result = await client.CallToolAsync(toolName, arguments, cancellationToken: cancellationToken)
                .ConfigureAwait(false);
            if (result.IsError is true)
            {
                var error = result.Content.OfType<TextContentBlock>().FirstOrDefault()?.Text ?? "unknown MCP tool error";
                throw new InvalidOperationException($"MCP tool '{toolName}' failed: {error}");
            }

            var json = ExtractJson(result);
            return parse(json);
        }
        catch
        {
            await ResetClientAsync().ConfigureAwait(false);
            throw;
        }
        finally
        {
            var duration = Stopwatch.GetElapsedTime(start).TotalSeconds;
            McpTelemetry.ToolDuration.Record(duration, new TagList { { "mcp.tool", toolName } });
        }
    }

    /// <summary>
    /// Name FastMCP uses for the synthetic wrapper it adds around non-object tool results.
    /// </summary>
    private const string WrapResultProperty = "result";

    private static string ExtractJson(CallToolResult result)
    {
        if (result.StructuredContent is { } structured)
        {
            return structured.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null
                ? "null"
                : Unwrap(structured).GetRawText();
        }

        return result.Content.OfType<TextContentBlock>().FirstOrDefault()?.Text ?? "null";
    }

    /// <summary>
    /// MCP requires structuredContent to be a JSON object, so FastMCP wraps tool results that are
    /// not objects (lists, scalars, and optionals) in {"result": ...} and advertises it with
    /// x-fastmcp-wrap-result in the tool's output schema. Five of the six movie tools are wrapped;
    /// only get_dataset_stats returns a bare object. Unwrapping a lone "result" property is safe
    /// here because no tool payload we deserialize is itself a single-property "result" object.
    /// </summary>
    private static JsonElement Unwrap(JsonElement structured)
    {
        if (structured.ValueKind is not JsonValueKind.Object)
        {
            return structured;
        }

        using var properties = structured.EnumerateObject();
        if (!properties.MoveNext())
        {
            return structured;
        }

        var only = properties.Current;
        return !properties.MoveNext() && only.NameEquals(WrapResultProperty)
            ? only.Value
            : structured;
    }

    private async Task<McpClient> GetClientAsync(CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_client is not null)
        {
            return _client;
        }

        await _gate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_client is not null)
            {
                return _client;
            }

            var endpoint = _serverUrl.EndsWith("/sse", StringComparison.OrdinalIgnoreCase)
                ? _serverUrl
                : $"{_serverUrl}/sse";
            var transport = new HttpClientTransport(new HttpClientTransportOptions
            {
                Endpoint = new Uri(endpoint),
                TransportMode = HttpTransportMode.Sse,
            });
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(_timeout);
            _client = await McpClient.CreateAsync(
                    transport,
                    loggerFactory: _loggerFactory,
                    cancellationToken: timeoutCts.Token)
                .ConfigureAwait(false);
            _logger.LogInformation("Connected to MCP server at {Endpoint}", endpoint);
            return _client;
        }
        finally
        {
            _gate.Release();
        }
    }

    private async Task ResetClientAsync()
    {
        await _gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_client is not null)
            {
                await _client.DisposeAsync().ConfigureAwait(false);
                _client = null;
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Error disposing MCP client");
            _client = null;
        }
        finally
        {
            _gate.Release();
        }
    }
}
