using MovieSearch.Domain;

namespace MovieSearch.Application.Movies;

public sealed class SearchMovies
{
    private readonly IMovieSearchClient _client;

    public SearchMovies(IMovieSearchClient client)
    {
        _client = client;
    }

    public Task<IReadOnlyList<Movie>> ExecuteAsync(SearchQuery query, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(query.Query);
        return _client.SearchByDescriptionAsync(query.ClampTopK(), cancellationToken);
    }
}
