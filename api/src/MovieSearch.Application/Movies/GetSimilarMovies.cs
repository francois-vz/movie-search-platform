using MovieSearch.Domain;

namespace MovieSearch.Application.Movies;

public sealed class GetSimilarMovies
{
    private readonly IMovieSearchClient _client;

    public GetSimilarMovies(IMovieSearchClient client)
    {
        _client = client;
    }

    public Task<IReadOnlyList<Movie>> ExecuteAsync(
        string movieId,
        int topK = 5,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(movieId);
        var clamped = Math.Clamp(topK <= 0 ? 5 : topK, 1, SearchQuery.MaxTopK);
        return _client.GetSimilarAsync(movieId, clamped, cancellationToken);
    }
}
