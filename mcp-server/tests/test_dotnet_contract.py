"""Cross-language contract: the tools the .NET API calls must actually exist.

`GET /api/v1/movies/{id}` shipped calling `get_movie_by_id` while the server
only exposed `get_movie_by_title`. Nothing caught it: the .NET tests run against
a fake client, and the Python tests never saw the C#. This test reads the real
client and checks every tool name and argument against the live registry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.server.tools import mcp

CLIENT = (
    Path(__file__).resolve().parents[2]
    / "api"
    / "src"
    / "MovieSearch.Infrastructure"
    / "Mcp"
    / "McpMovieSearchClient.cs"
)

pytestmark = pytest.mark.skipif(
    not CLIENT.is_file(), reason="the .NET MCP client is not present"
)

# CallAsync("tool_name", ...) — the only way the client invokes a tool.
_TOOL_CALL = re.compile(r'CallAsync\(\s*"([a-z_]+)"')
# ["arg_name"] = ... — how the client builds every argument dictionary.
_ARG_KEY = re.compile(r'\["([a-z_]+)"\]\s*=')
# The constant naming FastMCP's synthetic wrapper property in the .NET client.
_WRAP_CONST = re.compile(r'WrapResultProperty\s*=\s*"(\w+)"')


def _client_source() -> str:
    return CLIENT.read_text(encoding="utf-8")


async def _registry() -> dict[str, set[str]]:
    """Registered tool name -> its accepted argument names."""
    tools = await mcp.list_tools()
    return {
        tool.name: set((tool.parameters or {}).get("properties", {}))
        for tool in tools
    }


def test_client_actually_calls_some_tools() -> None:
    """Guard the regex itself: a silent zero-match would make this vacuous."""
    assert len(_TOOL_CALL.findall(_client_source())) >= 5


async def test_every_tool_the_api_calls_is_registered() -> None:
    registry = await _registry()
    called = set(_TOOL_CALL.findall(_client_source()))

    missing = called - set(registry)
    assert not missing, f".NET calls MCP tools that do not exist: {sorted(missing)}"


async def test_every_argument_the_api_sends_is_accepted() -> None:
    registry = await _registry()
    accepted = set().union(*registry.values()) if registry else set()
    sent = set(_ARG_KEY.findall(_client_source()))

    unknown = sent - accepted
    assert not unknown, f".NET sends arguments no tool accepts: {sorted(unknown)}"


async def test_get_by_id_contract_specifically() -> None:
    """The endpoint that was broken; pin its exact shape."""
    registry = await _registry()
    assert "get_movie_by_id" in registry
    assert registry["get_movie_by_id"] == {"movie_id"}


async def test_tools_returning_non_objects_wrap_their_result() -> None:
    """Pin the envelope shape the .NET client has to unwrap.

    MCP requires structuredContent to be a JSON object, so FastMCP wraps any tool
    whose return type is not one (lists, and the `MovieResult | None` optionals) in
    {"result": ...}. The .NET client deserialized that envelope straight into
    List<McpMovieDto> and every search, similar, genres and by-id call 500'd; only
    get_dataset_stats, a bare object, worked. If FastMCP ever stops wrapping, this
    fails and McpMovieSearchClient.Unwrap must be revisited.
    """
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    def wraps(name: str) -> bool:
        return bool((tools[name].output_schema or {}).get("x-fastmcp-wrap-result", False))

    assert wraps("search_movies_by_description")
    assert wraps("get_similar_movies")
    assert wraps("list_genres")
    assert wraps("get_movie_by_id")
    assert wraps("get_movie_by_title")
    # Returns a plain model, so it is the one tool delivered unwrapped.
    assert not wraps("get_dataset_stats")


def test_dotnet_client_unwraps_the_result_envelope() -> None:
    """The .NET side must know the wrapper property by the name FastMCP uses."""
    source = _client_source()
    wrapper = _WRAP_CONST.search(source)
    assert wrapper, "McpMovieSearchClient no longer declares WrapResultProperty"
    assert wrapper.group(1) == "result"


async def test_response_fields_the_api_deserializes_exist_on_the_model() -> None:
    from src.server.models import DatasetStats, MovieResult

    # McpMovieDto / McpDatasetStatsDto use JsonNamingPolicy.SnakeCaseLower.
    movie_dto = {
        "id",
        "title",
        "release_year",
        "major_genre",
        "mpaa_rating",
        "director",
        "distributor",
        "imdb_rating",
        "rt_rating",
        "similarity",
    }
    stats_dto = {"total_movies", "genres", "year_min", "year_max", "avg_imdb_rating"}

    assert movie_dto <= set(MovieResult.model_fields)
    assert stats_dto <= set(DatasetStats.model_fields)
