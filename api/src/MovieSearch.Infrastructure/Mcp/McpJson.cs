using System.Text.Json;
using System.Text.Json.Serialization;
using MovieSearch.Domain;

namespace MovieSearch.Infrastructure.Mcp;

internal static class McpJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static T? Deserialize<T>(string json) => JsonSerializer.Deserialize<T>(json, Options);
}

internal sealed record McpMovieDto(
    string Id,
    string Title,
    int? ReleaseYear,
    string? MajorGenre,
    string? MpaaRating,
    string? Director,
    string? Distributor,
    double? ImdbRating,
    int? RtRating,
    double? Similarity)
{
    public Movie ToDomain() => new(
        Id,
        Title,
        ReleaseYear,
        MajorGenre,
        MpaaRating,
        Director,
        Distributor,
        ImdbRating,
        RtRating,
        Similarity);
}

internal sealed record McpDatasetStatsDto(
    int TotalMovies,
    int Genres,
    int? YearMin,
    int? YearMax,
    double? AvgImdbRating)
{
    public DatasetStats ToDomain() => new(TotalMovies, Genres, YearMin, YearMax, AvgImdbRating);
}
