using Microsoft.AspNetCore.Mvc;
using MovieSearch.Api.Auth;

namespace MovieSearch.Api.Endpoints;

public static class AuthEndpoints
{
    public static IEndpointRouteBuilder MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/auth/token", IssueToken)
            .WithName("IssueToken")
            .WithTags("Auth")
            .WithSummary("Issue a JWT via client credentials.")
            .WithDescription(
                "Exchange a reader or admin client id/secret for a Bearer token. Accepts JSON or form-urlencoded. "
                + "Credentials come from AUTH_READER_CLIENT_ID/AUTH_READER_CLIENT_SECRET and the AUTH_ADMIN_* pair; "
                + "substitute the value configured for this environment for the placeholder in the example.")
            .AllowAnonymous()

            // The handler takes HttpRequest so it can accept either content type,
            // which leaves nothing for OpenAPI to infer about the body.
            .Accepts<TokenRequest>("application/json", "application/x-www-form-urlencoded")
            .Produces<TokenResponse>(StatusCodes.Status200OK)
            .Produces<ProblemDetails>(StatusCodes.Status400BadRequest)
            .Produces<ProblemDetails>(StatusCodes.Status401Unauthorized);
        return app;
    }

    private static async Task<IResult> IssueToken(HttpRequest request, TokenService tokens)
    {
        var payload = await ReadRequestAsync(request).ConfigureAwait(false);
        if (payload is null)
        {
            return Results.Problem(
                statusCode: StatusCodes.Status400BadRequest,
                title: "Bad Request",
                detail: "Provide grant_type, client_id, and client_secret as JSON or form fields.");
        }

        var issued = tokens.Issue(payload);
        if (issued is null)
        {
            return Results.Problem(
                statusCode: StatusCodes.Status401Unauthorized,
                title: "Unauthorized",
                detail: "Invalid client credentials or grant_type. Use grant_type=client_credentials.");
        }

        return Results.Ok(issued);
    }

    private static async Task<TokenRequest?> ReadRequestAsync(HttpRequest request)
    {
        if (request.HasJsonContentType())
        {
            return await request.ReadFromJsonAsync<TokenRequest>().ConfigureAwait(false);
        }

        if (request.HasFormContentType)
        {
            var form = await request.ReadFormAsync().ConfigureAwait(false);
            return new TokenRequest
            {
                GrantType = form["grant_type"],
                ClientId = form["client_id"],
                ClientSecret = form["client_secret"],
            };
        }

        return null;
    }
}
