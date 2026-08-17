using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace MovieSearch.Infrastructure.Mcp;

public static class McpTelemetry
{
    public const string ActivitySourceName = "MovieSearch.Mcp";
    public const string MeterName = "MovieSearch.Mcp";

    public static readonly ActivitySource ActivitySource = new(ActivitySourceName);
    public static readonly Meter Meter = new(MeterName);

    // Boundaries are mandatory here: durations are recorded in seconds, but the
    // OpenTelemetry default advice (0, 5, 10 ... 10000) is shaped for
    // milliseconds. Every real call would land in the first bucket and
    // histogram_quantile would interpolate inside [0, 5], reporting p95 in
    // seconds for calls that take tens of milliseconds. These match the buckets
    // http.server.request.duration uses, so the two latency panels are
    // comparable.
    public static readonly Histogram<double> ToolDuration = Meter.CreateHistogram(
        "mcp_tool_call_duration",
        unit: "s",
        description: "MCP tool call latency",
        tags: null,
        advice: new InstrumentAdvice<double>
        {
            HistogramBucketBoundaries =
            [
                0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1, 2.5, 5, 7.5, 10,
            ],
        });
}
