namespace MovieSearch.Domain;

/// <summary>
/// Natural-language search with optional metadata filters.
/// </summary>
public sealed record SearchQuery
{
    public const int DefaultTopK = 10;
    public const int MaxTopK = 50;

    public required string Query { get; init; }
    public int TopK { get; init; } = DefaultTopK;
    public string? Genre { get; init; }
    public double? MinImdbRating { get; init; }
    public string? MpaaRating { get; init; }
    public int? Decade { get; init; }

    public SearchQuery ClampTopK() =>
        this with { TopK = Math.Clamp(TopK <= 0 ? DefaultTopK : TopK, 1, MaxTopK) };
}
