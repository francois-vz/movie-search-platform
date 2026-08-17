namespace MovieSearch.Api.Hosting;

public static class HostEnvironmentExtensions
{
    /// <summary>Fake MCP client, no outbound calls at all.</summary>
    public const string Testing = "Testing";

    /// <summary>
    /// Real MCP client against a running server, but still no file logs and no
    /// trace export. Used by <c>LiveMcpTests</c>.
    /// </summary>
    public const string IntegrationTesting = "IntegrationTesting";

    /// <summary>
    /// True for both test environments. Guards side effects that are unwanted
    /// under test — the rolling file sink and the OTLP exporter — as distinct
    /// from the choice of MCP client, which keys off configuration.
    /// </summary>
    public static bool IsTestEnvironment(this IHostEnvironment environment) =>
        environment.IsEnvironment(Testing) || environment.IsEnvironment(IntegrationTesting);
}
