namespace MovieSearch.Domain;

/// <summary>
/// Public movie representation. Field set mirrors MCP <c>MovieResult</c>.
/// </summary>
public sealed record Movie(
    string Id,
    string Title,
    int? ReleaseYear = null,
    string? MajorGenre = null,
    string? MpaaRating = null,
    string? Director = null,
    string? Distributor = null,
    double? ImdbRating = null,
    int? RtRating = null,
    double? Similarity = null);
