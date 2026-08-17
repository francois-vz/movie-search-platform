using MovieSearch.Domain;

namespace MovieSearch.Infrastructure.Fake;

/// <summary>
/// Deterministic in-memory MCP stand-in so Part 4 can be built and tested
/// without a live FastMCP server.
/// </summary>
public sealed class FakeMovieSearchClient : IMovieSearchClient
{
    public static readonly string MatrixId = "11111111-1111-1111-1111-111111111111";
    public static readonly string ToyStoryId = "22222222-2222-2222-2222-222222222222";
    public static readonly string AlienId = "33333333-3333-3333-3333-333333333333";
    public static readonly string TitanicId = "44444444-4444-4444-4444-444444444444";
    public static readonly string TerminatorId = "55555555-5555-5555-5555-555555555555";

    private readonly IReadOnlyList<Movie> _movies =
    [
        new(MatrixId, "The Matrix", 1999, "Action", "R", "Lana Wachowski", "Warner Bros.", 8.7, 87),
        new(ToyStoryId, "Toy Story", 1995, "Adventure", "G", "John Lasseter", "Walt Disney Pictures", 8.3, 100),
        new(AlienId, "Alien", 1979, "Horror", "R", "Ridley Scott", "20th Century Fox", 8.5, 98),
        new(TitanicId, "Titanic", 1997, "Drama", "PG-13", "James Cameron", "Paramount Pictures", 7.9, 88),
        new(TerminatorId, "Terminator 2: Judgment Day", 1991, "Action", "R", "James Cameron", "TriStar Pictures", 8.6, 93),
    ];

    public int SearchCallCount { get; private set; }

    public Task<IReadOnlyList<Movie>> SearchByDescriptionAsync(
        SearchQuery query,
        CancellationToken cancellationToken = default)
    {
        SearchCallCount++;
        IEnumerable<Movie> results = _movies;
        if (!string.IsNullOrWhiteSpace(query.Genre))
        {
            results = results.Where(m =>
                string.Equals(m.MajorGenre, query.Genre, StringComparison.OrdinalIgnoreCase));
        }

        if (query.MinImdbRating is { } min)
        {
            results = results.Where(m => m.ImdbRating >= min);
        }

        if (!string.IsNullOrWhiteSpace(query.MpaaRating))
        {
            results = results.Where(m =>
                string.Equals(m.MpaaRating, query.MpaaRating, StringComparison.OrdinalIgnoreCase));
        }

        if (query.Decade is { } decade)
        {
            results = results.Where(m => m.ReleaseYear is { } year && year / 10 * 10 == decade);
        }

        IReadOnlyList<Movie> ranked = results
            .Take(query.TopK)
            .Select((movie, index) => movie with { Similarity = Math.Round(0.95 - (index * 0.05), 2) })
            .ToList();
        return Task.FromResult(ranked);
    }

    public Task<Movie?> GetByIdAsync(string movieId, CancellationToken cancellationToken = default)
    {
        var movie = _movies.FirstOrDefault(m => string.Equals(m.Id, movieId, StringComparison.OrdinalIgnoreCase));
        return Task.FromResult(movie);
    }

    public Task<IReadOnlyList<Movie>> GetSimilarAsync(
        string movieId,
        int topK = 5,
        CancellationToken cancellationToken = default)
    {
        IReadOnlyList<Movie> similar = _movies
            .Where(m => !string.Equals(m.Id, movieId, StringComparison.OrdinalIgnoreCase))
            .Take(topK)
            .Select((movie, index) => movie with { Similarity = Math.Round(0.9 - (index * 0.08), 2) })
            .ToList();
        return Task.FromResult(similar);
    }

    public Task<IReadOnlyList<string>> ListGenresAsync(CancellationToken cancellationToken = default)
    {
        IReadOnlyList<string> genres = _movies
            .Select(m => m.MajorGenre)
            .Where(g => !string.IsNullOrWhiteSpace(g))
            .Select(g => g!)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(g => g)
            .ToList();
        return Task.FromResult(genres);
    }

    public Task<DatasetStats> GetStatsAsync(CancellationToken cancellationToken = default)
    {
        var years = _movies.Select(m => m.ReleaseYear).Where(y => y.HasValue).Select(y => y!.Value).ToList();
        var ratings = _movies.Select(m => m.ImdbRating).Where(r => r.HasValue).Select(r => r!.Value).ToList();
        var stats = new DatasetStats(
            TotalMovies: _movies.Count,
            Genres: _movies.Select(m => m.MajorGenre).Where(g => g is not null).Distinct().Count(),
            YearMin: years.Count == 0 ? null : years.Min(),
            YearMax: years.Count == 0 ? null : years.Max(),
            AvgImdbRating: ratings.Count == 0 ? null : Math.Round(ratings.Average(), 1));
        return Task.FromResult(stats);
    }

    public Task<bool> PingAsync(CancellationToken cancellationToken = default) => Task.FromResult(true);
}
