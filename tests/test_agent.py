import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from quantic_agent import agent, llm, quantic
from quantic_agent.tools import DIVIDEND_CALENDAR

pytestmark = pytest.mark.anyio


def asks(*calls: tuple[str, dict[str, Any]], tokens: int = 0) -> llm.ChatResponse:
    """A model reply asking for tools, which cost tokens to produce."""
    tool_calls = [llm.ToolCall(function=llm.FunctionCall(name=n, arguments=a)) for n, a in calls]
    return llm.ChatResponse(
        model="m",
        message=llm.Message(role="assistant", tool_calls=tool_calls),
        done=True,
        prompt_eval_count=tokens,
    )


def answers(text: str, tokens: int = 0) -> llm.ChatResponse:
    return llm.ChatResponse(
        model="m",
        message=llm.Message(role="assistant", content=text),
        done=True,
        prompt_eval_count=tokens,
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
    formats: list[dict[str, Any] | None] = field(
        default_factory=lambda: list[dict[str, Any] | None]()
    )

    async def chat(
        self,
        messages: Sequence[llm.Message],
        *,
        tools: Sequence[llm.ToolDef] | None = None,
        think: bool | None = None,
        format: dict[str, Any] | None = None,
        options: llm.Options | None = None,
    ) -> llm.ChatResponse:
        self.shown.append(list(messages))
        self.tools.append(tools)
        self.formats.append(format)
        return self.script.pop(0)


# A result worked out from the call's arguments.
type Answer = Callable[[dict[str, Any]], quantic.Result | Exception]


@dataclass
class FakeServer:
    """Answers tool calls from a table, or raises what it's given. delay says
    how long a call takes, from its arguments; peak is the most calls it was
    answering at once."""

    results: dict[str, quantic.Result | Exception | Answer] = field(
        default_factory=lambda: dict[str, quantic.Result | Exception | Answer]()
    )
    received: list[tuple[str, dict[str, Any]]] = field(
        default_factory=lambda: list[tuple[str, dict[str, Any]]]()
    )
    delay: Callable[[dict[str, Any]], float] = lambda _: 0.0
    peak: int = 0
    busy: int = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> quantic.Result:
        self.received.append((name, arguments))
        self.busy += 1
        self.peak = max(self.peak, self.busy)
        try:
            await asyncio.sleep(self.delay(arguments))
        finally:
            self.busy -= 1
        result = self.results[name]
        if callable(result):
            result = result(arguments)
        if isinstance(result, Exception):
            raise result
        return result


CALENDAR = quantic.Result(text='{"stocks":[{"symbol":"MSFT"}]}', is_error=False)


def researcher(
    model: ScriptedModel, server: FakeServer, budget: agent.Budget = agent.DEFAULT_BUDGET
) -> agent.Researcher:
    return agent.Researcher(model=model, server=server, tools=[DIVIDEND_CALENDAR], budget=budget)


async def research(r: agent.Researcher, gathered: agent.Research | None = None) -> agent.Research:
    gathered = gathered if gathered is not None else agent.Research()
    await r.research("q", gathered)
    return gathered


async def test_it_calls_a_tool_until_the_model_stops_asking() -> None:
    model = ScriptedModel(
        [asks(("dividend_calendar", {"days": 10}), tokens=900), answers("MSFT.", tokens=1100)]
    )
    server = FakeServer({"dividend_calendar": CALENDAR})
    traced: list[tuple[int, agent.Call]] = []
    gathered = agent.Research()

    await researcher(model, server).research(
        "next 10 days?", gathered, on_call=lambda seq, c: traced.append((seq, c))
    )

    # The arguments reached the server validated, as the tool takes them.
    assert server.received == [("dividend_calendar", {"days": 10})]
    # Each call was handed over as it completed, with its position, and kept.
    assert traced == list(enumerate(gathered.calls))
    assert [(c.tool, c.result, c.failed) for c in gathered.calls] == [
        ("dividend_calendar", CALENDAR.text, False)
    ]
    # Both replies' tokens count; neither budget stopped it.
    assert (gathered.tokens, gathered.exhausted) == (2000, None)
    assert gathered.has_data
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

    gathered = await research(researcher(model, server))

    # The server never got the bad request; the model was shown why instead.
    assert server.received == []
    assert gathered.calls[0].failed
    assert shown in model.shown[1][-1].content
    # A refused call is not data.
    assert not gathered.has_data


async def test_a_tools_refusal_goes_back_to_the_model() -> None:
    refused = quantic.Result(text="needs authentication", is_error=True)
    model = ScriptedModel([asks(("dividend_calendar", {})), answers("can't")])

    gathered = await research(researcher(model, FakeServer({"dividend_calendar": refused})))

    assert gathered.calls[0].failed
    assert model.shown[1][-1].content == "error: needs authentication"


async def test_a_rejected_request_goes_back_to_the_model() -> None:
    rejected = quantic.RPCError(-32602, "Invalid params", "days: expected type of :integer")
    model = ScriptedModel([asks(("dividend_calendar", {"days": 10})), answers("ok")])

    await research(researcher(model, FakeServer({"dividend_calendar": rejected})))

    assert "Invalid params (-32602)" in model.shown[1][-1].content


async def test_running_out_of_calls_is_an_outcome_not_an_error() -> None:
    # A model that never stops asking.
    model = ScriptedModel([asks(("dividend_calendar", {})) for _ in range(10)])
    server = FakeServer({"dividend_calendar": CALENDAR})

    gathered = await research(researcher(model, server, agent.Budget(calls=2)))

    assert gathered.exhausted is agent.Limit.CALLS
    assert len(gathered.calls) == len(server.received) == 2


async def test_a_reply_that_crosses_the_token_budget_isnt_run() -> None:
    model = ScriptedModel(
        [
            asks(("dividend_calendar", {"days": 10}), tokens=600),
            asks(("dividend_calendar", {"days": 20}), tokens=600),
        ]
    )
    server = FakeServer({"dividend_calendar": CALENDAR})

    gathered = await research(researcher(model, server, agent.Budget(tokens=1000)))

    # The second request arrived after the budget was spent: dropped.
    assert server.received == [("dividend_calendar", {"days": 10})]
    assert (gathered.tokens, gathered.exhausted) == (1200, agent.Limit.TOKENS)


async def test_a_spent_budget_asks_nothing() -> None:
    # A resumed run may have spent its tokens already.
    model = ScriptedModel([])
    spent = agent.Research(tokens=agent.DEFAULT_BUDGET.tokens)

    await research(researcher(model, FakeServer()), spent)

    assert model.shown == []
    assert spent.exhausted is agent.Limit.TOKENS


async def test_it_stops_when_the_server_is_gone() -> None:
    gone = quantic.ToolServerUnavailableError("connection refused")
    model = ScriptedModel([asks(("dividend_calendar", {}), tokens=700)])
    gathered = agent.Research()

    # A failure the model can't fix ends the run, keeping its class...
    with pytest.raises(quantic.ToolServerUnavailableError):
        await researcher(model, FakeServer({"dividend_calendar": gone})).research("q", gathered)
    # ...and what was done before it is still there: the call it happened in,
    # for the audit log, and the tokens.
    assert [(c.tool, c.failed) for c in gathered.calls] == [("dividend_calendar", True)]
    assert gathered.tokens == 700


async def test_a_resumed_run_replays_its_calls() -> None:
    recorded = agent.Call(tool="dividend_calendar", arguments={"days": 10}, result=CALENDAR.text)
    prior = agent.Research(calls=[recorded], tokens=900)
    model = ScriptedModel([asks(("dividend_calendar", {"days": 20})), answers("done")])
    server = FakeServer({"dividend_calendar": CALENDAR})
    traced: list[int] = []

    await researcher(model, server).research("q", prior, on_call=lambda seq, _: traced.append(seq))

    # The model saw the recorded call and its result as if just made...
    first = model.shown[0]
    assert [m.role for m in first] == ["system", "user", "assistant", "tool"]
    assert first[2].tool_calls is not None
    assert first[2].tool_calls[0].function.arguments == {"days": 10}
    assert first[3].content == CALENDAR.text
    # ...without the tool being called again for it. The new call is
    # number 1, after the recorded one.
    assert server.received == [("dividend_calendar", {"days": 20})]
    assert traced == [1]
    assert [c.arguments for c in prior.calls] == [{"days": 10}, {"days": 20}]


async def test_recorded_calls_count_against_the_budget() -> None:
    recorded = agent.Call(tool="dividend_calendar", arguments={}, result=CALENDAR.text)
    model = ScriptedModel([asks(("dividend_calendar", {}))])
    server = FakeServer({"dividend_calendar": CALENDAR})

    gathered = await research(
        researcher(model, server, agent.Budget(calls=2)), agent.Research(calls=[recorded] * 2)
    )

    assert server.received == []
    assert gathered.exhausted is agent.Limit.CALLS


# ---- writing ---------------------------------------------------------------


def gathered_data(*, exhausted: agent.Limit | None = None) -> agent.Research:
    return agent.Research(
        calls=[
            agent.Call("dividend_calendar", {"days": 200}, "error: at most 120", failed=True),
            agent.Call("dividend_calendar", {"days": 10}, CALENDAR.text),
        ],
        exhausted=exhausted,
    )


async def test_the_writer_sees_the_question_and_the_data_only() -> None:
    model = ScriptedModel([answers("MSFT goes ex-dividend.", tokens=500)])
    writer = agent.Writer(model, today=date(2026, 10, 7))

    draft = await writer.write("next 10 days?", gathered_data())

    assert draft == agent.Draft(text="MSFT goes ex-dividend.", truncated=False, tokens=500)
    # No tools: the writer can't fetch anything.
    assert model.tools == [None]
    system, user = model.shown[0]
    assert system.content == agent.WRITE_PROMPT
    # The failed call is an error the research model saw, not data.
    assert user.content == (
        "Today's date: 2026-10-07\n\n"
        "Question: next 10 days?\n\n"
        f'Data from dividend_calendar {{"days": 10}}:\n{CALENDAR.text}'
    )


def test_the_writer_is_told_when_research_was_cut_short() -> None:
    _, user = agent.write_messages("q", None, gathered_data(exhausted=agent.Limit.CALLS))
    assert "Today" not in user.content
    assert user.content.endswith(
        "(its calls budget ran out), so the data may be incomplete. Say what it covers."
    )


def test_the_writer_is_told_when_there_is_no_data() -> None:
    _, user = agent.write_messages("q", None, agent.Research())
    assert user.content == "Question: q\n\nNo data was retrieved."


async def test_an_empty_answer_is_not_a_draft() -> None:
    model = ScriptedModel([answers("  \n", tokens=300)])

    with pytest.raises(agent.NothingWrittenError) as caught:
        await agent.Writer(model).write("q", gathered_data())

    assert caught.value.tokens == 300


# ---- several calls in one reply -------------------------------------------


def days(*n: int) -> llm.ChatResponse:
    """A reply asking for the calendar once per window, all at once."""
    return asks(*(("dividend_calendar", {"days": d}) for d in n))


async def test_one_replys_calls_run_at_once() -> None:
    # The 30-day call is the slowest and the 10-day one the quickest.
    model = ScriptedModel([days(30, 20, 10), answers("done")])

    def echo(arguments: dict[str, Any]) -> quantic.Result:
        return quantic.Result(text=json.dumps(arguments), is_error=False)

    server = FakeServer({"dividend_calendar": echo}, delay=lambda a: a["days"] / 300)
    traced: list[int] = []

    gathered = agent.Research()
    await researcher(model, server).research(
        "q", gathered, on_call=lambda _, c: traced.append(c.arguments["days"])
    )

    assert server.peak == 3
    # Recorded as they finished...
    assert traced == [10, 20, 30]
    # ...and shown to the model in the order it asked.
    results = [json.loads(m.content)["days"] for m in model.shown[1] if m.role == "tool"]
    assert results == [30, 20, 10]


async def test_parallel_bounds_how_many_at_once() -> None:
    model = ScriptedModel([days(1, 2, 3, 4), answers("done")])
    server = FakeServer({"dividend_calendar": CALENDAR}, delay=lambda _: 0.05)
    r = agent.Researcher(
        model=model,
        server=server,
        tools=[DIVIDEND_CALENDAR],
        budget=agent.Budget(calls=10),
        parallel=2,
    )

    await research(r)

    assert server.peak == 2
    assert len(server.received) == 4


async def test_a_failure_waits_for_the_calls_beside_it() -> None:
    # One call finds the server gone at once; the other two are still
    # answering. They finish and are recorded before the failure is raised.
    gone = quantic.ToolServerUnavailableError("connection refused")
    model = ScriptedModel([days(10, 20, 30)])

    def some_gone(arguments: dict[str, Any]) -> quantic.Result | Exception:
        return gone if arguments["days"] == 10 else CALENDAR

    server = FakeServer({"dividend_calendar": some_gone}, delay=lambda a: a["days"] / 300)
    gathered = agent.Research()

    with pytest.raises(quantic.ToolServerUnavailableError):
        await researcher(model, server).research("q", gathered)

    assert sorted((c.arguments["days"], c.failed) for c in gathered.calls) == [
        (10, True),
        (20, False),
        (30, False),
    ]


async def test_calls_beyond_the_budget_are_dropped() -> None:
    model = ScriptedModel([days(10, 20, 30)])
    server = FakeServer({"dividend_calendar": CALENDAR})

    gathered = await research(researcher(model, server, agent.Budget(calls=2)))

    assert [a["days"] for _, a in server.received] == [10, 20]
    assert gathered.exhausted is agent.Limit.CALLS
