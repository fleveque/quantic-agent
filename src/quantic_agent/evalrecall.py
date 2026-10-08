"""The quantic-evalrecall command: how well embedding models find the right
example.

Style memory shows a writer the approved answers most similar to its
question (design §3.4). This measures that choice on a fixed set
(recall_cases.json): real answers from this project's runs, and questions
labelled with the answers that would be fair examples for them, in English and
Spanish, since posts will be written in seven locales. A question scores when
its most similar answer is one of its labels.

Each model runs as published, twice: plain text, and with the prefixes its
documentation asks for. Prefixes are how a model is meant to be used, not a
modified model (models are used as published).
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from importlib.resources import files

from pydantic import BaseModel, TypeAdapter

from quantic_agent import llm, memory
from quantic_agent.cli import cancel_on_sigterm
from quantic_agent.memory import PLAIN, Usage, documented

DEFAULT_MODELS = "nomic-embed-text,qwen3-embedding:0.6b"
DEFAULT_TIMEOUT = 300.0


class Answer(BaseModel):
    id: str
    question: str
    text: str


class Query(BaseModel):
    query: str
    want: list[str]  # the answers that would be fair examples
    language: str = "en"


class Cases(BaseModel):
    answers: list[Answer]
    queries: list[Query]


class Outcome(BaseModel):
    query: str
    language: str
    found: str  # the most similar answer
    score: float
    hit: bool


class Score(BaseModel):
    model: str
    usage: str
    dims: int = 0
    hits: int = 0
    runs: int = 0
    ms_per_text: float = 0.0  # Ollama's own time, per text embedded
    outcomes: list[Outcome] = []


_SCORES = TypeAdapter(list[Score])


def load_cases() -> Cases:
    """The cases, read from the package itself."""
    return Cases.model_validate_json(
        files("quantic_agent").joinpath("recall_cases.json").read_bytes()
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quantic-evalrecall",
        description="Measure how well embedding models find the right example answer.",
    )
    parser.add_argument(
        "--ollama",
        default=os.environ.get("OLLAMA_HOST") or llm.DEFAULT_BASE_URL,
        help="model server URL (default: $OLLAMA_HOST, else %(default)s)",
    )
    parser.add_argument(
        "--models", default=DEFAULT_MODELS, help="comma-separated embedding models to evaluate"
    )
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
        print("quantic-evalrecall: stopped", file=sys.stderr)
        return 130


async def _run(args: argparse.Namespace) -> int:
    cancel_on_sigterm()
    cases = load_cases()
    scores: list[Score] = []
    # The client's own model is never used: embed names the model per call.
    async with llm.Client(args.ollama, "") as client:
        for model in [m.strip() for m in args.models.split(",") if m.strip()]:
            usages = [PLAIN, *filter(None, [documented(model)])]
            try:
                for usage in usages:
                    async with asyncio.timeout(args.timeout or None):
                        scores.append(await evaluate(client, model, usage, cases))
            except llm.LLMError as err:
                print(f"quantic-evalrecall: {model}: {err}", file=sys.stderr)
    if not scores:
        return 1
    if args.json:
        print(_SCORES.dump_json(scores, indent=2).decode())
    else:
        _write_table(scores)
    return 0


async def evaluate(client: llm.Client, model: str, usage: Usage, cases: Cases) -> Score:
    """Embeds every answer and every question with model, used as usage says,
    and scores each question by its most similar answer."""
    answers = await client.embed([usage.document + a.text for a in cases.answers], model=model)
    queries = await client.embed([usage.query + q.query for q in cases.queries], model=model)
    # Memory's run_id is the answer's position in the cases.
    stored = [
        memory.Memory(i, a.text, memory.unit(v))
        for i, (a, v) in enumerate(zip(cases.answers, answers.embeddings, strict=True))
    ]
    score = Score(model=model, usage=usage.name, dims=len(answers.embeddings[0]))
    for q, vector in zip(cases.queries, queries.embeddings, strict=True):
        [best] = memory.nearest(vector, stored, k=1)
        found = cases.answers[best.memory.run_id].id
        hit = found in q.want
        score.outcomes.append(
            Outcome(query=q.query, language=q.language, found=found, score=best.score, hit=hit)
        )
        score.hits += hit
        score.runs += 1
    texts = len(cases.answers) + len(cases.queries)
    elapsed = answers.total_duration + queries.total_duration - answers.load_duration
    score.ms_per_text = elapsed.total_seconds() * 1000 / texts
    return score


def _write_table(scores: list[Score]) -> None:
    rows = [["MODEL", "USAGE", "DIMS", "EN", "ES", "TOTAL", "MS/TEXT"]]
    for s in scores:
        by_language = {lang: [o for o in s.outcomes if o.language == lang] for lang in ("en", "es")}
        cells = [f"{sum(o.hit for o in os)}/{len(os)}" for os in by_language.values()]
        rows.append(
            [s.model, s.usage, str(s.dims), *cells, f"{s.hits}/{s.runs}", f"{s.ms_per_text:.1f}"]
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())
    for s in scores:
        for o in s.outcomes:
            if not o.hit:
                print(f"{s.model} ({s.usage}) missed: {o.query!r} found {o.found}", file=sys.stderr)
