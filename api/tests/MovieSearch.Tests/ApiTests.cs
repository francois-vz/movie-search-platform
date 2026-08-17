using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using MovieSearch.Infrastructure.Fake;
using Xunit;

namespace MovieSearch.Tests;

public abstract class ApiTestBase : IClassFixture<CustomWebApplicationFactory>
{
    protected ApiTestBase(CustomWebApplicationFactory factory)
    {
        Factory = factory;
        Client = factory.CreateClient();
    }

    protected CustomWebApplicationFactory Factory { get; }
    protected HttpClient Client { get; }

    protected async Task<string> GetTokenAsync(string clientId, string secret)
    {
        using var response = await Client.PostAsJsonAsync("/auth/token", new
        {
            grant_type = "client_credentials",
            client_id = clientId,
            client_secret = secret,
        });
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.GetProperty("access_token").GetString()
               ?? throw new InvalidOperationException("Token response missing access_token.");
    }

    protected async Task<HttpClient> CreateAuthorizedClientAsync(string clientId, string secret)
    {
        var token = await GetTokenAsync(clientId, secret);
        var client = Factory.CreateClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return client;
    }
}

public sealed class AuthTests : ApiTestBase
{
    public AuthTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Token_issues_reader_and_admin_roles()
    {
        var reader = await GetTokenAsync("reader", "reader-secret");
        var admin = await GetTokenAsync("admin", "admin-secret");
        Assert.False(string.IsNullOrWhiteSpace(reader));
        Assert.False(string.IsNullOrWhiteSpace(admin));
        Assert.NotEqual(reader, admin);
    }

    [Fact]
    public async Task Token_rejects_bad_credentials()
    {
        using var response = await Client.PostAsJsonAsync("/auth/token", new
        {
            grant_type = "client_credentials",
            client_id = "reader",
            client_secret = "wrong",
        });
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Api_without_token_returns_401()
    {
        using var response = await Client.GetAsync("/api/v1/movies/search?q=matrix");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }
}

public sealed class SearchTests : ApiTestBase
{
    public SearchTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Search_requires_q()
    {
        using var client = await CreateAuthorizedClientAsync("reader", "reader-secret");
        using var response = await client.GetAsync("/api/v1/movies/search");
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Search_as_reader_returns_results()
    {
        using var client = await CreateAuthorizedClientAsync("reader", "reader-secret");
        using var response = await client.GetAsync("/api/v1/movies/search?q=action%20movies%20from%20the%2090s&top_k=10");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(JsonValueKind.Array, payload.ValueKind);
        Assert.True(payload.GetArrayLength() > 0);
    }

    [Fact]
    public async Task Search_clamps_top_k()
    {
        using var client = await CreateAuthorizedClientAsync("reader", "reader-secret");
        using var response = await client.GetAsync("/api/v1/movies/search?q=movies&top_k=999");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.True(payload.GetArrayLength() <= 50);
    }
}

public sealed class AuthorizationTests : ApiTestBase
{
    public AuthorizationTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Theory]
    [InlineData("/api/v1/stats")]
    [InlineData("/api/v1/movies/genres")]
    [InlineData("/api/v1/movies/11111111-1111-1111-1111-111111111111")]
    [InlineData("/api/v1/movies/11111111-1111-1111-1111-111111111111/similar")]
    public async Task Reader_is_forbidden_outside_search(string path)
    {
        using var client = await CreateAuthorizedClientAsync("reader", "reader-secret");
        using var response = await client.GetAsync(path);
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Admin_can_read_stats()
    {
        using var client = await CreateAuthorizedClientAsync("admin", "admin-secret");
        using var response = await client.GetAsync("/api/v1/stats");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}

public sealed class GetMovieTests : ApiTestBase
{
    public GetMovieTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Get_by_id_returns_404_when_missing()
    {
        using var client = await CreateAuthorizedClientAsync("admin", "admin-secret");
        using var response = await client.GetAsync("/api/v1/movies/00000000-0000-0000-0000-000000000000");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Get_by_id_returns_movie()
    {
        using var client = await CreateAuthorizedClientAsync("admin", "admin-secret");
        using var response = await client.GetAsync($"/api/v1/movies/{FakeMovieSearchClient.MatrixId}");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var movie = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("The Matrix", movie.GetProperty("title").GetString());
    }
}

public sealed class CacheTests : ApiTestBase
{
    public CacheTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Identical_search_hits_cache()
    {
        using var client = await CreateAuthorizedClientAsync("reader", "reader-secret");
        var before = Factory.Fake.SearchCallCount;
        var url = "/api/v1/movies/search?q=cache-me-unique&top_k=5";
        using var first = await client.GetAsync(url);
        using var second = await client.GetAsync(url);
        Assert.Equal(HttpStatusCode.OK, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, second.StatusCode);
        Assert.Equal(before + 1, Factory.Fake.SearchCallCount);
    }
}

public sealed class RateLimitTests : ApiTestBase
{
    public RateLimitTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Sixty_first_search_is_rate_limited()
    {
        using var client = await CreateAuthorizedClientAsync("reader", "reader-secret");
        HttpStatusCode last = HttpStatusCode.OK;
        for (var i = 0; i < 61; i++)
        {
            using var response = await client.GetAsync($"/api/v1/movies/search?q=rate-{i}");
            last = response.StatusCode;
        }

        Assert.Equal(HttpStatusCode.TooManyRequests, last);
    }
}

public sealed class HealthTests : ApiTestBase
{
    public HealthTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Health_is_live()
    {
        using var response = await Client.GetAsync("/health");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Ready_is_ok_with_fake_client()
    {
        using var response = await Client.GetAsync("/health/ready");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}

public sealed class SearchQueryTests
{
    [Fact]
    public void ClampTopK_caps_at_50()
    {
        var query = new MovieSearch.Domain.SearchQuery { Query = "x", TopK = 999 }.ClampTopK();
        Assert.Equal(50, query.TopK);
    }

    [Fact]
    public void ClampTopK_defaults_non_positive()
    {
        var query = new MovieSearch.Domain.SearchQuery { Query = "x", TopK = 0 }.ClampTopK();
        Assert.Equal(10, query.TopK);
    }
}
