using System.Text.Json.Serialization;

namespace MovieSearch.Api.Auth;

public sealed class TokenRequest
{
    [JsonPropertyName("grant_type")]
    public string? GrantType { get; set; }

    [JsonPropertyName("client_id")]
    public string? ClientId { get; set; }

    [JsonPropertyName("client_secret")]
    public string? ClientSecret { get; set; }
}

public sealed class TokenResponse
{
    [JsonPropertyName("access_token")]
    public required string AccessToken { get; init; }

    [JsonPropertyName("token_type")]
    public string TokenType { get; init; } = "Bearer";

    [JsonPropertyName("expires_in")]
    public int ExpiresIn { get; init; }

    [JsonPropertyName("role")]
    public required string Role { get; init; }
}
