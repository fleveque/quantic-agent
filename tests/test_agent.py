from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from quantic_agent import agent, llm, quantic
from quantic_agent.tools import DIVIDEND_CALENDAR

pytestmark = pytest.mark.anyio


def asks(*calls: tuple[str, dict[str, Any]]) -> llm.ChatResponse:
    """A model reply asking for tools."""
    tool_calls = [llm.ToolCall(function=llm.FunctionCall(name=n, arguments=a)) for n, a in calls]
    return llm.ChatResponse(
        model="m", message=llm.Message(role="assistant", tool_calls=tool_calls), done=True
    )


def answers(text: str) -> llm.ChatResponse:
    return llm.ChatResponse(
        model="m", message=llm.Message(role="assistant", content=text), done=True
    )


@dataclass
class ScriptedModel:
    """Replies with its script, one reply per chat call, and keeps every
    conversation it was shown. It satisfies agent.Model without naming it."""

    script: list[llm.ChatResponse]
    shown: list[list[llm.Message]] = field(default_factory=lambda: list[list[llm.Message]]())
    tools: list[Sequence[llm.ToolDef] | None] = field(
        default_factory=lambda: list[Sequence[llm.ToolDef] | None]()
    )

    async def chat(
        self,
        messages: Sequence[llm.Message],
        *,
        tools: Sequence[llm.ToolDef] | None = None,
        think: bool | None = None,
        options: llm.Options | None = None,
    ) -> llm.ChatResponse:
        self.shown.append(list(messages))
        self.tools.append(tools)
        return self.script.pop(0)


@dataclass
class FakeServer:
    """Answers tool calls from a table, or raises what it's given."""

    results: dict[str, quantic.Result | Exception] = field(
        default_factory=lambda: dict[str, quantic.Result | Exception]()
    )
    received: list[tuple[str, dict[str, Any]]] = field(
        default_factory=lambda: list[tuple[str, dict[str, Any]]]()
    )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> quantic.Result:
        self.received.append((name, arguments))
        result = self.results[name]
        if isinstance(result, Exception):
            raise result
        return result


CALENDAR = quantic.Result(text='{"stocks":[{"symbol":"MSFT"}]}', is_error=False)


def researcher(model: ScriptedModel, server: FakeServer) -> agent.Researcher:
    return agent.Researcher(model=model, server=server, tools=[DIVIDEND_CALENDAR])


async def test_it_calls_a_tool_then_answers() -> None:
    model = ScriptedModel([asks(("dividend_calendar", {"days": 10})), answers("MSFT, on the 8th.")])
    server = FakeServer({"dividend_calendar": CALENDAR})
    traced: list[agent.Call] = []

    answer = await researcher(model, server).ask("next 10 days?", on_call=traced.append)

    assert answer.text == "MSFT, on the 8th."
    # The arguments reached the server validated, as the tool takes them.
    assert server.received == [("dividend_calendar", {"days": 10})]
    # Each call was handed over as it completed, and kept in the answer.
    assert traced == answer.calls
    assert [(c.tool, c.result, c.failed) for c in answer.calls] == [
        ("dividend_calendar", CALENDAR.text, False)
    ]
    # Second turn: the model saw its own request, then the tool's output.
    second = model.shown[1]
    assert second[-2].tool_calls is not None
    assert (second[-1].role, second[-1].tool_name, second[-1].content) == (
        "tool",
        "dividend_calendar",
        CALENDAR.text,
    )
    # The tool was offered with the schema from its arguments model.
    offered = model.tools[0]
    assert offered is not None
    assert offered[0].function.parameters == DIVIDEND_CALENDAR.schema()


@pytest.mark.parametrize(
    ("request_", "shown"),
    [
        pytest.param(
            ("no_such_tool", dict[str, Any]()),
            "there is no tool called 'no_such_tool'",
            id="unknown",
        ),
        pytest.param(
            ("dividend_calendar", {"days": 180}),
            "days: Input should be less than or equal to 120",
            id="out of bounds",
        ),
    ],
)
async def test_model_mistakes_go_back_to_the_model(
    request_: tuple[str, dict[str, Any]], shown: str
) -> None:
    model = ScriptedModel([asks(request_), answers("sorry")])
    server = FakeServer({"dividend_calendar": CALENDAR})

    answer = await researcher(model, server).ask("q")

    # The server never got the bad request; the model was shown why instead.
    assert server.received == []
    assert answer.calls[0].failed
    assert shown in model.shown[1][-1].content


async def test_a_tools_refusal_goes_back_to_the_model() -> None:
    refused = quantic.Result(text="needs authentication", is_error=True)
    model = ScriptedModel([asks(("dividend_calendar", {})), answers("can't")])

    answer = await researcher(model, FakeServer({"dividend_calendar": refused})).ask("q")

    assert answer.calls[0].failed
    assert model.shown[1][-1].content == "error: needs authentication"


async def test_a_rejected_request_goes_back_to_the_model() -> None:
    rejected = quantic.RPCError(-32602, "Invalid params", "days: expected type of :integer")
    model = ScriptedModel([asks(("dividend_calendar", {"days": 10})), answers("ok")])

    await researcher(model, FakeServer({"dividend_calendar": rejected})).ask("q")

    assert "Invalid params (-32602)" in model.shown[1][-1].content


async def test_it_stops_at_the_call_limit() -> None:
    # A model that never stops asking.
    model = ScriptedModel([asks(("dividend_calendar", {})) for _ in range(10)])
    traced: list[agent.Call] = []

    with pytest.raises(agent.TooManyCallsError):
        await agent.Researcher(
            model=model,
            server=FakeServer({"dividend_calendar": CALENDAR}),
            tools=[DIVIDEND_CALENDAR],
            max_calls=2,
        ).ask("q", on_call=traced.append)

    # The calls made before the limit were all recorded.
    assert len(traced) == 2


async def test_it_stops_when_the_server_is_gone() -> None:
    gone = quantic.ToolServerUnavailableError("connection refused")
    model = ScriptedModel([asks(("dividend_calendar", {}))])
    traced: list[agent.Call] = []

    # A failure the model can't fix ends the run, keeping its class...
    with pytest.raises(quantic.ToolServerUnavailableError):
        await researcher(model, FakeServer({"dividend_calendar": gone})).ask(
            "q", on_call=traced.append
        )
    # ...and the call it happened in is recorded, for the audit log.
    assert [(c.tool, c.failed) for c in traced] == [("dividend_calendar", True)]
