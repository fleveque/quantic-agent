"""The quantic-evaltools command: how well models choose and call tools.

It runs a fixed set of questions whose right first move is known
(eval_cases.json) and judges each model's first reply: the right tool (or
correctly none), with arguments that validate and make sense. Decision 0005
chooses models by measurement on this agent's own tasks; this is the first such
measurement. It scores only the first reply, so it needs Ollama but not
Quantic, and its verdicts don't depend on what the calendar holds today.

Each case runs several times per model: sampling varies between runs, and a
model that is right three times out of five is not the same as one that is
right every time.
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, TypeAdapter

from quantic_agent import agent, llm
from quantic_agent.cli import cancel_on_sigterm
from quantic_agent.tools import (
    DIVIDEND_CALENDAR,
    GET_STOCK,
    ArgumentsError,
    DividendCalendarArgs,
    GetStockArgs,
    Tool,
)

DEFAULT_MODELS = "qwen3.5:9b,qwen3.6:35b,hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S"
DEFAULT_TIMEOUT = 600.0
ALLOWED: list[Tool[Any]] = [DIVIDEND_CALENDAR, GET_STOCK]


class Case(BaseModel):
    """One question and its right first move. want_tool "" means the right
    move is not to call a tool; or_tool is another tool that's also right.
    days_min and days_max both 0 accept any window. symbols, for get_stock,
    are the companies the first reply must ask for, all of them at once: one
    call each, in the same reply."""

    name: str
    question: str
    want_tool: str
    or_tool: str = ""
    days_min: int = 0
    days_max: int = 0
    symbols: list[str] = []


class Outcome(BaseModel):
    """One run of one case. valid: a tool call naming a real tool with
    arguments that validate (answering directly is always valid)."""

    case: str
    correct: bool = False
    valid: bool = False
    called: str = ""
    args: str = ""
    reason: str = ""


class Score(BaseModel):
    model: str
    runs: int = 0
    correct: int = 0
    outcomes: list[Outcome] = []


_CASES = TypeAdapter(list[Case])
_SCORES = TypeAdapter(list[Score])


def load_cases() -> list[Case]:
    """The cases, read from the package itself. They're data a person edits,
    shipped with the code and versioned with it (design open question 6)."""
    return _CASES.validate_json(files("quantic_agent").joinpath("eval_cases.json").read_bytes())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quantic-evaltools",
        description="Measure how reliably models choose and call tools.",
    )
    parser.add_argument(
        "--ollama",
        default=os.environ.get("OLLAMA_HOST") or llm.DEFAULT_BASE_URL,
        help="model server URL (default: $OLLAMA_HOST, else %(default)s)",
    )
    parser.add_argument(
        "--models", default=DEFAULT_MODELS, help="comma-separated models to evaluate"
    )
    parser.add_argument("--repeat", type=int, default=5, help="runs per case per model")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="give up on any single request after this long (default: %(default)g)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit results as JSON instead of a table"
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt, asyncio.CancelledError:
        print("quantic-evaltools: stopped", file=sys.stderr)
        return 130


async def _run(args: argparse.Namespace) -> int:
    cancel_on_sigterm()
    cases = load_cases()
    scores: list[Score] = []
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        async with llm.Client(args.ollama, name) as model:
            try:
                scores.append(await evaluate(model, cases, args.repeat, args.timeout or None))
            except (llm.LLMError, TimeoutError) as err:
                # A model that can't answer at all has no score.
                print(f"quantic-evaltools: {name}: {err or 'timed out'}", file=sys.stderr)
    if not scores:
        return 1
    if args.json:
        print(_SCORES.dump_json(scores, indent=2).decode())
    else:
        _write_table(scores, cases)
    return 0


async def evaluate(
    model: llm.Client, cases: list[Case], repeat: int, timeout: float | None
) -> Score:
    """Runs every case repeat times against one model. The model is shown
    exactly what the research loop shows it."""
    researcher = agent.Researcher(model=model, server=None, tools=ALLOWED)
    score = Score(model=model.model)
    for case in cases:
        for _ in range(repeat):
            async with asyncio.timeout(timeout):
                resp = await model.chat(
                    researcher.first_messages(case.question),
                    tools=researcher.tool_defs(),
                    think=False,
                )
            outcome = judge(case, resp.message)
            score.outcomes.append(outcome)
            score.runs += 1
            score.correct += outcome.correct
    return score


def judge(case: Case, message: llm.Message) -> Outcome:
    """Whether a model's first reply was the right move."""
    outcome = Outcome(case=case.name)
    if not message.tool_calls:
        outcome.valid = True  # answering directly is always a well-formed move
        outcome.correct = case.want_tool == ""
        if not outcome.correct:
            outcome.reason = f"answered without calling {case.want_tool}"
        return outcome

    calls = [c.function for c in message.tool_calls]
    outcome.called = ",".join(c.name for c in calls)
    outcome.args = ",".join(json.dumps(c.arguments, separators=(",", ":")) for c in calls)
    decoded: list[Any] = []
    for call in calls:
        tool = next((t for t in ALLOWED if t.name == call.name), None)
        if tool is None:
            outcome.reason = "called a tool that doesn't exist"
            return outcome
        try:
            decoded.append(tool.decode_args(call.arguments))
        except ArgumentsError as err:
            outcome.reason = str(err)
            return outcome
    outcome.valid = True

    names = {c.name for c in calls}
    if case.want_tool == "":
        outcome.reason = "called a tool for a question that needs none"
    elif len(names) > 1 or not names <= {case.want_tool, case.or_tool}:
        outcome.reason = "called the wrong tool"
    elif names == {GET_STOCK.name}:
        got = sorted(a.symbol.upper() for a in decoded if isinstance(a, GetStockArgs))
        want = sorted(case.symbols) if case.symbols else got
        if got != want:
            outcome.reason = f"asked for {', '.join(got)}, want {', '.join(want)}"
        else:
            outcome.correct = True
    elif len(calls) > 1:
        outcome.reason = f"made {len(calls)} calls where one was needed"
    else:
        [args] = decoded
        assert isinstance(args, DividendCalendarArgs)
        if case.days_max > 0 and not case.days_min <= args.days <= case.days_max:
            outcome.reason = f"asked for {args.days} days, want {case.days_min}-{case.days_max}"
        else:
            outcome.correct = True
    return outcome


def _write_table(scores: list[Score], cases: list[Case]) -> None:
    rows = [["CASE", *(s.model for s in scores)]]
    for case in cases:
        row = [case.name]
        for s in scores:
            runs = [o for o in s.outcomes if o.case == case.name]
            row.append(f"{sum(o.correct for o in runs)}/{len(runs)}")
        rows.append(row)
    rows.append(
        ["TOTAL", *(f"{s.correct}/{s.runs} ({100 * s.correct / s.runs:.0f}%)" for s in scores)]
    )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())

    # The reasons are the useful part when a model gets something wrong.
    for s in scores:
        seen: set[str] = set()
        for o in s.outcomes:
            key = f"{o.case}: {o.reason}"
            if o.correct or key in seen:
                continue
            seen.add(key)
            called = f" · {o.called} {o.args}" if o.called else ""
            print(f"\n{s.model} · {o.case} · {o.reason}{called}", end="")
    print()
