using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.DependencyInjection;
using MovieSearch.Application.Caching;
using MovieSearch.Domain;
using MovieSearch.Infrastructure.Fake;
using MovieSearch.Infrastructure.Mcp;

namespace MovieSearch.Tests;

public sealed class CustomWebApplicationFactory : WebApplicationFactory<Program>
{
    public FakeMovieSearchClient Fake { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        builder.ConfigureServices(services =>
        {
            var stale = services
                .Where(d => d.ServiceType == typeof(FakeMovieSearchClient)
                            || d.ServiceType == typeof(IMovieSearchClient)
                            || d.ServiceType == typeof(McpMovieSearchClient))
                .ToList();
            foreach (var descriptor in stale)
            {
                services.Remove(descriptor);
            }

            services.AddSingleton(Fake);
            services.AddSingleton<IMovieSearchClient>(sp => new CachingMovieSearchClient(
                Fake,
                sp.GetRequiredService<IMemoryCache>(),
                TimeSpan.FromSeconds(60)));
        });
    }
}
