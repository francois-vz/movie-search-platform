namespace MovieSearch.Domain;

/// <summary>
/// Outbound port to the movie-search MCP server (or a fake for tests).
/// </summary>
public interface IMovieSearchClient
{
    Task<IReadOnlyList<Movie>> SearchByDescriptionAsync(
        SearchQuery query,
        CancellationToken cancellationToken = default);

    Task<Movie?> GetByIdAsync(string movieId, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<Movie>> GetSimilarAsync(
        string movieId,
        int topK = 5,
        CancellationToken cancellationToken = default);

    Task<IReadOnlyList<string>> ListGenresAsync(CancellationToken cancellationToken = default);

    Task<DatasetStats> GetStatsAsync(CancellationToken cancellationToken = default);

    Task<bool> PingAsync(CancellationToken cancellationToken = default);
}
