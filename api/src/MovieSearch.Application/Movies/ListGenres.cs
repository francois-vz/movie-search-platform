using MovieSearch.Domain;

namespace MovieSearch.Application.Movies;

public sealed class ListGenres
{
    private readonly IMovieSearchClient _client;

    public ListGenres(IMovieSearchClient client)
    {
        _client = client;
    }

    public Task<IReadOnlyList<string>> ExecuteAsync(CancellationToken cancellationToken = default) =>
        _client.ListGenresAsync(cancellationToken);
}
