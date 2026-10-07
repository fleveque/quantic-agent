"""The research loop: the model is offered tools, asks for the ones it needs,
and answers from what they return.

This is milestone 5's version: one question, a cap on tool calls, and a record
of every call. Milestone 8 grows it into the full loop of design §3.1 (budgets
for time and tokens, retries, phases), and the writing phase that follows it
never gets tools at all.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
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


# A question about one calendar needs one call; the cap stops a model that
# keeps asking.
DEFAULT_MAX_CALLS = 4

# The standing instruction for a research question. Prompts are code (design
# open question 6): they live here, reviewed like the rest.
SYSTEM_PROMPT = (
    "You answer questions about dividends and the companies that pay them. "
    "Use the tools for every fact, date and figure; never rely on memory for them. "
    "If the tools don't provide something, say so instead of guessing. "
    "Describe what the data shows. Do not recommend buying or selling anything."
)


class TooManyCallsError(Exception):
    """The model was still asking for tools when the cap was reached. Design
    §3.2 treats running out of budget as an outcome of the run, not a crash:
    every call made so far has already been recorded."""


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
class Answer:
    text: str = ""
    calls: list[Call] = field(default_factory=lambda: list[Call]())
    truncated: bool = False  # the model ran out of tokens mid-answer


@dataclass
class Researcher:
    """Answers questions with a model and a tool server. tools is the
    allowlist: the only tools offered, and the only ones run."""

    model: Model
    server: ToolServer | None
    tools: Sequence[Tool[Any]]
    max_calls: int = DEFAULT_MAX_CALLS

    async def ask(self, question: str, on_call: Callable[[Call], None] | None = None) -> Answer:
        """Runs the loop for one question, calling on_call with each tool call
        as it completes.

        A model mistake (an unknown tool, arguments that don't fit, a tool's
        refusal, a request the server rejects) is shown to the model as the
        tool's result so it can correct itself, and counts against the cap. A
        failure the model can't fix, such as the tool server being down, stops
        the loop: the exception propagates, and the call it happened in has
        already been recorded.
        """
        answer = Answer()

        def record(call: Call) -> None:
            answer.calls.append(call)
            if on_call is not None:
                on_call(call)

        messages = self.first_messages(question)
        definitions = self.tool_defs()
        while True:
            resp = await self.model.chat(messages, tools=definitions, think=False)
            if not resp.message.tool_calls:
                answer.text = resp.message.content
                answer.truncated = resp.truncated
                return answer

            # The model's request goes into the history unchanged, followed by
            # one tool message per call it made.
            messages.append(resp.message)
            for request in resp.message.tool_calls:
                if len(answer.calls) == self.max_calls:
                    raise TooManyCallsError(
                        f"the model was still asking for tools after {self.max_calls} calls"
                    )
                call = await self._run(request.function, record)
                messages.append(llm.Message(role="tool", tool_name=call.tool, content=call.result))

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

    async def _run(self, request: llm.FunctionCall, record: Callable[[Call], None]) -> Call:
        """Runs one tool call and records it, whatever happens. Only a failure
        the model can't fix is raised."""
        start = time.monotonic()
        call = Call(tool=request.name, arguments=request.arguments)

        def finish(result: str, *, failed: bool = False) -> Call:
            call.result, call.failed = result, failed
            call.duration = timedelta(seconds=time.monotonic() - start)
            record(call)
            return call

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
            raise RuntimeError("Researcher.ask needs a tool server")
        try:
            result = await self.server.call_tool(tool.name, args.model_dump())
        except quantic.RPCError as err:
            return finish(f"error: {err}", failed=True)  # the request was at fault
        except quantic.ToolServerError as err:
            finish(f"error: {err}", failed=True)
            raise
        if result.is_error:
            return finish(f"error: {result.text}", failed=True)  # the tool ran and declined
        return finish(result.text)


# The real clients must keep matching the Protocols. These lines run nothing;
# pyright checks the assignments, so a client whose method signature drifts
# fails the type check here instead of surprising the loop later.
if TYPE_CHECKING:
    _model: type[Model] = llm.Client
    _server: type[ToolServer] = quantic.Server
