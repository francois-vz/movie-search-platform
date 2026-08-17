using System.Text.Json.Nodes;

namespace MovieSearch.Api.OpenApi;

/// <summary>
/// Example payloads attached to the generated OpenAPI document. Values are real
/// rows and real queries from the Vega dataset, so anything pasted out of
/// Swagger UI returns results rather than an empty list.
/// </summary>
internal static class OpenApiExamples
{
    public const string SearchQuery = "action movies from the 90s with high IMDB ratings";
    public const string MovieId = "11111111-1111-1111-1111-111111111111";

    public static JsonObject Movie() => new()
    {
        ["id"] = MovieId,
        ["title"] = "The Matrix",
        ["releaseYear"] = 1999,
        ["majorGenre"] = "Action",
        ["mpaaRating"] = "R",
        ["director"] = "Lana Wachowski",
        ["distributor"] = "Warner Bros.",
        ["imdbRating"] = 8.7,
        ["rtRating"] = 87,
        ["similarity"] = 0.91,
    };

    public static JsonArray MovieList() => new(Movie());

    public static JsonObject DatasetStats() => new()
    {
        ["totalMovies"] = 3200,
        ["genres"] = 12,
        ["yearMin"] = 1915,
        ["yearMax"] = 2011,
        ["avgImdbRating"] = 6.4,
    };

    public static JsonArray Genres() => new("Action", "Adventure", "Comedy", "Drama", "Horror", "Thriller");

    public static JsonObject TokenRequest() => new()
    {
        ["grant_type"] = "client_credentials",
        ["client_id"] = "reader",
        ["client_secret"] = "change_me_reader_secret",
    };

    public static JsonObject TokenResponse() => new()
    {
        ["access_token"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJyZWFkZXIifQ.signature",
        ["token_type"] = "Bearer",
        ["expires_in"] = 3600,
        ["role"] = "reader",
    };

    public static JsonObject Liveness() => new()
    {
        ["status"] = "healthy",
        ["checks"] = new JsonObject { ["mcp"] = "deferred" },
    };

    public static JsonObject Readiness() => new()
    {
        ["status"] = "healthy",
        ["checks"] = new JsonObject { ["mcp"] = "healthy" },
    };

    public static JsonObject Problem(int status, string title, string detail) => new()
    {
        ["type"] = $"https://tools.ietf.org/html/rfc9110#section-15.5.{status - 399}",
        ["title"] = title,
        ["status"] = status,
        ["detail"] = detail,
    };
}
