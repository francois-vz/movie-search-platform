using Microsoft.OpenApi;

namespace MovieSearch.Api.OpenApi;

public static class OpenApiConfiguration
{
    public static void AddMovieSearchOpenApi(this IServiceCollection services)
    {
        services.AddOpenApi(options =>
        {
            options.AddDocumentTransformer((document, _, _) =>
            {
                document.Info = new OpenApiInfo
                {
                    Title = "Movie Search API",
                    Version = "1.0.0",
                    Description =
                        "Public REST API for semantic movie search. Wraps the FastMCP movie-search tools behind JWT auth.",
                };
                document.Components ??= new OpenApiComponents();
                document.Components.SecuritySchemes ??= new Dictionary<string, IOpenApiSecurityScheme>();
                document.Components.SecuritySchemes["Bearer"] = new OpenApiSecurityScheme
                {
                    Type = SecuritySchemeType.Http,
                    Scheme = "bearer",
                    BearerFormat = "JWT",
                    Description = "JWT from POST /auth/token (client_credentials).",
                };
                return Task.CompletedTask;
            });
        });
    }
}
