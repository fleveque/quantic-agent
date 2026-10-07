"""The tools the research loop can call.

Two kinds so far. Quantic's tools, run on its MCP server: each is a Tool here,
with the agent's own description and an arguments model whose fields are the
schema the model is shown. And the deterministic calculators from design §3.3:
when a draft needs a derived figure (a percentage change, a difference, a
total), the model calls one of these instead of doing the arithmetic itself,
so the result enters the provenance manifest like any other tool response.
Their results are full float precision. Rounding is presentation, and
presentation belongs to the Phoenix template (docs/rendering.md).
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ToolArgs(BaseModel):
    """The base of every tool's arguments: strict on purpose. An argument the
    tool doesn't take, or a value of the wrong type ("10" for 10), is an error
    to show the model, not something to drop or convert quietly."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ArgumentsError(Exception):
    """A model's arguments don't fit the tool. The message is written for the
    model, which is shown it so it can try again."""


@dataclass(frozen=True)
class Tool[A: ToolArgs]:
    """A tool the research loop may offer the model: the name it calls it by,
    a description written for the model, and the model class its arguments
    must validate into. That class is the schema: what the model is shown and
    what its arguments are checked against can't disagree."""

    name: str
    description: str
    args: type[A]

    def schema(self) -> dict[str, Any]:
        """The arguments' JSON Schema, without the titles Pydantic adds, which
        only repeat the names to the model."""
        return _without_titles(self.args.model_json_schema())

    def decode_args(self, raw: dict[str, Any]) -> A:
        """Checks the arguments a model produced. Bounds in the schema are
        enforced here: a limit stated only to the model is one it can ignore,
        and the evaluation showed that it does."""
        try:
            return self.args.model_validate(raw)
        except ValidationError as err:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in e['loc']) or 'arguments'}: {e['msg']}"
                for e in err.errors()
            )
            raise ArgumentsError(f"{self.name} arguments: {problems}") from err


def _without_titles(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key == "properties":
            props: dict[str, dict[str, Any]] = value
            value = {name: _without_titles(prop) for name, prop in props.items()}
        out[key] = value
    return out


class DividendCalendarArgs(ToolArgs):
    days: int = Field(
        default=45,
        le=120,
        description=(
            "How many days ahead to look, counting from today. Defaults to 45; at most 120."
        ),
    )


# One of Quantic's public reference tools: the same answer for every caller, no
# account needed. The description is the agent's own, not the server's. The
# server's ends with buying advice ("buy before the ex-date to receive the next
# dividend"), and the agent's output is informational, never advisory (design
# N5). What the model is told a tool is for shapes what it writes.
DIVIDEND_CALENDAR = Tool(
    name="dividend_calendar",
    description=(
        "List the companies going ex-dividend soon, soonest first. Each entry has the "
        "company name, symbol, sector, ex-dividend date (YYYY-MM-DD) and how often it "
        "pays. The list starts today and covers the given number of days."
    ),
    args=DividendCalendarArgs,
)


def pct_change(previous: float, current: float) -> float:
    """The percentage change from previous to current: 1.50 → 1.55 is 3.33…, not 0.0333….

    previous must be positive. A zero base has no percentage change, and a
    negative one produces a sign that reads backwards (-2 → -1 is "-50%").
    Both are refused: a calculator that declines leaves the draft without a
    figure, which is safe; one that returns a misleading figure is not.
    """
    if previous <= 0:
        raise ValueError(f"pct_change needs a positive previous value, got {previous}")
    return (current - previous) / previous * 100


def diff(previous: float, current: float) -> float:
    """current minus previous."""
    return current - previous


def total(*values: float) -> float:
    """The sum of values. The sum of no values is 0.

    Named total so it doesn't hide the built-in sum, which it uses: since
    Python 3.12, sum() of floats compensates for rounding as it adds.
    """
    return sum(values, 0.0)
