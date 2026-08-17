using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace MovieSearch.Infrastructure.Mcp;

public static class McpTelemetry
{
    public const string ActivitySourceName = "MovieSearch.Mcp";
    public const string MeterName = "MovieSearch.Mcp";

    public static readonly ActivitySource ActivitySource = new(ActivitySourceName);
    public static readonly Meter Meter = new(MeterName);

    public static readonly Histogram<double> ToolDuration = Meter.CreateHistogram<double>(
        "mcp_tool_call_duration",
        unit: "s",
        description: "MCP tool call latency");
}
