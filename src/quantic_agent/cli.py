"""The quantic-agent command.

It still has no scheduled tasks. What it can do as of milestone 2 is reach the
local model server: --check reports the server and its models, --ask sends one
prompt and prints the reply.
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


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the command and returns its exit status.

    A usage mistake, --help and --version end the run from inside argparse by
    raising SystemExit (2 for a mistake, 0 for the others).
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
        return 0

    with llm.Client(args.ollama, args.model) as client:
        try:
            if args.check:
                return _check(client, args.ollama)
            return _ask(client, args.ask)
        except llm.LLMError as err:
            print(f"quantic-agent: {err}", file=sys.stderr)
            return 1


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
        print(f"quantic-agent: {client.model} is not on this server", file=sys.stderr)
        return 1
    return 0


def _ask(client: llm.Client, prompt: str) -> int:
    # Thinking is suppressed: the agent wants the answer, and a reasoning
    # trace is text nothing downstream is allowed to publish.
    resp = client.generate(prompt, think=False)
    print(resp.response)
    # The run line goes to stderr so that stdout stays pipeable.
    note = " · truncated: hit the token limit" if resp.truncated else ""
    ms = round(resp.eval_duration.total_seconds() * 1000)
    print(f"{resp.model} · {resp.eval_count} tokens · {ms}ms{note}", file=sys.stderr)
    return 0


def short_count(n: int) -> str:
    """A context length the way model cards write it: 262144 as 256K."""
    if n >= 1024 * 1024:
        return f"{n // (1024 * 1024)}M"
    if n >= 1024:
        return f"{n // 1024}K"
    return str(n)
