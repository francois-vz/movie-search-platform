namespace MovieSearch.Domain;

/// <summary>
/// Dataset summary. Field set mirrors MCP <c>DatasetStats</c>.
/// </summary>
public sealed record DatasetStats(
    int TotalMovies,
    int Genres,
    int? YearMin = null,
    int? YearMax = null,
    double? AvgImdbRating = null);
