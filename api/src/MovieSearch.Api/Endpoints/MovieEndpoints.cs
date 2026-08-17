using Microsoft.AspNetCore.Mvc;
using MovieSearch.Application.Movies;
using MovieSearch.Domain;

namespace MovieSearch.Api.Endpoints;

public static class MovieEndpoints
{
    public const string ReaderOrAdmin = "ReaderOrAdmin";
    public const string AdminOnly = "AdminOnly";

    public static IEndpointRouteBuilder MapMovieEndpoints(this IEndpointRouteBuilder app)
    {
        var api = app.MapGroup("/api/v1")
            .RequireAuthorization()
            .RequireRateLimiting("per-user")
            .WithTags("Movies");

        api.MapGet("/movies/search", Search)
            .WithName("SearchMovies")
            .WithSummary("Natural-language movie search.")
            .WithDescription("Semantic search via MCP search_movies_by_description. Reader and admin roles.")
            .RequireAuthorization(ReaderOrAdmin)
            .Produces<IReadOnlyList<Movie>>(StatusCodes.Status200OK)
            .Produces<ProblemDetails>(StatusCodes.Status400BadRequest)
            .Produces<ProblemDetails>(StatusCodes.Status401Unauthorized)
            .Produces<ProblemDetails>(StatusCodes.Status403Forbidden);

        api.MapGet("/movies/{id}", GetById)
            .WithName("GetMovieById")
            .WithSummary("Get a movie by ID.")
            .WithDescription("Admin only. Calls MCP get_movie_by_id.")
            .RequireAuthorization(AdminOnly)
            .Produces<Movie>(StatusCodes.Status200OK)
            .Produces<ProblemDetails>(StatusCodes.Status401Unauthorized)
            .Produces<ProblemDetails>(StatusCodes.Status403Forbidden)
            .Produces(StatusCodes.Status404NotFound);

        api.MapGet("/movies/{id}/similar", GetSimilar)
            .WithName("GetSimilarMovies")
            .WithSummary("Get semantically similar movies.")
            .WithDescription("Admin only. Calls MCP get_similar_movies.")
            .RequireAuthorization(AdminOnly)
            .Produces<IReadOnlyList<Movie>>(StatusCodes.Status200OK)
            .Produces<ProblemDetails>(StatusCodes.Status401Unauthorized)
            .Produces<ProblemDetails>(StatusCodes.Status403Forbidden);

        api.MapGet("/movies/genres", GetGenres)
            .WithName("ListGenres")
            .WithSummary("List distinct genres.")
            .WithDescription("Admin only. Calls MCP list_genres.")
            .RequireAuthorization(AdminOnly)
            .Produces<IReadOnlyList<string>>(StatusCodes.Status200OK)
            .Produces<ProblemDetails>(StatusCodes.Status401Unauthorized)
            .Produces<ProblemDetails>(StatusCodes.Status403Forbidden);

        api.MapGet("/stats", GetStats)
            .WithName("GetDatasetStats")
            .WithSummary("Dataset statistics.")
            .WithDescription("Admin only. Calls MCP get_dataset_stats.")
            .RequireAuthorization(AdminOnly)
            .Produces<DatasetStats>(StatusCodes.Status200OK)
            .Produces<ProblemDetails>(StatusCodes.Status401Unauthorized)
            .Produces<ProblemDetails>(StatusCodes.Status403Forbidden);

        return app;
    }

    private static async Task<IResult> Search(
        SearchMovies useCase,
        string? q,
        [FromQuery(Name = "top_k")] int topK = SearchQuery.DefaultTopK,
        string? genre = null,
        [FromQuery(Name = "min_imdb_rating")] double? minImdbRating = null,
        [FromQuery(Name = "mpaa_rating")] string? mpaaRating = null,
        int? decade = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(q))
        {
            return Results.Problem(
                statusCode: StatusCodes.Status400BadRequest,
                title: "Bad Request",
                detail: "Query parameter 'q' is required.");
        }

        var results = await useCase.ExecuteAsync(
            new SearchQuery
            {
                Query = q,
                TopK = topK,
                Genre = genre,
                MinImdbRating = minImdbRating,
                MpaaRating = mpaaRating,
                Decade = decade,
            },
            cancellationToken).ConfigureAwait(false);
        return Results.Ok(results);
    }

    private static async Task<IResult> GetById(
        string id,
        GetMovieById useCase,
        CancellationToken cancellationToken)
    {
        var movie = await useCase.ExecuteAsync(id, cancellationToken).ConfigureAwait(false);
        return movie is null ? Results.NotFound() : Results.Ok(movie);
    }

    private static Task<IReadOnlyList<Movie>> GetSimilar(
        string id,
        GetSimilarMovies useCase,
        [FromQuery(Name = "top_k")] int topK = 5,
        CancellationToken cancellationToken = default) =>
        useCase.ExecuteAsync(id, topK, cancellationToken);

    private static Task<IReadOnlyList<string>> GetGenres(
        ListGenres useCase,
        CancellationToken cancellationToken) =>
        useCase.ExecuteAsync(cancellationToken);

    private static Task<DatasetStats> GetStats(
        GetDatasetStats useCase,
        CancellationToken cancellationToken) =>
        useCase.ExecuteAsync(cancellationToken);
}
