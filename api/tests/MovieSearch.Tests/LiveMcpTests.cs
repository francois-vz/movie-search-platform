using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using MovieSearch.Api.Hosting;
using Xunit;

namespace MovieSearch.Tests;

/// <summary>
/// Skips unless <c>MCP_INTEGRATION_URL</c> points at a running MCP server, in the
/// same way the Python suites gate on <c>MCP_TEST_DSN</c>. Reported as skipped
/// rather than silently passing.
/// </summary>
public sealed class RequiresLiveMcpAttribute : FactAttribute
{
    public const string UrlVariable = "MCP_INTEGRATION_URL";

    public RequiresLiveMcpAttribute()
    {
        if (string.IsNullOrWhiteSpace(LiveMcpWebApplicationFactory.ServerUrl))
        {
            Skip = $"Set {UrlVariable} to a running MCP server (e.g. http://localhost:8000) to run this.";
        }
    }
}

/// <summary>
/// Boots the API with the real <c>McpMovieSearchClient</c> rather than the fake,
/// so the SSE handshake and the JSON field mapping are exercised.
/// </summary>
public sealed class LiveMcpWebApplicationFactory : WebApplicationFactory<Program>
{
    public static string? ServerUrl =>
        Environment.GetEnvironmentVariable(RequiresLiveMcpAttribute.UrlVariable);

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment(HostEnvironmentExtensions.IntegrationTesting);
        builder.UseSetting("MCP_SERVER_URL", ServerUrl ?? "http://localhost:8000");
    }
}

/// <summary>
/// The gap these tests close: every other .NET test substitutes
/// <c>FakeMovieSearchClient</c>, so nothing here spoke to a real server. That is
/// how the FastMCP <c>{"result": ...}</c> envelope bug shipped — five of six
/// tools returned 500 while the suite stayed green, because the mismatch was in
/// response *shape*, which a fake cannot reproduce. Each test therefore asserts
/// on deserialized fields, not just on the status code.
/// </summary>
public sealed class LiveMcpTests : IClassFixture<LiveMcpWebApplicationFactory>
{
    private readonly LiveMcpWebApplicationFactory _factory;

    public LiveMcpTests(LiveMcpWebApplicationFactory factory) => _factory = factory;

    [RequiresLiveMcp]
    public async Task Readiness_reports_healthy_against_a_live_server()
    {
        using var client = _factory.CreateClient();
        using var response = await client.GetAsync("/health/ready");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var body = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("healthy", body.RootElement.GetProperty("checks").GetProperty("mcp").GetString());
    }

    [RequiresLiveMcp]
    public async Task Search_returns_populated_movies()
    {
        var client = await AuthorizedClientAsync("reader", "reader-secret");
        using var response = await client.GetAsync(
            "/api/v1/movies/search?q=action%20movies%20from%20the%2090s%20with%20high%20IMDB%20ratings&top_k=5");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var movies = await ReadArrayAsync(response);
        Assert.NotEmpty(movies);

        // Field mapping, not just JSON validity: an envelope or casing mismatch
        // deserializes into a list of empty records rather than failing outright.
        foreach (var movie in movies)
        {
            Assert.False(string.IsNullOrWhiteSpace(movie.GetProperty("id").GetString()));
            Assert.False(string.IsNullOrWhiteSpace(movie.GetProperty("title").GetString()));
        }
    }

    [RequiresLiveMcp]
    public async Task Genres_and_stats_agree_with_each_other()
    {
        var client = await AuthorizedClientAsync("admin", "admin-secret");

        using var genresResponse = await client.GetAsync("/api/v1/movies/genres");
        Assert.Equal(HttpStatusCode.OK, genresResponse.StatusCode);
        var genres = await ReadArrayAsync(genresResponse);
        Assert.NotEmpty(genres);
        Assert.All(genres, genre => Assert.False(string.IsNullOrWhiteSpace(genre.GetString())));

        using var statsResponse = await client.GetAsync("/api/v1/stats");
        Assert.Equal(HttpStatusCode.OK, statsResponse.StatusCode);
        using var stats = JsonDocument.Parse(await statsResponse.Content.ReadAsStringAsync());
        Assert.True(stats.RootElement.GetProperty("totalMovies").GetInt32() > 0);
        Assert.Equal(genres.Count, stats.RootElement.GetProperty("genres").GetInt32());
    }

    [RequiresLiveMcp]
    public async Task Get_by_id_and_similar_round_trip_an_id_from_search()
    {
        var client = await AuthorizedClientAsync("admin", "admin-secret");

        using var searchResponse = await client.GetAsync("/api/v1/movies/search?q=science%20fiction&top_k=1");
        var found = await ReadArrayAsync(searchResponse);
        Assert.NotEmpty(found);
        var id = found[0].GetProperty("id").GetString()!;

        using var byId = await client.GetAsync($"/api/v1/movies/{id}");
        Assert.Equal(HttpStatusCode.OK, byId.StatusCode);
        using var movie = JsonDocument.Parse(await byId.Content.ReadAsStringAsync());
        Assert.Equal(id, movie.RootElement.GetProperty("id").GetString());

        using var similarResponse = await client.GetAsync($"/api/v1/movies/{id}/similar?top_k=3");
        Assert.Equal(HttpStatusCode.OK, similarResponse.StatusCode);
        var similar = await ReadArrayAsync(similarResponse);
        Assert.NotEmpty(similar);
        Assert.DoesNotContain(similar, other => other.GetProperty("id").GetString() == id);
    }

    [RequiresLiveMcp]
    public async Task Unknown_id_is_a_404_not_a_500()
    {
        var client = await AuthorizedClientAsync("admin", "admin-secret");
        using var response = await client.GetAsync($"/api/v1/movies/{Guid.NewGuid()}");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    private async Task<HttpClient> AuthorizedClientAsync(string clientId, string secret)
    {
        var client = _factory.CreateClient();
        using var tokenResponse = await client.PostAsJsonAsync("/auth/token", new
        {
            grant_type = "client_credentials",
            client_id = clientId,
            client_secret = secret,
        });
        tokenResponse.EnsureSuccessStatusCode();
        using var body = JsonDocument.Parse(await tokenResponse.Content.ReadAsStringAsync());
        var token = body.RootElement.GetProperty("access_token").GetString();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return client;
    }

    private static async Task<List<JsonElement>> ReadArrayAsync(HttpResponseMessage response)
    {
        var payload = await response.Content.ReadAsStringAsync();
        using var document = JsonDocument.Parse(payload);
        Assert.Equal(JsonValueKind.Array, document.RootElement.ValueKind);
        return [.. document.RootElement.EnumerateArray().Select(element => element.Clone())];
    }
}
