using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Mvc;
using Microsoft.OpenApi;
using MovieSearch.Api.Auth;
using MovieSearch.Domain;

namespace MovieSearch.Api.OpenApi;

public static class OpenApiConfiguration
{
    private const string BearerScheme = "Bearer";

    /// <summary>
    /// Query and path parameter examples. Names are shared across operations, so
    /// one table covers every parameter in the document.
    /// </summary>
    private static readonly Dictionary<string, JsonNode> ParameterExamples = new(StringComparer.Ordinal)
    {
        ["q"] = OpenApiExamples.SearchQuery,
        ["top_k"] = 10,
        ["genre"] = "Action",
        ["min_imdb_rating"] = 7.5,
        ["mpaa_rating"] = "R",
        ["decade"] = 1990,
        ["id"] = OpenApiExamples.MovieId,
    };

    /// <summary>
    /// Descriptions for parameters whose example cannot be a working value, so
    /// Swagger UI says what to substitute instead of failing on the prefilled one.
    /// </summary>
    private static readonly Dictionary<string, string> ParameterDescriptions = new(StringComparer.Ordinal)
    {
        ["id"] =
            "Movie id from a /movies/search response. Ids are generated per database, "
            + "so the example value above is a placeholder and will return 404.",
    };

    public static void AddMovieSearchOpenApi(this IServiceCollection services)
    {
        services.AddOpenApi(options =>
        {
            options.AddSchemaTransformer((schema, context, _) =>
            {
                ApplySchemaExample(schema, context.JsonTypeInfo.Type);
                return Task.CompletedTask;
            });

            // Operations are enriched from the document rather than through an
            // operation transformer: security requirements need the document to
            // resolve the scheme reference, so doing all of it in one place
            // keeps the ordering obvious.
            options.AddDocumentTransformer((document, _, _) =>
            {
                ApplyInfo(document);
                ApplySecurityScheme(document);
                foreach (var operation in AllOperations(document))
                {
                    ApplyParameterMetadata(operation);
                    ApplyResponseExamples(operation, document);
                }

                return Task.CompletedTask;
            });
        });
    }

    private static void ApplyInfo(OpenApiDocument document)
    {
        document.Info = new OpenApiInfo
        {
            Title = "Movie Search API",
            Version = "1.0.0",
            Description =
                "Public REST API for semantic movie search. Wraps the FastMCP movie-search tools "
                + "behind JWT Bearer auth (client credentials). Minimal APIs on .NET 10.",
        };

        // Relative, so it resolves against whichever origin served the document:
        // localhost:8080 under Compose, the load balancer in AWS. An absolute URL
        // here would send Swagger UI's "Try it out" to that host regardless of
        // where the page was loaded from. Staying constant also keeps the document
        // byte-identical wherever it is generated, which OpenApiSpecTests depends
        // on to detect drift against the committed openapi.json.
        document.Servers =
        [
            new OpenApiServer { Url = "/", Description = "Origin serving this document" },
        ];
    }

    private static void ApplySecurityScheme(OpenApiDocument document)
    {
        document.Components ??= new OpenApiComponents();
        document.Components.SecuritySchemes ??= new Dictionary<string, IOpenApiSecurityScheme>(StringComparer.Ordinal);
        document.Components.SecuritySchemes[BearerScheme] = new OpenApiSecurityScheme
        {
            Type = SecuritySchemeType.Http,
            Scheme = "bearer",
            BearerFormat = "JWT",
            Description = "JWT from POST /auth/token (client_credentials).",
        };
    }

    private static IEnumerable<OpenApiOperation> AllOperations(OpenApiDocument document)
    {
        if (document.Paths is null)
        {
            yield break;
        }

        foreach (var path in document.Paths.Values)
        {
            if (path.Operations is null)
            {
                continue;
            }

            foreach (var operation in path.Operations.Values.OfType<OpenApiOperation>())
            {
                yield return operation;
            }
        }
    }

    private static void ApplySchemaExample(OpenApiSchema schema, Type type)
    {
        JsonNode? example = null;
        if (type == typeof(Movie))
        {
            example = OpenApiExamples.Movie();
        }
        else if (type == typeof(DatasetStats))
        {
            example = OpenApiExamples.DatasetStats();
        }
        else if (type == typeof(TokenRequest))
        {
            example = OpenApiExamples.TokenRequest();
        }
        else if (type == typeof(TokenResponse))
        {
            example = OpenApiExamples.TokenResponse();
        }
        else if (type == typeof(ProblemDetails))
        {
            example = OpenApiExamples.Problem(400, "Bad Request", "Query parameter 'q' is required.");
        }

        if (example is not null)
        {
            // OpenAPI 3.1 folds examples into JSON Schema, where the keyword is
            // the plural array form.
            schema.Examples = [example];
        }
    }

    private static void ApplyParameterMetadata(OpenApiOperation operation)
    {
        if (operation.Parameters is null)
        {
            return;
        }

        foreach (var parameter in operation.Parameters.OfType<OpenApiParameter>())
        {
            if (parameter.Name is null)
            {
                continue;
            }

            if (parameter.Example is null && ParameterExamples.TryGetValue(parameter.Name, out var example))
            {
                parameter.Example = example.DeepClone();
            }

            if (string.IsNullOrEmpty(parameter.Description)
                && ParameterDescriptions.TryGetValue(parameter.Name, out var description))
            {
                parameter.Description = description;
            }
        }
    }

    private static void ApplyResponseExamples(OpenApiOperation operation, OpenApiDocument document)
    {
        switch (operation.OperationId)
        {
            case "IssueToken":
                SetRequestBodyExample(operation, OpenApiExamples.TokenRequest());
                SetResponse(operation, "200", "Token issued.", OpenApiExamples.TokenResponse());
                SetResponse(
                    operation,
                    "400",
                    "grant_type, client_id or client_secret missing.",
                    OpenApiExamples.Problem(400, "Bad Request", "Provide grant_type, client_id, and client_secret as JSON or form fields."));
                SetResponse(
                    operation,
                    "401",
                    "Unknown client or wrong secret.",
                    OpenApiExamples.Problem(401, "Unauthorized", "Invalid client credentials or grant_type. Use grant_type=client_credentials."));
                break;

            case "HealthLive":
                SetResponse(operation, "200", "Process is up. Always 200 while the process is running.", OpenApiExamples.Liveness());
                break;

            case "HealthReady":
                SetResponse(operation, "200", "MCP server reachable.", OpenApiExamples.Readiness());
                SetResponse(
                    operation,
                    "503",
                    "The real MCP client is configured and unreachable.",
                    new JsonObject
                    {
                        ["status"] = "unhealthy",
                        ["checks"] = new JsonObject { ["mcp"] = "unhealthy" },
                    });
                break;

            case "SearchMovies":
                RequireBearer(operation, document);
                SetResponse(operation, "200", "Results ranked by cosine similarity, descending.", OpenApiExamples.MovieList());
                SetResponse(
                    operation,
                    "400",
                    "The q parameter is missing or blank.",
                    OpenApiExamples.Problem(400, "Bad Request", "Query parameter 'q' is required."));
                Describe(operation, "401", "Missing, expired or malformed Bearer token.");
                Describe(operation, "403", "Token is valid but lacks the reader or admin role.");
                Describe(operation, "429", "Rate limit of 60 requests/minute per client exceeded.");
                break;

            case "GetMovieById":
                RequireBearer(operation, document);
                SetResponse(operation, "200", "The movie.", OpenApiExamples.Movie());
                Describe(operation, "401", "Missing, expired or malformed Bearer token.");
                Describe(operation, "403", "Admin role required; reader tokens are rejected.");
                Describe(operation, "404", "No movie with that id.");
                break;

            case "GetSimilarMovies":
                RequireBearer(operation, document);
                SetResponse(operation, "200", "Nearest neighbours by embedding, excluding the seed movie.", OpenApiExamples.MovieList());
                Describe(operation, "401", "Missing, expired or malformed Bearer token.");
                Describe(operation, "403", "Admin role required; reader tokens are rejected.");
                break;

            case "ListGenres":
                RequireBearer(operation, document);
                SetResponse(operation, "200", "Distinct non-null major genres, alphabetical.", OpenApiExamples.Genres());
                Describe(operation, "401", "Missing, expired or malformed Bearer token.");
                Describe(operation, "403", "Admin role required; reader tokens are rejected.");
                break;

            case "GetDatasetStats":
                RequireBearer(operation, document);
                SetResponse(operation, "200", "Corpus summary.", OpenApiExamples.DatasetStats());
                Describe(operation, "401", "Missing, expired or malformed Bearer token.");
                Describe(operation, "403", "Admin role required; reader tokens are rejected.");
                break;

            default:
                break;
        }
    }

    private static void RequireBearer(OpenApiOperation operation, OpenApiDocument document)
    {
        operation.Security =
        [
            new OpenApiSecurityRequirement
            {
                [new OpenApiSecuritySchemeReference(BearerScheme, document)] = [],
            },
        ];
    }

    private static void SetRequestBodyExample(OpenApiOperation operation, JsonNode example)
    {
        if (operation.RequestBody is not OpenApiRequestBody body || body.Content is null)
        {
            return;
        }

        foreach (var media in body.Content.Values)
        {
            media.Example ??= example.DeepClone();
        }
    }

    private static void SetResponse(OpenApiOperation operation, string statusCode, string description, JsonNode example)
    {
        if (!TryGetResponse(operation, statusCode, out var response))
        {
            return;
        }

        response.Description = description;
        if (response.Content is null)
        {
            return;
        }

        foreach (var media in response.Content.Values)
        {
            media.Example ??= example.DeepClone();
        }
    }

    private static void Describe(OpenApiOperation operation, string statusCode, string description)
    {
        if (TryGetResponse(operation, statusCode, out var response))
        {
            response.Description = description;
        }
    }

    private static bool TryGetResponse(
        OpenApiOperation operation,
        string statusCode,
        out OpenApiResponse response)
    {
        response = null!;
        if (operation.Responses is not null
            && operation.Responses.TryGetValue(statusCode, out var candidate)
            && candidate is OpenApiResponse concrete)
        {
            response = concrete;
            return true;
        }

        return false;
    }
}
