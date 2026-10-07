"""The quantic-agent command.

It still has no scheduled tasks. What it can do so far: --check reports the
model server and its models, --ask sends one prompt and prints the reply, and
--research answers a question with Quantic's tools, tracing each tool call to
stderr as it completes.

Exit status: 0 success, 1 failure (including --timeout running out), 2 wrong
usage, 3 the model server or the MCP server wasn't there to answer, 130
stopped by Ctrl-C or
SIGTERM. 3 means nothing was attempted, so a scheduler can simply run the same
command again later (design §3.6). On 130 the request in flight was
cancelled, and Ollama stops working on it too.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Sequence
from importlib.metadata import version

from quantic_agent import agent, llm, quantic
from quantic_agent.tools import DIVIDEND_CALENDAR

# The safe choice for the target hardware (design §4): it fits any 16GB card
# with room to spare. Development happens on a different machine, so both
# options below read an environment variable first and nothing is baked in.
DEFAULT_MODEL = "qwen3.5:9b"

# Exit statuses, as documented at the top of this file. 2 is argparse's.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNAVAILABLE = 3
EXIT_INTERRUPTED = 130  # 128 + SIGINT, the shell's convention for Ctrl-C

# Bounds one run, in seconds. The slowest request measured on the target
# machine took 94s (a 27B partly in system RAM, 64K context) and the slowest
# cold load 31s, so five minutes leaves more than double. It must never be
# short enough to cut off a load: cancelling a load aborts it, and the next
# attempt starts from zero.
DEFAULT_TIMEOUT = 300.0


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the command and returns its exit status.

    A usage mistake, --help and --version end the run from inside argparse by
    raising SystemExit (2 for a mistake, 0 for the others). Every other status
    is returned.
    """
    parser = argparse.ArgumentParser(
        prog="quantic-agent",
        description="Drafts data-grounded content for Quantic with a local model.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('quantic-agent')}",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="report the model server and its models"
    )
    action.add_argument("--ask", metavar="PROMPT", help="send one prompt and print the reply")
    action.add_argument(
        "--research", metavar="QUESTION", help="answer a question using Quantic's tools"
    )
    parser.add_argument(
        "--ollama",
        default=os.environ.get("OLLAMA_HOST") or llm.DEFAULT_BASE_URL,
        help="model server URL (default: $OLLAMA_HOST, else %(default)s)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("QUANTIC_MODEL") or DEFAULT_MODEL,
        help="model to generate with (default: $QUANTIC_MODEL, else %(default)s)",
    )
    parser.add_argument(
        "--mcp",
        default=os.environ.get("QUANTIC_MCP_URL") or quantic.DEFAULT_URL,
        help="Quantic's MCP server (default: $QUANTIC_MCP_URL, else %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="give up on the model server after this long; 0 for no limit (default: %(default)g)",
    )
    args = parser.parse_args(argv)

    if not args.check and args.ask is None and args.research is None:
        print("quantic-agent: no tasks defined yet")
        return EXIT_OK

    # asyncio.run turns Ctrl-C into a cancellation of _run, then re-raises it
    # here as KeyboardInterrupt once _run has unwound. SIGTERM cancels _run
    # too (cancel_on_sigterm), and arrives as the CancelledError itself.
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt, asyncio.CancelledError:
        _error("stopped; the request in flight was cancelled")
        return EXIT_INTERRUPTED


async def _run(args: argparse.Namespace) -> int:
    cancel_on_sigterm()
    async with llm.Client(args.ollama, args.model) as client:
        try:
            # One deadline for the whole run, whatever it does inside; None
            # means no limit.
            async with asyncio.timeout(args.timeout or None):
                if args.check:
                    return await _check(client, args.ollama)
                if args.research is not None:
                    return await _research(client, args.mcp, args.research)
                return await _ask(client, args.ask)
        except TimeoutError:
            _error(
                f"gave up after {args.timeout:g}s (--timeout). A cold model can take "
                "half a minute to load, and a long generation longer."
            )
            return EXIT_FAILED
        except (llm.LLMError, quantic.ToolServerError, agent.TooManyCallsError) as err:
            return _fail(err, args)


def cancel_on_sigterm() -> None:
    """Makes SIGTERM, what systemd sends to stop a service, cancel the running
    task the way Ctrl-C does. Only the first one: after it, SIGTERM is back to
    its default, so a second one ends the process at once instead of waiting
    for a clean stop."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is None:
        return

    def stop() -> None:
        loop.remove_signal_handler(signal.SIGTERM)
        task.cancel()

    loop.add_signal_handler(signal.SIGTERM, stop)


def _fail(err: Exception, args: argparse.Namespace) -> int:
    """Reports err and chooses the exit status, by the kind of error: its
    class, never its message, which is for people and can change."""
    match err:
        case llm.ServerUnavailableError():
            _error(f"no model server answering at {args.ollama}. Is Ollama running?")
            _error(str(err))
            return EXIT_UNAVAILABLE
        case quantic.ToolServerUnavailableError():
            _error(f"no MCP server answering at {args.mcp}.")
            _error(str(err))
            return EXIT_UNAVAILABLE
        case agent.TooManyCallsError():
            _error(f"the model kept asking for tools and never answered: {err}")
        case llm.ModelNotFoundError():
            _not_pulled(args.model)
        case llm.APIError(status_code=status) if status >= 500:
            # The server itself failed, such as a model it couldn't load. The
            # reason is in its log, not in the reply.
            _error(str(err))
            _error("the model server failed; its log has the cause (journalctl -u ollama)")
        case _:
            _error(str(err))
    return EXIT_FAILED


def _not_pulled(model: str) -> None:
    _error(f"{model} is not on this server. Pull it with: ollama pull {model}")


def _error(message: str) -> None:
    print(f"quantic-agent: {message}", file=sys.stderr)


async def _check(client: llm.Client, base_url: str) -> int:
    print(f"ollama {await client.version()} at {base_url}")
    selected = False
    for m in await client.models():
        # Names compare case-insensitively because that is how Ollama
        # resolves them.
        marker = " "
        if m.name.casefold() == client.model.casefold():
            marker, selected = "*", True
        print(
            f"{marker} {m.name:<26} {m.size / 1e9:5.1f} GB  {m.details.parameter_size:<6} "
            f"{m.details.quantization_level:<7} ctx {short_count(m.details.context_length):<5} "
            f"{' '.join(m.capabilities)}"
        )
    # The agent runs where its developer isn't sitting, so a model that was
    # never pulled has to be loud now rather than a 404 mid-task.
    if not selected:
        _not_pulled(client.model)
        return EXIT_FAILED
    return EXIT_OK


async def _research(client: llm.Client, mcp_url: str, question: str) -> int:
    async with quantic.Server(mcp_url) as server:
        researcher = agent.Researcher(model=client, server=server, tools=[DIVIDEND_CALENDAR])
        answer = await researcher.ask(question, on_call=_trace)
    print(answer.text)
    if answer.truncated:
        _error("the answer was truncated: the model hit its token limit")
    return EXIT_OK


def _trace(call: agent.Call) -> None:
    """One line per tool call on stderr: what was asked, and what came back."""
    outcome = call.result if call.failed else f"{len(call.result)} bytes"
    ms = round(call.duration.total_seconds() * 1000)
    print(f"tool {call.tool} {json.dumps(call.arguments)} → {outcome} ({ms}ms)", file=sys.stderr)


async def _ask(client: llm.Client, prompt: str) -> int:
    # Thinking is suppressed: the agent wants the answer, and a reasoning
    # trace is text nothing downstream is allowed to publish.
    resp = await client.generate(prompt, think=False)
    print(resp.response)
    # The run line goes to stderr so that stdout stays pipeable.
    note = " · truncated: hit the token limit" if resp.truncated else ""
    ms = round(resp.eval_duration.total_seconds() * 1000)
    print(f"{resp.model} · {resp.eval_count} tokens · {ms}ms{note}", file=sys.stderr)
    return EXIT_OK


def short_count(n: int) -> str:
    """A context length the way model cards write it: 262144 as 256K."""
    if n >= 1024 * 1024:
        return f"{n // (1024 * 1024)}M"
    if n >= 1024:
        return f"{n // 1024}K"
    return str(n)
