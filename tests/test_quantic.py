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


# Short waits, so the retries take milliseconds.
FAST = quantic.Backoff(attempts=3, base=0.01, max=0.02)


async def test_a_rate_limited_request_is_retried(quantic_mcp: FakeMCP) -> None:
    quantic_mcp.tools["dividend_calendar"] = "call-dividend-calendar.sse"
    retries: list[tuple[str, int]] = []

    def on_retry(method: str, retry: int, wait: float) -> None:
        retries.append((method, retry))
        assert FAST.wait(retry, lambda: 0) <= wait <= FAST.wait(retry, lambda: 1)

    async with quantic.Server(quantic_mcp.url, backoff=FAST, on_retry=on_retry) as server:
        # The handshake is over once a request has been answered after it.
        await server.list_tools()
        quantic_mcp.rate_limited = 2
        result = await server.call_tool("dividend_calendar", {"days": 10})

    assert not result.is_error
    assert retries == [("tools/call", 1), ("tools/call", 2)]


async def test_a_limit_that_doesnt_clear_is_not_the_models_mistake(quantic_mcp: FakeMCP) -> None:
    # Left to the SDK, a 429 became "Server returned an error response
    # (-32603)", an RPCError, which the research loop hands to the model to
    # correct. Nothing about the request was wrong.
    async with quantic.Server(quantic_mcp.url, backoff=FAST) as server:
        await server.list_tools()
        quantic_mcp.rate_limited = 3
        with pytest.raises(quantic.RateLimitedError, match=r"tools/call: 429.*3 attempts"):
            await server.call_tool("dividend_calendar", {"days": 10})


async def test_a_rate_limited_handshake(quantic_mcp: FakeMCP) -> None:
    quantic_mcp.rate_limited = 3
    with pytest.raises(quantic.RateLimitedError, match="initialize"):
        async with quantic.Server(quantic_mcp.url, backoff=FAST):
            pass


async def test_waiting_to_retry_ends_with_the_run(quantic_mcp: FakeMCP) -> None:
    # An hour's wait, cut short by the deadline: a refused run must still
    # stop when it is told to.
    quantic_mcp.rate_limited = 1

    async def connect() -> None:
        async with quantic.Server(quantic_mcp.url, backoff=quantic.Backoff(base=3600, max=3600)):
            pass

    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(connect(), 0.2)
    assert loop.time() - start < 1


def test_the_default_backoff_outlasts_a_minute() -> None:
    # Quantic counts requests in fixed one-minute windows and doesn't say when
    # one ends. Even the shortest schedule, every jitter at its minimum, must
    # wait out a whole window before giving up.
    b = quantic.DEFAULT_BACKOFF
    shortest = sum(b.wait(r, lambda: 0) for r in range(1, b.attempts))
    longest = sum(b.wait(r, lambda: 1) for r in range(1, b.attempts))
    assert shortest >= 60, f"the retries can give up after {shortest}s of waiting"
    assert (shortest, longest) == (60.5, 121)


def test_a_wait_is_capped_however_late_the_retry() -> None:
    b = quantic.DEFAULT_BACKOFF
    assert b.wait(2000, lambda: 1) == b.max


async def test_a_pace_waits_when_its_window_is_full() -> None:
    waits: list[float] = []
    pace = quantic.Pace(limit=3, per=0.3, on_wait=waits.append)
    loop = asyncio.get_running_loop()
    start = loop.time()

    for _ in range(6):
        await pace.wait()

    # Three at once, then the fourth waited for the first to leave the
    # window, and the fifth and sixth came in with it.
    assert 0.3 <= loop.time() - start < 0.5
    assert len(waits) == 1


async def test_sessions_share_a_pace(quantic_mcp: FakeMCP) -> None:
    # One session sends five requests (the handshake, its notification, the
    # refused event stream, a list, the closing DELETE): within a limit of
    # six. Two sessions sharing one pace send ten, so the second waits.
    loop = asyncio.get_running_loop()

    async def session(pace: quantic.Pace) -> None:
        async with quantic.Server(quantic_mcp.url, pace=pace) as server:
            await server.list_tools()

    start = loop.time()
    await session(quantic.Pace(limit=6, per=0.3))
    assert loop.time() - start < 0.2

    shared = quantic.Pace(limit=6, per=0.3)
    start = loop.time()
    await asyncio.gather(session(shared), session(shared))
    assert loop.time() - start >= 0.3
