using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.IdentityModel.Tokens;
using MovieSearch.Api.Configuration;

namespace MovieSearch.Api.Auth;

public sealed class TokenService
{
    public const string ReaderRole = "reader";
    public const string AdminRole = "admin";
    public const string RoleClaim = "role";

    private readonly MovieSearchApiOptions _options;
    private readonly SymmetricSecurityKey _signingKey;

    public TokenService(MovieSearchApiOptions options)
    {
        _options = options;
        _signingKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(options.JwtSigningKey));
    }

    public TokenResponse? Issue(TokenRequest request)
    {
        if (!string.Equals(request.GrantType, "client_credentials", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var role = ResolveRole(request.ClientId, request.ClientSecret);
        if (role is null || string.IsNullOrWhiteSpace(request.ClientId))
        {
            return null;
        }

        var now = DateTime.UtcNow;
        var expires = now.AddMinutes(_options.JwtExpiryMinutes);
        var claims = new[]
        {
            new Claim(JwtRegisteredClaimNames.Sub, request.ClientId),
            new Claim(ClaimTypes.NameIdentifier, request.ClientId),
            new Claim(RoleClaim, role),
        };
        var token = new JwtSecurityToken(
            issuer: _options.JwtIssuer,
            audience: _options.JwtAudience,
            claims: claims,
            notBefore: now,
            expires: expires,
            signingCredentials: new SigningCredentials(_signingKey, SecurityAlgorithms.HmacSha256));
        return new TokenResponse
        {
            AccessToken = new JwtSecurityTokenHandler().WriteToken(token),
            TokenType = "Bearer",
            ExpiresIn = _options.JwtExpiryMinutes * 60,
            Role = role,
        };
    }

    private string? ResolveRole(string? clientId, string? clientSecret)
    {
        if (Matches(clientId, _options.ReaderClientId, clientSecret, _options.ReaderClientSecret))
        {
            return ReaderRole;
        }

        if (Matches(clientId, _options.AdminClientId, clientSecret, _options.AdminClientSecret))
        {
            return AdminRole;
        }

        return null;
    }

    private static bool Matches(string? clientId, string expectedId, string? secret, string expectedSecret) =>
        string.Equals(clientId, expectedId, StringComparison.Ordinal) &&
        string.Equals(secret, expectedSecret, StringComparison.Ordinal);
}
