using MovieSearch.Domain;

namespace MovieSearch.Application.Movies;

public sealed class GetDatasetStats
{
    private readonly IMovieSearchClient _client;

    public GetDatasetStats(IMovieSearchClient client)
    {
        _client = client;
    }

    public Task<DatasetStats> ExecuteAsync(CancellationToken cancellationToken = default) =>
        _client.GetStatsAsync(cancellationToken);
}
