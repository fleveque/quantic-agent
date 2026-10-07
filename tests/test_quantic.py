import asyncio
import json

import pytest
from conftest import DEAD_URL, FakeMCP

from quantic_agent import quantic

pytestmark = pytest.mark.anyio


async def test_a_tool_call_returns_the_tools_own_json(quantic_mcp: FakeMCP) -> None:
    quantic_mcp.tools["dividend_calendar"] = "call-dividend-calendar.sse"

    async with quantic.Server(quantic_mcp.url) as server:
        result = await server.call_tool("dividend_calendar", {"days": 10})

    assert not result.is_error
    # The tool's output is a JSON document inside the reply's text: decoded
    # once by the SDK, and once more here.
    calendar = json.loads(result.text)
    assert calendar["days"] == 10
    assert calendar["stocks"][0]["symbol"] == "O"
    assert quantic_mcp.calls() == [{"name": "dividend_calendar", "arguments": {"days": 10}}]


async def test_the_handshake_comes_first(quantic_mcp: FakeMCP) -> None:
    async with quantic.Server(quantic_mcp.url) as server:
        await server.list_tools()

    methods = [r.get("method") for r in quantic_mcp.requests]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert quantic_mcp.requests[0]["params"]["clientInfo"]["name"] == "quantic-agent"


async def test_a_refusal_is_a_result_not_an_exception(quantic_mcp: FakeMCP) -> None:
    # What quantic.finance answers when a portfolio tool is called anonymously.
    quantic_mcp.tools["get_portfolio"] = "call-private-anonymous.json"

    async with quantic.Server(quantic_mcp.url) as server:
        result = await server.call_tool("get_portfolio", {})

    assert result.is_error
    assert "needs authentication" in result.text


@pytest.mark.parametrize(
    ("tool", "fixture", "detail"),
    [
        ("no_such_tool", "error-unknown-tool.json", "Tool not found: no_such_tool"),
        (
            "dividend_calendar",
            "error-bad-arguments.json",
            'days: expected type of :integer received "ten" value',
        ),
    ],
)
async def test_a_rejected_request_is_an_rpc_error(
    quantic_mcp: FakeMCP, tool: str, fixture: str, detail: str
) -> None:
    quantic_mcp.tools[tool] = fixture

    async with quantic.Server(quantic_mcp.url) as server:
        with pytest.raises(quantic.RPCError) as err:
            await server.call_tool(tool, {"days": "ten"})

    assert err.value.code == -32602
    assert err.value.detail == detail


async def test_list_tools_describes_what_the_server_offers(quantic_mcp: FakeMCP) -> None:
    async with quantic.Server(quantic_mcp.url) as server:
        tools = {t.name: t for t in await server.list_tools()}

    assert "dividend_calendar" in tools
    assert tools["dividend_calendar"].input_schema["properties"]["days"]["type"] == "integer"


async def test_an_unreachable_server_is_unavailable() -> None:
    with pytest.raises(quantic.ToolServerUnavailableError):
        async with quantic.Server(DEAD_URL + "/mcp"):
            pass


async def test_an_unknown_host_is_not_unavailable() -> None:
    with pytest.raises(quantic.ToolServerError) as err:
        async with quantic.Server("http://no-such-host.invalid/mcp"):
            pass
    assert type(err.value) is quantic.ToolServerError


async def test_a_deadline_ends_a_tool_call(quantic_mcp: FakeMCP) -> None:
    quantic_mcp.tools["dividend_calendar"] = "hang"

    async with quantic.Server(quantic_mcp.url) as server:
        # asyncio's own TimeoutError, not a ToolServerError: running out of
        # time is the caller's decision. (The SDK runs on anyio task groups; a
        # cancellation that came back wrapped in a group would break this.)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.3):
                await server.call_tool("dividend_calendar", {"days": 10})
