"""The quantic-bench command: what the model server can do on this machine.

It exists for design open question 9: on a 16GB card, does a 27B with some
layers spilled into system RAM beat a 9B that fits entirely in VRAM? That is a
measurement, not an argument, and the answer belongs to one machine, so the
benchmark travels with the repository and runs where the agent will.
"""

import argparse
import os
import secrets
import sys
from collections.abc import Sequence
from datetime import timedelta

from pydantic import BaseModel, TypeAdapter

from quantic_agent import llm
from quantic_agent.cli import short_count

# The candidates for design open question 9: the 9B that fits with room to
# spare, and Qwen3.8-27B at two sub-4-bit quantisations that Ollama's own
# library doesn't publish, pulled from Hugging Face.
DEFAULT_MODELS = (
    "qwen3.5:9b,hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S,hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL"
)


class Result(BaseModel):
    """One (model, context length) measurement. The field names are the JSON
    keys, the same as the Go version's, so files in docs/benchmarks compare
    with new runs."""

    model: str
    context_tokens: int
    prompt_tokens: int
    prompt_tokens_per_second: float
    generated_tokens: int
    generated_tokens_per_second: float
    total_seconds: float
    load_seconds: float
    size_bytes: int = 0
    vram_bytes: int = 0
    fraction_on_gpu: float = 0
    generated_tokens_requested: int


_RESULTS = TypeAdapter(list[Result])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quantic-bench",
        description="Measure prompt and generation speed and GPU residency per model.",
    )
    parser.add_argument(
        "--ollama",
        default=os.environ.get("OLLAMA_HOST") or llm.DEFAULT_BASE_URL,
        help="model server URL (default: $OLLAMA_HOST, else %(default)s)",
    )
    parser.add_argument(
        "--models", default=DEFAULT_MODELS, help="comma-separated models to measure"
    )
    parser.add_argument(
        "--contexts",
        type=parse_sizes,
        default="8192,32768,65536",
        help="comma-separated context sizes in tokens (default: %(default)s)",
    )
    parser.add_argument(
        "--predict", type=int, default=128, help="tokens to generate per measurement"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit results as JSON instead of a table"
    )
    args = parser.parse_args(argv)
    sizes: list[int] = args.contexts
    wanted = [m.strip() for m in args.models.split(",") if m.strip()]

    results: list[Result] = []
    try:
        with llm.Client(args.ollama, "") as lister:
            present = {m.name.casefold() for m in lister.models()}
        for name in wanted:
            if name.casefold() not in present:
                print(f"quantic-bench: {name} is not on this server, skipping", file=sys.stderr)
                continue
            with llm.Client(args.ollama, name) as client:
                results.extend(_measure_model(client, sizes, args.predict))
    except llm.LLMError as err:
        print(f"quantic-bench: {err}", file=sys.stderr)
        return 1

    if not results:
        print("quantic-bench: nothing measured", file=sys.stderr)
        return 1
    if args.json:
        print(_RESULTS.dump_json(results, indent=2).decode())
    else:
        _write_table(results)
    return 0


def _measure_model(client: llm.Client, sizes: list[int], predict: int) -> list[Result]:
    # One untimed call first, so the measurements exclude loading the weights
    # and load time is reported once rather than smeared over the first size.
    try:
        warm = client.generate(
            "Reply with the single word: ready.",
            think=False,
            options=llm.Options(num_predict=1, num_ctx=sizes[0]),
        )
    except llm.LLMError as err:
        print(f"quantic-bench: {client.model}: {err}", file=sys.stderr)
        return []

    results: list[Result] = []
    for ctx in sizes:
        try:
            results.append(_measure(client, ctx, predict, warm.load_duration))
        except llm.LLMError as err:
            print(f"quantic-bench: {client.model} at {ctx}: {err}", file=sys.stderr)
    return results


def _measure(client: llm.Client, ctx: int, predict: int, load: timedelta) -> Result:
    """One generation, with the rates the server itself counted. Ollama returns
    token counts and durations per phase, so nothing here is timed with a wall
    clock that would include HTTP."""
    resp = client.generate(
        filler_prompt(ctx * 8 // 10),
        think=False,
        options=llm.Options(num_predict=predict, num_ctx=ctx),
    )
    r = Result(
        model=client.model,
        context_tokens=ctx,
        prompt_tokens=resp.prompt_eval_count,
        prompt_tokens_per_second=_rate(resp.prompt_eval_count, resp.prompt_eval_duration),
        generated_tokens=resp.eval_count,
        generated_tokens_per_second=_rate(resp.eval_count, resp.eval_duration),
        total_seconds=resp.total_duration.total_seconds(),
        load_seconds=load.total_seconds(),
        generated_tokens_requested=predict,
    )
    # Residency is only knowable while the model is still held, so ask right
    # after the generation rather than at the end of the run.
    try:
        running = client.running()
    except llm.LLMError:
        return r  # the measurement stands; residency is a bonus
    for m in running:
        if m.name.casefold() == client.model.casefold():
            r.size_bytes, r.vram_bytes, r.fraction_on_gpu = m.size, m.size_vram, m.on_gpu
            break
    return r


def _write_table(results: list[Result]) -> None:
    rows = [("MODEL", "CTX", "PROMPT tok/s", "GEN tok/s", "RESIDENT", "ON GPU", "LOAD", "TOTAL")]
    notes = [""]
    for r in results:
        rows.append(
            (
                r.model,
                short_count(r.context_tokens),
                f"{r.prompt_tokens_per_second:.0f}",
                f"{r.generated_tokens_per_second:.1f}",
                f"{r.size_bytes / 1e9:.1f} GB",
                _percent(r.fraction_on_gpu),
                f"{r.load_seconds:.1f}s",
                f"{r.total_seconds:.1f}s",
            )
        )
        short = r.generated_tokens < r.generated_tokens_requested
        notes.append(
            f" (stopped after {r.generated_tokens} of {r.generated_tokens_requested}"
            " tokens: small sample)"
            if short
            else ""
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row, note in zip(rows, notes, strict=True):
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip() + note)

    print()
    print("ON GPU below 100% means layers spilled into system RAM: the model is larger than")
    print("the card once its KV cache is counted. To find out whether cache quantisation helps,")
    print("run this again with OLLAMA_KV_CACHE_TYPE=q8_0 set on the *server* and compare the")
    print("largest context row. If nothing moves, flash attention isn't active for that model")
    print("and the setting is being ignored.")


def filler_prompt(tokens: int) -> str:
    """A prompt of roughly `tokens` tokens. It asks for a long answer on
    purpose: generation speed measured over two tokens is noise, so the model
    should run to --predict. The nonce matters too: without it Ollama's prefix
    cache answers the second run for free and reports a prompt-processing rate
    that doesn't exist."""
    head = (
        f"Session {secrets.token_hex(8)}. Read the notes below, then summarise them at length.\n\n"
    )
    line = (
        "Dividend note: the payout was declared, the ex-date is set, "
        "and the yield moved with the price. "
    )
    # About 4 characters per token; the server reports the real count.
    repeats = max(0, -(-(tokens * 4 - len(head)) // len(line)))
    return head + line * repeats


def parse_sizes(text: str) -> list[int]:
    """Context sizes from "8192,32768". argparse reports an ArgumentTypeError's
    message as a usage error naming the option; any other exception, it
    replaces with a generic "invalid value"."""
    sizes: list[int] = []
    for part in text.split(","):
        if not (part := part.strip()):
            continue
        if not part.isdigit() or int(part) == 0:
            raise argparse.ArgumentTypeError(
                f"context size {part!r} is not a positive number of tokens"
            )
        sizes.append(int(part))
    if not sizes:
        raise argparse.ArgumentTypeError("no context sizes given")
    return sizes


def _rate(tokens: int, duration: timedelta) -> float:
    seconds = duration.total_seconds()
    return tokens / seconds if seconds > 0 else 0.0


def _percent(fraction: float) -> str:
    return "0% (CPU)" if fraction <= 0 else f"{fraction * 100:.0f}%"
