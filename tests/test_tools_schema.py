"""Tools as Pydantic models: the arguments class is the schema."""

import json
from pathlib import Path

import pytest

from quantic_agent.tools import DIVIDEND_CALENDAR, ArgumentsError

FIXTURES = Path(__file__).parent / "fixtures"


def test_the_schema_comes_from_the_arguments_model() -> None:
    assert DIVIDEND_CALENDAR.schema() == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "days": {
                "type": "integer",
                "default": 45,
                "maximum": 120,
                "description": (
                    "How many days ahead to look, counting from today. Defaults to 45; at most 120."
                ),
            }
        },
    }


def test_dividend_calendar_matches_the_server() -> None:
    # The server publishes its own schema for each tool. Ours is written
    # independently, as a model, so this test is what notices if the two
    # drift apart: a renamed argument, a changed type.
    listed = json.loads((FIXTURES / "mcp" / "tools-list.json").read_text())  # from quantic.finance
    server = next(t for t in listed["result"]["tools"] if t["name"] == "dividend_calendar")
    theirs = server["inputSchema"]["properties"]
    ours = DIVIDEND_CALENDAR.schema()["properties"]

    assert ours.keys() == theirs.keys()
    for name, prop in theirs.items():
        assert ours[name]["type"] == prop["type"], name


def test_our_description_gives_no_buying_advice() -> None:
    # The server's description ends "buy before the ex-date to receive the next
    # dividend"; the agent is informational, never advisory (design N5).
    assert "buy" not in DIVIDEND_CALENDAR.description.lower()


@pytest.mark.parametrize(
    ("raw", "days"),
    [
        pytest.param({"days": 10}, 10, id="given"),
        pytest.param({}, 45, id="left out: the server's default"),
        pytest.param({"days": 120}, 120, id="the maximum"),
    ],
)
def test_decode_args(raw: dict[str, object], days: int) -> None:
    assert DIVIDEND_CALENDAR.decode_args(raw).days == days


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        pytest.param({"days": 180}, "days: Input should be less than or equal to 120", id="over"),
        pytest.param({"days": "10"}, "days: Input should be a valid integer", id="a string"),
        pytest.param({"days": None}, "days: Input should be a valid integer", id="null"),
        pytest.param({"nights": 3}, "nights: Extra inputs are not permitted", id="unknown"),
    ],
)
def test_decode_args_is_strict(raw: dict[str, object], message: str) -> None:
    with pytest.raises(ArgumentsError) as err:
        DIVIDEND_CALENDAR.decode_args(raw)
    # Written for the model, which is shown it so it can try again.
    assert str(err.value) == f"dividend_calendar arguments: {message}"
