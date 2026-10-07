import json
from typing import Any

import pytest
from conftest import FakeOllama, Reply

from quantic_agent import evaltools, llm
from quantic_agent.evaltools import Case, judge

WINDOW = Case(
    name="explicit window",
    question="next 10 days?",
    want_tool="dividend_calendar",
    days_min=10,
    days_max=10,
)
NO_TOOL = Case(name="definition", question="what is an ex-date?", want_tool="")


def calls(*requests: tuple[str, dict[str, Any]]) -> llm.Message:
    return llm.Message(
        role="assistant",
        tool_calls=[
            llm.ToolCall(function=llm.FunctionCall(name=n, arguments=a)) for n, a in requests
        ],
    )


@pytest.mark.parametrize(
    ("case", "message", "correct", "valid", "reason"),
    [
        pytest.param(
            WINDOW, calls(("dividend_calendar", {"days": 10})), True, True, "", id="right"
        ),
        pytest.param(
            WINDOW,
            calls(("dividend_calendar", {"days": 30})),
            False,
            True,
            "asked for 30 days, want 10-10",
            id="wrong window",
        ),
        pytest.param(
            WINDOW,
            calls(("dividend_calendar", {"days": 180})),
            False,
            False,
            "dividend_calendar arguments: days: Input should be less than or equal to 120",
            id="out of bounds",
        ),
        pytest.param(
            WINDOW,
            calls(("no_such_tool", {})),
            False,
            False,
            "called a tool that doesn't exist",
            id="unknown tool",
        ),
        pytest.param(
            WINDOW,
            calls(("dividend_calendar", {"days": 10}), ("dividend_calendar", {"days": 10})),
            False,
            True,
            "made 2 calls where one was needed",
            id="two calls",
        ),
        pytest.param(
            WINDOW,
            llm.Message(role="assistant", content="MSFT"),
            False,
            True,
            "answered without calling dividend_calendar",
            id="no call",
        ),
        pytest.param(
            NO_TOOL,
            llm.Message(role="assistant", content="It's..."),
            True,
            True,
            "",
            id="none needed",
        ),
        pytest.param(
            NO_TOOL,
            calls(("dividend_calendar", {})),
            False,
            True,
            "called a tool for a question that needs none",
            id="unneeded call",
        ),
    ],
)
def test_judge(case: Case, message: llm.Message, correct: bool, valid: bool, reason: str) -> None:
    outcome = judge(case, message)
    assert (outcome.correct, outcome.valid, outcome.reason) == (correct, valid, reason)


def test_the_cases_are_well_formed() -> None:
    # The cases are data a person edits, so they're checked like code.
    cases = evaltools.load_cases()
    assert len(cases) == 8
    assert len({c.name for c in cases}) == len(cases)
    for c in cases:
        assert c.want_tool in ("", "dividend_calendar"), c.name
        assert 0 <= c.days_min <= c.days_max <= 120, c.name


def test_a_run_scores_each_model(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    # The fake model calls the calendar for 10 days whatever it's asked.
    ollama.replies["/api/chat"] = Reply(
        b'{"model":"m","message":{"role":"assistant","content":"","tool_calls":'
        b'[{"function":{"name":"dividend_calendar","arguments":{"days":10}}}]},"done":true}'
    )

    assert evaltools.main(["--ollama", ollama.url, "--models", "m", "--repeat", "2", "--json"]) == 0
    [score] = json.loads(capsys.readouterr().out)

    # Right for the explicit 10-day window, "no window" and "one company"; wrong elsewhere.
    assert (score["model"], score["runs"], score["correct"]) == ("m", 16, 6)
    # Each request showed the model exactly what the research loop shows it.
    assert ollama.bodies[0]["messages"][0]["role"] == "system"
    assert ollama.bodies[0]["tools"][0]["function"]["name"] == "dividend_calendar"
