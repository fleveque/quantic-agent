"""The quantic-agent command.

It still has no scheduled tasks. What it can do so far is reach the local
model server: --check reports the server and its models, --ask sends one
prompt and prints the reply.

Exit status: 0 success, 1 failure, 2 wrong usage, 3 the model server wasn't
there to answer. 3 means nothing was attempted, so a scheduler can simply run
the same command again later (design §3.6).
"""

import argparse
import os
import sys
from collections.abc import Sequence
from importlib.metadata import version

from quantic_agent import llm

# The safe choice for the target hardware (design §4): it fits any 16GB card
# with room to spare. Development happens on a different machine, so both
# options below read an environment variable first and nothing is baked in.
DEFAULT_MODEL = "qwen3.5:9b"

# Exit statuses, as documented at the top of this file. 2 is argparse's.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNAVAILABLE = 3


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
    args = parser.parse_args(argv)

    if not args.check and args.ask is None:
        print("quantic-agent: no tasks defined yet")
        return EXIT_OK

    with llm.Client(args.ollama, args.model) as client:
        try:
            if args.check:
                return _check(client, args.ollama)
            return _ask(client, args.ask)
        except llm.LLMError as err:
            return _fail(err, args.ollama, args.model)


def _fail(err: llm.LLMError, base_url: str, model: str) -> int:
    """Reports err and chooses the exit status, by the kind of error: its
    class, never its message, which is for people and can change."""
    match err:
        case llm.ServerUnavailableError():
            _error(f"no model server answering at {base_url}. Is Ollama running?")
            _error(str(err))
            return EXIT_UNAVAILABLE
        case llm.ModelNotFoundError():
            _not_pulled(model)
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


def _check(client: llm.Client, base_url: str) -> int:
    print(f"ollama {client.version()} at {base_url}")
    selected = False
    for m in client.models():
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


def _ask(client: llm.Client, prompt: str) -> int:
    # Thinking is suppressed: the agent wants the answer, and a reasoning
    # trace is text nothing downstream is allowed to publish.
    resp = client.generate(prompt, think=False)
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
