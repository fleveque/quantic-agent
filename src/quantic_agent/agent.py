"""A question answered in two phases (design §3.1).

Research is a loop: the model is offered tools, asks for the ones it needs,
and sees what they return, within a budget. Writing is one model call with no
tools at all: it gets the question and the data research gathered, and
nothing else, so it can't fetch, and it can't wander.
"""

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from quantic_agent import llm, quantic
from quantic_agent.tools import ArgumentsError, Tool


class Model(Protocol):
    """What the loop needs from a language model. llm.Client has it.

    A Protocol is satisfied by any class with matching methods, without
    naming the Protocol, as a Go interface is. It lives here, with the code
    that uses it: the consumer says what it needs, and tests supply a fake.
    """

    async def chat(
        self,
        messages: Sequence[llm.Message],
        *,
        tools: Sequence[llm.ToolDef] | None = None,
        think: bool | None = None,
        options: llm.Options | None = None,
    ) -> llm.ChatResponse: ...


class ToolServer(Protocol):
    """What the loop needs from Quantic. quantic.Server has it."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> quantic.Result: ...


@dataclass(frozen=True)
class Budget:
    """Bounds the research phase (design §3.2). Running out is not a failure:
    research stops, and writing goes ahead with what was gathered. The third
    bound, wall-clock time, is the caller's asyncio.timeout.

    The defaults are for one question. A question about one calendar needs
    one call and about 2,000 tokens; one about the companies in a 14-day
    calendar needed ten calls (the calendar, then get_stock for nine) and
    about 10,000 tokens of research (measured, lesson 09). Sixteen calls
    cover the calendar and fifteen companies; the tokens leave room for a
    model that corrects itself a few times, and stop one that keeps asking.
    """

    calls: int = 16  # tool calls
    tokens: int = 64_000  # tokens the model processes and generates


DEFAULT_BUDGET = Budget()


class Limit(StrEnum):
    """The budget that stopped research early."""

    CALLS = "calls"
    TOKENS = "tokens"


# The standing instruction for the research phase. Prompts are code (design
# open question 6): they live here, reviewed like the rest.
SYSTEM_PROMPT = (
    "You answer questions about dividends and the companies that pay them. "
    "Use the tools for every fact, date and figure; never rely on memory for them. "
    "If the tools don't provide something, say so instead of guessing. "
    "Describe what the data shows. Do not recommend buying or selling anything."
)


@dataclass
class Call:
    """One tool call: what the model asked for and what it got back. The audit
    log of design N3 in miniature: from these, an answer can be traced to the
    data it was given."""

    tool: str
    arguments: dict[str, Any]
    result: str = ""  # the tool's output, or the error the model was shown
    failed: bool = False  # result is an error, not data
    duration: timedelta = timedelta()


@dataclass
class Research:
    """What the research phase gathered: the calls it made, in order, the
    tokens it used, and the budget that stopped it, if one did."""

    calls: list[Call] = field(default_factory=lambda: list[Call]())
    tokens: int = 0
    exhausted: Limit | None = None  # None when the model finished on its own

    @property
    def has_data(self) -> bool:
        """Whether research gathered anything to write from: at least one call
        that succeeded. A model that answered without calling a tool, or whose
        every call was refused, gathered nothing, and writing would only
        produce an answer about nothing."""
        return any(not c.failed for c in self.calls)


@dataclass
class Researcher:
    """Runs the research phase with a model and a tool server. tools is the
    allowlist: the only tools offered, and the only ones run."""

    model: Model
    server: ToolServer | None
    tools: Sequence[Tool[Any]]
    budget: Budget = DEFAULT_BUDGET
    # How many of one reply's tool calls run at once. The rest wait their
    # turn; the tool server's own rate limit applies on top (quantic.Pace).
    parallel: int = 4
    # Sent with every model call: num_ctx above all (llm.Options).
    options: llm.Options | None = None

    async def research(
        self,
        question: str,
        gathered: Research,
        on_call: Callable[[int, Call], None] | None = None,
    ) -> None:
        """Runs the loop for one question until the model stops asking for
        tools or a budget runs out, calling on_call with each tool call and
        its position in the run as it completes.

        gathered is continued in place: a new run passes Research(), a resumed
        one what its record holds. Its calls are replayed to the model as if
        just made, without calling the tools again, and count against the
        budget like new ones. It is updated as the loop goes, so when the loop
        raises, it still says what was done and what it cost.

        A model mistake (an unknown tool, arguments that don't fit, a tool's
        refusal, a request the server rejects) is shown to the model as the
        tool's result so it can correct itself, and counts against the budget.
        A failure the model can't fix, such as the tool server being down,
        stops the loop: the exception propagates, and the call it happened in
        has already been recorded.

        When one reply asks for several tools, they run at once, at most
        parallel at a time, and each is recorded as it completes, so their
        positions in the run are the order they finished in. The model is
        shown the results in the order it asked.

        When the model stops asking, whatever it says is discarded: the answer
        is the writing phase's job.
        """
        gathered.exhausted = None
        messages = self.first_messages(question) + replay(gathered.calls)
        definitions = self.tool_defs()

        def record(call: Call) -> None:
            gathered.calls.append(call)
            if on_call is not None:
                on_call(len(gathered.calls) - 1, call)

        while True:
            # Checked before asking (a resumed run may have spent its tokens
            # already) and again after: a reply that crosses the budget has
            # its requests dropped rather than run.
            if gathered.tokens >= self.budget.tokens:
                gathered.exhausted = Limit.TOKENS
                return
            resp = await self.model.chat(
                messages, tools=definitions, think=False, options=self.options
            )
            gathered.tokens += resp.prompt_eval_count + resp.eval_count
            if not resp.message.tool_calls:
                return
            if gathered.tokens >= self.budget.tokens:
                gathered.exhausted = Limit.TOKENS
                return

            # The model's request goes into the history unchanged, followed by
            # one tool message per call it made. Requests beyond the call
            # budget are dropped, as before, and end research.
            messages.append(resp.message)
            room = self.budget.calls - len(gathered.calls)
            requests = [r.function for r in resp.message.tool_calls[: max(room, 0)]]
            for call in await self._run_all(requests, record):
                messages.append(llm.Message(role="tool", tool_name=call.tool, content=call.result))
            if len(resp.message.tool_calls) > len(requests):
                gathered.exhausted = Limit.CALLS
                return

    def first_messages(self, question: str) -> list[llm.Message]:
        """The conversation that opens the loop: the standing instructions and
        the question. Public so an evaluation shows a model exactly what the
        loop shows it."""
        return [
            llm.Message(role="system", content=SYSTEM_PROMPT),
            llm.Message(role="user", content=question),
        ]

    def tool_defs(self) -> list[llm.ToolDef]:
        """The allowlisted tools, as the model is shown them."""
        return [
            llm.ToolDef(
                function=llm.FunctionDef(
                    name=t.name, description=t.description, parameters=t.schema()
                )
            )
            for t in self.tools
        ]

    async def _run_all(
        self, requests: Sequence[llm.FunctionCall], record: Callable[[Call], None]
    ) -> list[Call]:
        """Runs one reply's tool calls at once, at most parallel at a time, and
        returns them in the order they were asked for. If any hit a failure
        the model can't fix, the first such failure is raised, once every
        call has finished and been recorded.

        Each task returns its failure instead of raising it. In a TaskGroup,
        a task that raises cancels its siblings: their calls would end
        unfinished and unrecorded, and the audit log would lose calls that
        were already on their way to the server.
        """
        slots = asyncio.Semaphore(self.parallel)

        async def one(request: llm.FunctionCall) -> tuple[Call, quantic.ToolServerError | None]:
            async with slots:
                return await self._run(request, record)

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(one(r)) for r in requests]
        done = [t.result() for t in tasks]
        failure = next((err for _, err in done if err is not None), None)
        if failure is not None:
            raise failure
        return [call for call, _ in done]

    async def _run(
        self, request: llm.FunctionCall, record: Callable[[Call], None]
    ) -> tuple[Call, quantic.ToolServerError | None]:
        """Runs one tool call and records it, whatever happens. A failure the
        model can't fix is returned beside the call, for the caller to raise."""
        start = time.monotonic()
        call = Call(tool=request.name, arguments=request.arguments)

        def finish(
            result: str, *, failed: bool = False, error: quantic.ToolServerError | None = None
        ) -> tuple[Call, quantic.ToolServerError | None]:
            call.result, call.failed = result, failed
            call.duration = timedelta(seconds=time.monotonic() - start)
            record(call)
            return call, error

        tool = next((t for t in self.tools if t.name == request.name), None)
        if tool is None:
            names = ", ".join(t.name for t in self.tools)
            return finish(
                f"error: there is no tool called {request.name!r}; the tools are: {names}",
                failed=True,
            )
        try:
            args = tool.decode_args(request.arguments)
        except ArgumentsError as err:
            return finish(f"error: {err}", failed=True)

        if self.server is None:
            raise RuntimeError("Researcher.research needs a tool server")
        try:
            result = await self.server.call_tool(tool.name, args.model_dump())
        except quantic.RPCError as err:
            return finish(f"error: {err}", failed=True)  # the request was at fault
        except quantic.ToolServerError as err:
            return finish(f"error: {err}", failed=True, error=err)
        if result.is_error:
            return finish(f"error: {result.text}", failed=True)  # the tool ran and declined
        return finish(result.text)


def replay(calls: Sequence[Call]) -> list[llm.Message]:
    """Recorded calls turned back into the conversation that produced them:
    for each, the model's request and the tool's result. A model that asked
    for two tools in one message gets them back as two messages, one call
    each, which says the same thing."""
    messages: list[llm.Message] = []
    for c in calls:
        request = llm.ToolCall(function=llm.FunctionCall(name=c.tool, arguments=c.arguments))
        messages.append(llm.Message(role="assistant", tool_calls=[request]))
        messages.append(llm.Message(role="tool", tool_name=c.tool, content=c.result))
    return messages


# ---- writing ---------------------------------------------------------------

# The standing instruction for the writing phase. The writer is shown the data
# and nothing else, and offered no tools.
WRITE_PROMPT = (
    "You write short, factual answers about dividends and the companies that pay them. "
    "Use only the data you are given: every company, date and figure you mention must appear "
    "in it. "
    "Do not work out new figures from it, such as counts, sums, averages or durations. "
    "If the data doesn't answer the question, say so. "
    "Describe what the data shows. Do not recommend buying or selling anything."
)


class NothingWrittenError(Exception):
    """The writer's reply had no text: nothing to check, and nothing to keep.
    tokens is what the attempt cost."""

    def __init__(self, tokens: int) -> None:
        super().__init__("the model wrote nothing")
        self.tokens = tokens


@dataclass(frozen=True)
class Draft:
    """What the writing phase produced."""

    text: str
    truncated: bool  # the model ran out of tokens mid-answer
    tokens: int


@dataclass
class Writer:
    """Runs the writing phase: one model call, no tools.

    today is the date the research was done, which the writer is told: left
    to itself, it guesses (one answer in the Go version worked from "October
    2023"). None tells it nothing.
    """

    model: Model
    today: date | None = None
    options: llm.Options | None = None

    async def write(self, question: str, research: Research) -> Draft:
        """Answers question from what research gathered."""
        messages = write_messages(question, self.today, research)
        resp = await self.model.chat(messages, think=False, options=self.options)
        tokens = resp.prompt_eval_count + resp.eval_count
        if not resp.message.content.strip():
            raise NothingWrittenError(tokens)
        return Draft(text=resp.message.content, truncated=resp.truncated, tokens=tokens)


def write_messages(question: str, today: date | None, research: Research) -> list[llm.Message]:
    """The writer's whole view of the world: the standing instruction, today's
    date, the question, and each successful call's result labelled with the
    call that produced it. Failed calls are left out: they are errors the
    research model was shown, not data. Public, so the prompt can be inspected
    exactly as the model gets it."""
    parts: list[str] = []
    if today is not None:
        parts.append(f"Today's date: {today.isoformat()}")
    parts.append(f"Question: {question}")
    data = [c for c in research.calls if not c.failed]
    for c in data:
        parts.append(f"Data from {c.tool} {json.dumps(c.arguments)}:\n{c.result}")
    if not data:
        parts.append("No data was retrieved.")
    if research.exhausted is not None:
        parts.append(
            f"The research stopped before it was finished (its {research.exhausted} budget "
            "ran out), so the data may be incomplete. Say what it covers."
        )
    return [
        llm.Message(role="system", content=WRITE_PROMPT),
        llm.Message(role="user", content="\n\n".join(parts)),
    ]


# The real clients must keep matching the Protocols. These lines run nothing;
# pyright checks the assignments, so a client whose method signature drifts
# fails the type check here instead of surprising the loop later.
if TYPE_CHECKING:
    _model: type[Model] = llm.Client
    _server: type[ToolServer] = quantic.Server
