using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;
using Xunit;

namespace MovieSearch.Tests;

/// <summary>
/// Makes the repository-root openapi.json an export of the generated document
/// rather than a hand-maintained copy that can drift from it.
/// Regenerate with <c>scripts/export_openapi.sh</c>.
/// </summary>
public sealed class OpenApiSpecTests : ApiTestBase
{
    private const string DocumentPath = "/openapi/v1.json";
    private const string UpdateVariable = "UPDATE_OPENAPI";

    public OpenApiSpecTests(CustomWebApplicationFactory factory)
        : base(factory)
    {
    }

    [Fact]
    public async Task Committed_openapi_json_matches_the_generated_document()
    {
        var generated = await GetGeneratedDocumentAsync();
        var committedPath = Path.Combine(RepositoryRoot(), "openapi.json");

        if (Environment.GetEnvironmentVariable(UpdateVariable) == "1")
        {
            await File.WriteAllTextAsync(committedPath, generated + Environment.NewLine);
            return;
        }

        Assert.True(File.Exists(committedPath), $"Expected an exported spec at {committedPath}.");
        var committed = Normalize(JsonNode.Parse(await File.ReadAllTextAsync(committedPath)));

        Assert.True(
            string.Equals(committed, generated, StringComparison.Ordinal),
            $"openapi.json is out of date. Regenerate it with scripts/export_openapi.sh ({UpdateVariable}=1).");
    }

    [Fact]
    public async Task Every_model_schema_carries_an_example()
    {
        var document = JsonNode.Parse(await GetGeneratedDocumentAsync())!;
        var schemas = document["components"]?["schemas"]?.AsObject();
        Assert.NotNull(schemas);

        foreach (var (name, schema) in schemas)
        {
            Assert.True(
                schema?["examples"] is JsonArray { Count: > 0 },
                $"Schema '{name}' has no examples. Add one in OpenApiConfiguration.ApplySchemaExample.");
        }
    }

    [Fact]
    public async Task Every_success_response_and_documented_parameter_carries_an_example()
    {
        var document = JsonNode.Parse(await GetGeneratedDocumentAsync())!;
        var paths = document["paths"]!.AsObject();

        foreach (var (route, pathItem) in paths)
        {
            foreach (var (method, operation) in pathItem!.AsObject())
            {
                var where = $"{method.ToUpperInvariant()} {route}";

                foreach (var parameter in operation?["parameters"]?.AsArray() ?? [])
                {
                    var name = parameter?["name"]?.GetValue<string>();
                    Assert.True(
                        parameter?["example"] is not null,
                        $"Parameter '{name}' on {where} has no example.");
                }

                var ok = operation?["responses"]?["200"];
                var content = ok?["content"]?.AsObject();
                if (content is null)
                {
                    continue;
                }

                foreach (var (mediaType, media) in content)
                {
                    Assert.True(
                        media?["example"] is not null,
                        $"Response 200 {mediaType} on {where} has no example.");
                }
            }
        }
    }

    private async Task<string> GetGeneratedDocumentAsync()
    {
        using var response = await Client.GetAsync(DocumentPath);
        response.EnsureSuccessStatusCode();
        return Normalize(JsonNode.Parse(await response.Content.ReadAsStringAsync()));
    }

    private static string Normalize(JsonNode? node) =>
        node?.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) ?? string.Empty;

    /// <summary>
    /// Anchored on this source file rather than the output directory, which moves
    /// when the build uses --artifacts-path.
    /// </summary>
    private static string RepositoryRoot([CallerFilePath] string callerPath = "")
    {
        var directory = new DirectoryInfo(Path.GetDirectoryName(callerPath)!);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "docker-compose.yml")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new InvalidOperationException($"Could not locate the repository root from {callerPath}.");
    }
}
