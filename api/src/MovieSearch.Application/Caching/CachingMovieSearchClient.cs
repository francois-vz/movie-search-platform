using Microsoft.Extensions.Caching.Memory;
using MovieSearch.Domain;

namespace MovieSearch.Application.Caching;

/// <summary>
/// Cache-aside decorator around <see cref="IMovieSearchClient"/>. Keys are tool + args,
/// not HTTP, so Authorization headers cannot bust the cache.
/// </summary>
public sealed class CachingMovieSearchClient : IMovieSearchClient
{
    private readonly IMovieSearchClient _inner;
    private readonly IMemoryCache _cache;
    private readonly TimeSpan _ttl;

    public CachingMovieSearchClient(IMovieSearchClient inner, IMemoryCache cache, TimeSpan ttl)
    {
        _inner = inner;
        _cache = cache;
        _ttl = ttl;
    }

    public Task<IReadOnlyList<Movie>> SearchByDescriptionAsync(
        SearchQuery query,
        CancellationToken cancellationToken = default)
    {
        var key =
            $"search:{query.Query}|{query.TopK}|{query.Genre}|{query.MinImdbRating}|{query.MpaaRating}|{query.Decade}";
        return GetOrCreateAsync(key, () => _inner.SearchByDescriptionAsync(query, cancellationToken));
    }

    public Task<Movie?> GetByIdAsync(string movieId, CancellationToken cancellationToken = default)
    {
        var key = $"get:{movieId}";
        return GetOrCreateAsync(key, () => _inner.GetByIdAsync(movieId, cancellationToken));
    }

    public Task<IReadOnlyList<Movie>> GetSimilarAsync(
        string movieId,
        int topK = 5,
        CancellationToken cancellationToken = default)
    {
        var key = $"similar:{movieId}|{topK}";
        return GetOrCreateAsync(key, () => _inner.GetSimilarAsync(movieId, topK, cancellationToken));
    }

    public Task<IReadOnlyList<string>> ListGenresAsync(CancellationToken cancellationToken = default) =>
        GetOrCreateAsync("genres", () => _inner.ListGenresAsync(cancellationToken));

    public Task<DatasetStats> GetStatsAsync(CancellationToken cancellationToken = default) =>
        GetOrCreateAsync("stats", () => _inner.GetStatsAsync(cancellationToken));

    public Task<bool> PingAsync(CancellationToken cancellationToken = default) =>
        _inner.PingAsync(cancellationToken);

    private async Task<T> GetOrCreateAsync<T>(string key, Func<Task<T>> factory)
    {
        if (_cache.TryGetValue(key, out T? cached) && cached is not null)
        {
            return cached;
        }

        var value = await factory().ConfigureAwait(false);
        if (value is not null)
        {
            _cache.Set(key, value, _ttl);
        }

        return value;
    }
}
