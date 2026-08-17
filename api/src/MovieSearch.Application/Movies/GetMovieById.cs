using MovieSearch.Domain;

namespace MovieSearch.Application.Movies;

public sealed class GetMovieById
{
    private readonly IMovieSearchClient _client;

    public GetMovieById(IMovieSearchClient client)
    {
        _client = client;
    }

    public Task<Movie?> ExecuteAsync(string movieId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(movieId);
        return _client.GetByIdAsync(movieId, cancellationToken);
    }
}
