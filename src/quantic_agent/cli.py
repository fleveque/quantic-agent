"""The quantic-agent command.

It still has no scheduled tasks. What it can do so far: --check reports the
model server and its models, --ask sends one prompt and prints the reply, and
--research answers a question in two phases: research, where the model calls
Quantic's tools (each call traced to stderr as it completes), then writing,
where it answers from what they returned and nothing else. Given several
times, it answers the questions at once: their model calls take turns at the
GPU, and their tool calls share one pace under Quantic's rate limit. Every research run
is stored with its tool calls in a SQLite database: --runs lists them, --run N
shows one and re-checks its answer against the data it was given, and
--resume N carries on with a run that stopped, from the phase it had reached.
--approve N and --reject N record a reviewer's verdict on a run's answer.
Approved answers are style memory: a writer is shown the most similar ones as
examples of the house voice, and --recall shows which those would be.

Exit status: 0 success, 1 failure (including --timeout running out), 2 wrong
usage, 3 the model server or the MCP server wasn't there to answer (or
Quantic's rate limit didn't clear), 4 a --research answer contains figures no
tool returned (design N1), 5 research gathered no data, so nothing was
written, 130 stopped by Ctrl-C or SIGTERM. For several questions, the status
is the first one that isn't 0, in the order the questions were given. After 3, 5 or 130, --resume
continues the run (design §3.6). On 130 the request in flight was cancelled,
and Ollama stops working on it too.
"""

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import TextIO

from quantic_agent import agent, llm, memory, provenance, quantic, store
from quantic_agent.tools import DIVIDEND_CALENDAR, GET_STOCK

# The safe choice for the target hardware (design §4): it fits any 16GB card
# with room to spare. Development happens on a different machine, so both
# options below read an environment variable first and nothing is baked in.
DEFAULT_MODEL = "qwen3.5:9b"

# Exit statuses, as documented at the top of this file. 2 is argparse's.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_UNAVAILABLE = 3
EXIT_UNVERIFIED = 4
EXIT_NO_DATA = 5
EXIT_INTERRUPTED = 130  # 128 + SIGINT, the shell's convention for Ctrl-C

# Bounds one run, in seconds. The slowest request measured on the target
# machine took 94s (a 27B partly in system RAM, 64K context) and the slowest
# cold load 31s, so five minutes leaves more than double. It must never be
# short enough to cut off a load: cancelling a load aborts it, and the next
# attempt starts from zero.
DEFAULT_TIMEOUT = 300.0

# The context window research and writing ask Ollama for. Its own default,
# 4096 tokens, is silently exceeded by a handful of get_stock results, and
# Ollama then drops the start of the conversation. 32K kept the default model
# wholly on a 16GB GPU (docs/benchmarks); see lesson 09 for the measurement.
DEFAULT_NUM_CTX = 32768

# The model that turns text into vectors for style memory, chosen by
# measurement (lesson 10), and how many approved answers a writer is shown.
DEFAULT_EMBED_MODEL = "qwen3-embedding:0.6b"
EXAMPLES = 2


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
        "--research",
        metavar="QUESTION",
        action="append",
        help="answer a question using Quantic's tools; give it several times to answer several "
        "questions at once",
    )
    action.add_argument(
        "--resume",
        type=int,
        metavar="N",
        help="carry on with run N, stopped or failed before answering, with its own model",
    )
    action.add_argument(
        "--approve", type=int, metavar="N", help="approve run N's answer: it becomes style memory"
    )
    action.add_argument(
        "--reject", type=int, metavar="N", help="reject run N's answer; it stops being style memory"
    )
    action.add_argument(
        "--recall",
        metavar="QUESTION",
        help="show the approved answers a writer would be shown for QUESTION",
    )
    action.add_argument("--runs", action="store_true", help="list recent research runs")
    action.add_argument(
        "--run",
        type=int,
        metavar="N",
        help="show one run, and re-check its answer against the tool results it was given",
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
        "--db",
        type=Path,
        default=os.environ.get("QUANTIC_AGENT_DB") or default_db_path(),
        help="the database of runs and tool calls (default: $QUANTIC_AGENT_DB, else %(default)s)",
    )
    parser.add_argument("--note", default="", help="a reviewer's note, with --approve or --reject")
    parser.add_argument(
        "--embed-model",
        default=os.environ.get("QUANTIC_EMBED_MODEL") or DEFAULT_EMBED_MODEL,
        help="the model that embeds text for style memory "
        "(default: $QUANTIC_EMBED_MODEL, else %(default)s)",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=int(os.environ.get("QUANTIC_NUM_CTX") or DEFAULT_NUM_CTX),
        metavar="TOKENS",
        help="the model's context window for research and writing "
        "(default: $QUANTIC_NUM_CTX, else %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="give up on a run after this long; 0 for no limit (default: %(default)g)",
    )
    args = parser.parse_args(argv)

    # Reading the history needs neither the model nor Quantic.
    if args.runs:
        with store.Store(args.db) as db:
            return _show_runs(db)
    if args.run is not None:
        with store.Store(args.db) as db:
            return _show_run(db, args.run)
    if args.reject is not None:
        with store.Store(args.db) as db:
            try:
                db.reject(args.reject, args.note)
            except store.NotReviewableError as err:
                _error(str(err))
                return EXIT_FAILED
        _error(f"run {args.reject} rejected")
        return EXIT_OK
    wanted = (args.check, args.ask, args.research, args.resume, args.approve, args.recall)
    if not any(w not in (None, False) for w in wanted):
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
    if args.resume is not None:
        with store.Store(args.db) as db:
            try:
                run = db.resume(args.resume)
            except store.NotResumableError as err:
                _error(str(err))
                return EXIT_FAILED
            _error(
                f"resuming run {run.id} in its {run.phase} phase, "
                f"with {len(run.calls)} tool call(s) recorded"
            )
            # A resumed run goes on with the model it started with, which is
            # the one its record names.
            async with llm.Client(args.ollama, run.model) as client:
                return await _research(client, db, args, _pace(), run=run)
    if args.research is not None:
        with store.Store(args.db) as db:
            async with llm.Client(args.ollama, args.model) as client:
                return await _research_all(client, db, args)
    if args.approve is not None or args.recall is not None:
        with store.Store(args.db) as db:
            async with llm.Client(args.ollama, args.model) as client:
                try:
                    async with asyncio.timeout(args.timeout or None):
                        if args.approve is not None:
                            return await _approve(client, db, args)
                        return await _show_recall(client, db, args)
                except TimeoutError:
                    return _gave_up(args.timeout)
                except llm.LLMError as err:
                    return _fail(err, args)
    async with llm.Client(args.ollama, args.model) as client:
        try:
            # One deadline for the whole run, whatever it does inside; None
            # means no limit.
            async with asyncio.timeout(args.timeout or None):
                if args.check:
                    return await _check(client, args.ollama)
                return await _ask(client, args.ask)
        except TimeoutError:
            return _gave_up(args.timeout)
        except llm.LLMError as err:
            return _fail(err, args)


def _gave_up(timeout: float) -> int:
    _error(
        f"gave up after {timeout:g}s (--timeout). A cold model can take "
        "half a minute to load, and a long generation longer."
    )
    return EXIT_FAILED


def default_db_path() -> Path:
    """Where the run history lives by default. It follows the XDG base
    directory convention: history is "state", data that persists between runs
    but isn't configuration."""
    state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state) / "quantic-agent" / "agent.db"


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
        case quantic.RateLimitedError():
            _error("Quantic's rate limit didn't clear; resume the run later.")
            _error(str(err))
            return EXIT_UNAVAILABLE
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


async def _approve(client: llm.Client, db: store.Store, args: argparse.Namespace) -> int:
    """Approves a run's answer: embeds it, then records the verdict and the
    vector together."""
    try:
        run = db.run(args.approve)
    except store.NotFoundError:
        _error(f"there is no run {args.approve}")
        return EXIT_FAILED
    if run.draft is None:
        _error(f"run {run.id} has no answer to review")
        return EXIT_FAILED
    usage = memory.documented(args.embed_model) or memory.PLAIN
    embedded = await client.embed([usage.document + run.draft.content], model=args.embed_model)
    try:
        db.approve(run.id, args.note, args.embed_model, embedded.embeddings[0], run.draft.content)
    except store.NotReviewableError as err:
        _error(str(err))
        return EXIT_FAILED
    _error(f"run {run.id} approved: style memory now")
    return EXIT_OK


async def _recall(
    client: llm.Client, db: store.Store, question: str, model: str, exclude: int = 0
) -> list[memory.Match]:
    """The approved answers most similar to question. With none approved, it
    asks nothing of the GPU. The question is embedded as the model's
    documentation asks for a query, and as it was measured."""
    memories = [m for m in db.memories(model) if m.run_id != exclude]
    if not memories:
        return []
    usage = memory.documented(model) or memory.PLAIN
    embedded = await client.embed([usage.query + question], model=model)
    return memory.nearest(embedded.embeddings[0], memories, EXAMPLES)


async def _show_recall(client: llm.Client, db: store.Store, args: argparse.Namespace) -> int:
    matches = await _recall(client, db, args.recall, args.embed_model)
    if not matches:
        print(f"no approved answers embedded with {args.embed_model}")
    for m in matches:
        print(f"run {m.memory.run_id} · {m.score:.3f}\n{m.memory.text}\n")
    return EXIT_OK


def _pace() -> quantic.Pace:
    """The pace every MCP session in this process shares."""

    def on_wait(seconds: float) -> None:
        _error(f"pacing: waiting {seconds:.1f}s to stay under Quantic's rate limit")

    return quantic.Pace(on_wait=on_wait)


async def _research_all(client: llm.Client, db: store.Store, args: argparse.Namespace) -> int:
    """Answers every --research question at once, each its own run. They
    share the model client, whose semaphore makes their model calls take
    turns at the GPU, and one pace for Quantic. The status is the first that
    isn't 0, in question order: a scheduler reads one number."""
    pace = _pace()
    questions: list[str] = args.research
    if len(questions) == 1:
        return await _research(client, db, args, pace, question=questions[0])
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(_research(client, db, args, pace, question=q, batch=True))
            for q in questions
        ]
    return next((code for t in tasks if (code := t.result()) != EXIT_OK), EXIT_OK)


async def _research(
    client: llm.Client,
    db: store.Store,
    args: argparse.Namespace,
    pace: quantic.Pace,
    *,
    question: str = "",
    run: store.Run | None = None,
    batch: bool = False,
) -> int:
    """Answers one question in two phases, research then write (design §3.1),
    recording the run as it goes: the run when it starts, each tool call as it
    completes, a checkpoint when research is done, and the outcome and draft
    when it ends. A resumed run, passed as run, starts at the phase it had
    reached: one stopped while writing doesn't call a single tool again.

    A new run is recorded here, in the task that answers it, before its first
    await. A task cancelled before it starts never runs a line, so it leaves
    no run behind; one recorded before the task started would stay "running"
    for ever. In a batch, each line on stderr names its run."""
    if run is None:
        run = db.run(db.start_run("research", question, client.model))
    label = f"run {run.id}: " if batch else ""
    options = llm.Options(num_ctx=args.num_ctx)

    def say(message: str) -> None:
        _error(label + message)

    # The record's calls, continued in place by the research phase.
    gathered = agent.Research(calls=run.calls, tokens=run.tokens, exhausted=run.exhausted)
    written = 0  # tokens the writer used, if it got that far

    def finish(
        state: store.State, error: str | None = None, draft: store.Draft | None = None
    ) -> None:
        db.finish(run.id, state, error, draft, tokens=gathered.tokens + written)
        _error(f"run {run.id} {state}")
        if draft is None:
            say(f"to carry on from where it stopped: quantic-agent --resume {run.id}")

    # "Today" is the day the run started, when its data was fetched, even for
    # a run resumed later: the answer describes that data.
    today = run.started_at.astimezone().date()
    try:
        # The deadline covers the handshake, every model turn, every tool
        # call and the writing. It sits inside this try, so running out of
        # time arrives as TimeoutError and a signal as CancelledError: two
        # different outcomes.
        async with asyncio.timeout(args.timeout or None):
            if run.phase is store.Phase.RESEARCH:
                await _research_phase(client, db, run, gathered, args, pace, options, label)
                if not gathered.has_data:
                    # Nothing to write from. Writing anyway produced "no data
                    # was retrieved" answers that counted as answered. The run
                    # stays in research, so resuming tries again.
                    say("research gathered no data (no tool call succeeded); nothing to write")
                    finish(store.State.NO_DATA, "research gathered no data")
                    return EXIT_NO_DATA
                if gathered.exhausted is not None:
                    say(
                        f"research stopped when its {gathered.exhausted} budget ran out; "
                        "writing from what it gathered"
                    )
                db.checkpoint(run.id, store.Phase.WRITE, gathered.tokens, gathered.exhausted)
            # Style memory: approved answers like this question, as examples.
            # Recorded before the writer sees them (N3).
            matches = await _recall(client, db, run.input, args.embed_model, exclude=run.id)
            if matches:
                db.record_examples(run.id, matches)
            examples = [m.memory.text for m in matches]
            writer = agent.Writer(client, today=today, options=options, examples=examples)
            draft = await writer.write(run.input, gathered)
            written = draft.tokens
    except asyncio.CancelledError:
        # Recorded, then passed on. finish() is synchronous, so it runs to the
        # end even in a cancelled task: cancellation only lands at an await.
        finish(store.State.INTERRUPTED)
        raise
    except TimeoutError:
        finish(store.State.FAILED, f"gave up after {args.timeout:g}s")
        return _gave_up(args.timeout)
    except agent.NothingWrittenError as err:
        written = err.tokens
        finish(store.State.FAILED, str(err))
        say(str(err))
        return EXIT_FAILED
    except (llm.LLMError, quantic.ToolServerError) as err:
        finish(store.State.FAILED, str(err))
        return _fail(err, args)

    if batch:
        print(f"=== run {run.id}: {run.input}")
    print(draft.text)
    if draft.truncated:
        say("the answer was truncated: the model hit its token limit")
    try:
        findings = _check_figures(run, draft.text, gathered.calls)
    except provenance.ProvenanceError as err:
        finish(store.State.FAILED, str(err))
        say(str(err))
        return EXIT_FAILED
    saved = store.Draft(content=draft.text, truncated=draft.truncated, findings=findings)
    if findings:
        _report_findings(findings, sys.stderr, label)
        finish(store.State.UNVERIFIED, draft=saved)
        return EXIT_UNVERIFIED
    finish(store.State.ANSWERED, draft=saved)
    return EXIT_OK


async def _research_phase(
    client: llm.Client,
    db: store.Store,
    run: store.Run,
    gathered: agent.Research,
    args: argparse.Namespace,
    pace: quantic.Pace,
    options: llm.Options,
    label: str,
) -> None:
    """Lets the model call Quantic's tools, recording each call as it
    completes, and carrying on from what gathered already holds."""

    def on_call(seq: int, call: agent.Call) -> None:
        _trace(call, label)
        db.record_call(run.id, seq, call)

    def on_retry(method: str, retry: int, wait: float) -> None:
        _error(f"{label}Quantic's rate limit; retry {retry} of {method} in {wait:.1f}s")

    async with quantic.Server(args.mcp, on_retry=on_retry, pace=pace) as server:
        researcher = agent.Researcher(
            model=client, server=server, tools=[DIVIDEND_CALENDAR, GET_STOCK], options=options
        )
        await researcher.research(run.input, gathered, on_call=on_call)


def _check_figures(
    run: store.Run, text: str, calls: Sequence[agent.Call]
) -> list[provenance.Finding]:
    """Every figure in text that the successful calls' results don't account
    for (design N1). Failed calls aren't data: an error message is not a
    source. The run's question and the date it started count as sources:
    repeating the question's "six months", or the date the writer was told is
    today, invents nothing."""
    records = [provenance.Record(c.tool, c.result) for c in calls if not c.failed]
    manifest = provenance.Manifest(records)
    manifest.add_text("question", run.input)
    manifest.add_text("today", run.started_at.astimezone().date().isoformat())
    return provenance.check_prose(text, manifest)


def _report_findings(findings: Sequence[provenance.Finding], out: TextIO, label: str = "") -> None:
    print(
        f"quantic-agent: {label}{len(findings)} figure(s) in the answer came from no tool result:",
        file=out,
    )
    for finding in findings:
        print(f"  {finding}", file=out)


def _show_runs(db: store.Store) -> int:
    """The most recent runs, newest first."""
    rows = [("RUN", "STARTED", "STATE", "PHASE", "CALLS", "TOKENS", "QUESTION")]
    for run in db.runs(20):
        started = run.started_at.astimezone().strftime("%Y-%m-%d %H:%M")
        rows.append(
            (
                str(run.id),
                started,
                run.state,
                run.phase,
                str(run.call_count),
                str(run.tokens),
                _shorten(run.input, 60),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())
    return EXIT_OK


def _show_run(db: store.Store, run_id: int) -> int:
    """One run, and its answer re-checked against the tool results it was
    given, as stored: the audit log answering "where did this come from?"
    after the fact (design N3)."""
    try:
        run = db.run(run_id)
    except store.NotFoundError:
        _error(f"there is no run {run_id}")
        return EXIT_FAILED
    started = run.started_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"run {run.id} · {run.state} · {run.model} · {started}")
    print(f"question: {run.input}")
    print(f"phase: {run.phase} · {run.tokens} tokens")
    if run.review is not None:
        note = f": {run.review.note}" if run.review.note else ""
        print(f"review: {run.review.verdict}{note}")
    if run.examples:
        shown = ", ".join(f"run {r} ({score:.3f})" for r, score in run.examples)
        print(f"examples shown to its writer: {shown}")
    if run.exhausted is not None:
        print(f"research stopped early: its {run.exhausted} budget ran out")
    if run.error:
        print(f"error: {run.error}")
    for i, call in enumerate(run.calls):
        outcome = call.result if call.failed else f"{len(call.result)} bytes"
        print(f"call {i}: {call.tool} {json.dumps(call.arguments)} → {outcome}")
    if run.draft is None:
        return EXIT_OK
    print(f"\n{run.draft.content}\n")
    findings = _check_figures(run, run.draft.content, run.calls)
    if not findings:
        print("provenance, re-checked now: every figure traces to a stored tool result")
        return EXIT_OK
    _report_findings(findings, sys.stdout)
    return EXIT_UNVERIFIED


def _shorten(text: str, n: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def _trace(call: agent.Call, label: str = "") -> None:
    """One line per tool call on stderr: what was asked, and what came back."""
    outcome = call.result if call.failed else f"{len(call.result)} bytes"
    ms = round(call.duration.total_seconds() * 1000)
    line = f"{label}tool {call.tool} {json.dumps(call.arguments)} → {outcome} ({ms}ms)"
    print(line, file=sys.stderr)


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
