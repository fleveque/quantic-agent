# quantic-agent — design

Living document. Records decisions, the reasoning behind them, and the questions still open.
Originates from a Spanish-language idea sketch; this is the refined English version the
implementation follows.

The agent was built in Go first, up to milestone 8 ([quantic-agent-go](https://github.com/fleveque/quantic-agent-go)),
and continues here in Python ([decision 0007](decisions/0007-continue-in-python.md)). The design
carries over whole. **"As built in Go"** notes record what the Go version built and measured, linked
to its code; what they found holds for any language. Each becomes an "As built" note about this
repository's code as its milestone is ported.

Companion documents: [content plan](content.md) · [format & rendering](rendering.md) · [decisions](decisions/)

---

## 1. Problem

Quantic (quantic.finance) is a dividend-portfolio tracker: Elixir/Phoenix monolith, real users, real
money decisions. Recurring jobs that are repetitive, LLM-shaped, and intolerant of hallucination:

1. **Content.** Recurring, data-grounded publishing — a weekly dividend digest, raise/cut notes,
   valuation write-ups — across seven locales. See the [content plan](content.md).
2. **Data quality.** Watching a large instrument universe for nulls, outliers, impossible dates and
   suspicious dividend histories.

The agent is meant to keep running and take on more jobs of this kind, not only to write articles. One
is about the agent itself:

3. **Model upkeep.** Open models improve every few months, and a newer model is often better than an
   older, bigger one. Watch for new candidates, measure them on this machine and on this agent's own
   tasks, and propose a change of default — as a PR carrying the numbers, never by switching itself
   (N2). See [decision 0005](decisions/0005-default-model-by-measurement.md) for the evaluation routine,
   and [open question 10](#5-open-questions).

Frontier-model APIs would work but cost per token and send portfolio-adjacent data to a third party.
A local model on owned hardware removes both constraints, at the cost of lower model quality — which
is precisely why the architecture must not depend on the model being smart about facts.

## 2. Non-negotiables

**N1 — No invented numbers.** Every figure in output traces to a recorded tool call. Enforced by a
validator, not by prompt instructions.

**N2 — No autonomous publication.** No merge to `main`, no post to any channel. Output is a PR or a
`pending_review` row.

**N3 — Full auditability.** Every tool call logged with inputs and outputs. Any output can be
reconstructed after the fact: what did the agent see, and when.

**N4 — No user data leaves the machine, or lands in this repo.** No portfolio contents in prompts,
logs, fixtures, or commits.

**N5 — Informational, never advisory.** Content describes what happened and what the data says. It
does not recommend buying or selling. Quantic operates in the EU; "this stock is a buy" is a
regulatory problem, not a style preference.

## 3. Architecture

### 3.1 The core split: agentic research, constrained writing

The pipeline has two LLM phases with deliberately different freedom:

```
        ┌─────────── RESEARCH (agentic) ───────────┐   ┌── WRITE ──┐
trigger →  plan → [ model ⇄ read-only tools ] ×N   → manifest → prose → validate → deliver
        └── bounded: calls · wall-clock · tokens ──┘   └ no tools ─┘
```

**Research is a real agentic loop.** The model chooses which tools to call and can follow a thread —
*"this yield jumped 40%, so check the payout ratio, then the last five dividends, then whether the
price collapsed"* — accumulating a manifest as it goes. Every call is read-only, so the blast radius
is zero and the loop can be given genuine freedom.

**Writing has no tools at all.** A separate model call receives *only* the accumulated manifest and
writes prose. Because it cannot fetch, it cannot wander mid-sentence into invention. It also cannot
"remember" a figure it never saw.

**Delivery tools (`create_pr`, `enqueue_for_review`) live outside the loop.** They are reachable only
at the terminal step and are never in the research allowlist, so no amount of wandering can cause the
agent to publish something.

An earlier draft of this design made the whole pipeline fixed — the task declared its data
dependencies up front and the model only wrote prose. That was over-cautious: the provenance manifest
records tool calls regardless of *who* decided to make them, so the N1 guarantee survives an agentic
loop intact. What a fixed pipeline actually buys is predictable cost, and that's what budgets are
for. See [decision 0001](decisions/0001-agentic-research-constrained-writing.md).

**As built (milestone 5, [`agent.py`](../src/quantic_agent/agent.py)).** The seed of the loop: the
model is offered the allowlist (`dividend_calendar` only), its arguments are validated against each
tool's Pydantic model, a mistake or a tool's refusal goes back to the model as the tool's result,
calls are capped at four, and each call is recorded as it completes. Quantic is reached through the
official MCP SDK ([decision 0009](decisions/0009-official-mcp-sdk.md)). No separate writer yet;
milestone 8 adds it.

**As built in Go (milestone 8, [`internal/agent`](https://github.com/fleveque/quantic-agent-go/tree/main/internal/agent)).** `Researcher.Research` is the loop;
when the model stops asking for tools, whatever it says is discarded. `Writer.Write` is one model
call with no tools, given the question and each successful call's result, labelled with the call
that produced it. Measured against milestone 7's single loop on the same questions and data, the
split traced as many answers (6 of 9 each) and failed differently
([benchmarks](benchmarks/2026-10-07-writer/README.md)): the writer doesn't know today's date, and it
miscounts in words ("ten" stocks where there are nine), which the validator doesn't read. A variant
that showed the writer the research conversation gave buy-timing advice twice; the data-only writer
didn't.

**As built (milestone 8, [`agent.py`](../src/quantic_agent/agent.py)).** The same two phases, with the
same prompts. `Researcher.research` continues an `agent.Research` in place (calls, tokens, the
budget that stopped it), so when the loop raises, the caller still holds what was done and what it
cost; Go returned the value alongside the error. `Writer.write` is one `chat` with no tools, told the
date the run started. Measured on the same three questions, three runs each, against live data a day
later ([benchmarks](benchmarks/2026-10-08-python-writer/README.md)): 4 of 9 traced. The failures were
wrong or unverifiable counts in words, a derived date six months out, and one answer that reasoned
out loud and concluded wrongly. One answer that traced fully was still wrong ("no companies" in ten
days, with Microsoft going ex-dividend that day): the check verifies figures, not claims.

### 3.2 Loop bounds

The research loop is bounded, not open-ended. Per task kind, from config:

| Bound | Default | Behaviour on breach |
|---|---|---|
| Max tool calls | 10 | Loop stops, writing proceeds with what was gathered |
| Wall clock | 5 min | `context` deadline cancels mid-call |
| Token budget | task-specific | Loop stops, run marked `budget_exhausted` |
| Tool allowlist | read-only data tools | Unknown tool name → error returned to model, counted as a call |
| Repeated identical call | 2 | Short-circuited from cache, doesn't count against budget |

A breach is not a failure — it's a normal exit. The manifest is whatever was gathered, and the
validator judges the result on its own merits.

**As built in Go (milestone 8).** Calls (default 4) and tokens (default 16,000) are `agent.Budget`; wall
clock is `-timeout`, the run's context deadline. Tokens are Ollama's `prompt_eval_count` plus
`eval_count` for every model call: the whole history is processed again each turn, so this is the
work the GPU does, not the size of the conversation. A question about one calendar used 1,800–3,500
tokens across both phases. A reply that takes research to its token budget has its tool requests
dropped, not run. The writer is told when research stopped early. The run records which budget ran
out (`runs.exhausted`). Not built yet: the cache for repeated identical calls, and per-task budgets
from config.

**As built (milestone 8).** The same bounds and defaults: `agent.Budget(calls=4, tokens=16_000)`, a
frozen dataclass whose defaults are the defaults (Go needed `cmp.Or` to read 0 as "the default"), and
`--timeout` for wall clock. Recorded calls of a resumed run count against the call budget, and its
recorded tokens against the token budget. Real runs used 1,780–3,301 tokens across both phases.

**As built (milestone 9).** With `get_stock`, a question about the companies in a 14-day calendar
made ten calls (the calendar, then nine companies in one reply) and used about 10,000 tokens of
research. The defaults became 16 calls (the calendar and fifteen companies) and 64,000 tokens. Calls
a reply asks for beyond the budget are dropped, and research ends there.

### 3.3 Provenance

The hard part, and the most interesting piece of engineering here.

Each run accumulates a **manifest**: an ordered list of `{tool, args, response, timestamp}` records.
After generation, the validator:

1. Extracts every numeric token from the draft (currency amounts, percentages, ratios, dates, counts).
2. Normalises them (thousands separators, currency symbols, decimal commas vs points, `1.2M` forms).
3. Checks each against the set of values present in the manifest's responses.
4. Rejects the draft if any token is unaccounted for.

**Hard case — derived figures.** "Yield rose from 3.1% to 3.4%, a 0.3pp increase" — the `0.3` is
correct but appears in no tool response. Resolution: **ban arithmetic in the writing prompt and
supply deterministic calculator tools** (`pct_change`, `diff`, `sum`) that the research loop calls, so
derived numbers enter the manifest legitimately. The tools are trivial to write, trivial to test, and
keep the invariant total. Fallback if this proves too strict in practice: downgrade unaccounted
numbers to `needs_close_review` rather than rejecting.

The calculators return **full double precision and never round**. 1.50 → 1.55 is
`3.333333333333336`, and that is the value the manifest records and the data block carries. Rounding
is presentation, so the template does it — which means the figure the validator compares is exactly
the figure the tool returned, with no rounding rule duplicated between the agent and Elixir. A
calculator also refuses inputs it can't answer honestly: `pct_change` from a zero or negative base
raises an error rather than returning `Inf` or a percentage whose sign reads backwards.

**As built (milestone 1, [`quantic_agent/tools.py`](../src/quantic_agent/tools.py)).** `pct_change`,
`diff` and `total` (named so it doesn't hide Python's `sum`). A zero base would raise
`ZeroDivisionError` anyway, where Go returned `+Inf`; the explicit check still runs first, so both
refusals are the same `ValueError`. `total` uses the built-in `sum`, which since Python 3.12
compensates for rounding as it adds: ten 0.1s total 1.0, where Go's loop gave 0.9999999999999999.
So the two versions can differ in the last digit for the same inputs, and the manifest records
whichever the running version returned.

**Hard case — false positives.** Years, list positions, "top 10", version numbers. Needs a small
ignore-list and a notion of "numbers that are not claims". Table-driven tests (`pytest.mark.parametrize`) will earn their keep.

**Solved by the format contract.** Numbers live in typed frontmatter fields, not in prose (see
[rendering](rendering.md)), so validation is field-by-field comparison against the manifest rather
than regex extraction — and the prose is validated by the simpler assertion that it contains *no*
unaccounted numerics at all. This also removes the locale number-format problem entirely: figures
never appear in translated text.

**As built (milestone 6, [`provenance.py`](../src/quantic_agent/provenance.py)).** The manifest indexes
every number, date and string in a run's successful tool results, with the path each came from.
`check_data` holds a post's data block to it field by field, strings included, so an invented ticker
fails like a rounded yield. `check_prose` covers free text such as `--research` answers: it finds
numbers (currency, percent, thousands separators), dates (ISO, "Oct 8", "8 October 2026") and bare
years, and reports any the manifest lacks. Matching is exact: a rounded, converted or derived figure is
reported. The false positives above are handled by rule: digits inside words (`Q3`, `W38`) and list
positions at a line start aren't claims, and a bare year counts if a returned date falls in it. Known
limits, acceptable because post prose must have no figures at all (`no_figures`): only English
number formats are parsed. Booleans are never indexed as numbers, since Python's `True == 1` and
`False == 0` would let a tool's `"done": true` vouch for a "1". In six real research runs, four traced
fully; the other two said "October 16 and 17", where the bare "17" isn't read as a date, and "to
December 6, 2026", an end date the model computed from the window itself.

*In Go's own real runs at milestone 6, five of six research answers traced fully; the sixth said "the
next 4 months", a figure the model derived itself, which is exactly what N1 forbids.*

**As built (milestone 8).** Go's fixes after its milestone 8, ported: numbers written as words, two to
ninety-nine, are figures ("nine stocks", "six-month"; "one" is left out, usually a pronoun);
"October 16 and 17" is two dates; each list's length counts as returned, so "nine stocks" checks
against a nine-item calendar; and `Manifest.add_text` adds the figures of the question and of the
date the run started, which the writer is told
([measurement, in Go](benchmarks/2026-10-07-writer/README.md)). Two additions of this version's own,
both from real runs. A weekday written with a date must be the weekday that date falls on: milestone
7's audit log passed "Tuesday, October 9" for a Friday. A weekday alone ("on Friday") isn't checked;
nothing says which Friday. And a range of days, "Oct 8-10" or "Oct 16–17", is two dates, where the
end was read as the number -10.

**As built (milestone 9).** `get_stock` returns some figures as keys (`dividend_by_year`:
`{"2014": 1.12, ...}`) and year-months (`"from": "2020-10"`). Keys that are numbers or dates, and
year-months, now count as returned; a real answer's "$1.12 in 2014" was flagged until they did. Its
growth rates are ratios (`cagr_5y`: 0.1023...), so "10.23%" is a converted figure and is reported,
as N1 requires.

### 3.4 Retrieval (RAG)

Retrieval does not make the model *learn* — the weights never change; it puts relevant text in the
context window at call time. Framed honestly, it earns its place in three specific spots:

1. **Style memory.** Retrieve past **approved** drafts so new output matches the house voice. The
   review queue *is* the corpus, so every human approval improves the next draft. This is the closest
   honest version of "the agent gets better at what it does", and it's a real feedback loop.
2. **Don't-repeat-yourself.** Retrieve what was recently written about a ticker so week 4's digest
   doesn't rehash week 1's angle.
3. **Filings and news text.** Chunked 10-K and press-release text makes valuation write-ups richer.
   Where that text comes from is [open question 11](#5-open-questions): trusted sources only, never
   open browsing.

**The hard line: never retrieve a number.** Retrieved text is quotable as *language*; every figure
still comes from a live tool call. Vector stores have no freshness guarantee, and this is precisely
the crack hallucination would get back in through. Retrieved chunks enter the prompt but **not** the
provenance manifest — they can't authorise a number.

**Implementation: no vector database.** Embeddings stored as BLOBs in SQLite, brute-force cosine
similarity in the agent's own process. At this corpus size — hundreds to low thousands of chunks —
that's microseconds and no service to run. It is the correct engineering choice at this scale, not a
shortcut; revisit only if the corpus grows two orders of magnitude. Embeddings from Ollama
(`nomic-embed-text` or a Qwen3 embedding model) alongside the chat model.

**As built (milestone 10, [`memory.py`](../src/quantic_agent/memory.py),
[decision 0012](decisions/0012-style-memory.md)).** Style memory only. `--approve N` embeds an
answer whose every figure traced; `--reject N` deletes its vector. A writer is shown the two approved
answers most similar to its question, told their facts and figures are out of date, and the run
records which (`--run N` shows them). Examples never enter the manifest: a test copies an example's
figure into a new answer and sees it reported. `qwen3-embedding:0.6b` with its documented query
instruction, by measurement (`quantic-evalrecall`: 10 of 12 against `nomic-embed-text`'s 8). Search
is plain Python over unit vectors, one `math.sumprod` each: about 10ms for 500, 0.4s for 20,000
([benchmarks](benchmarks/2026-10-08-retrieval/README.md)). In a real run the writer took an
approved answer's sentence shapes almost word for word: the review queue decides the voice.
Don't-repeat-yourself and filing text aren't built.

### 3.5 Translation

All seven Quantic locales are in scope from the first content milestone. The review burden is the
thing to design around: **the human reviews the source; translations are machine-verified, not
human-reviewed — with one exception.**

**English is the source.** It's Quantic's reference language and the canonical host, so the `en` draft
is what the validator gates and what the human reads first.

**Spanish is spot-checked.** `es` is the locale the reviewer can actually judge for correctness, so it
surfaces in the review queue alongside the source rather than publishing on machine verification
alone. It's a fluency check on the translation pass, not a re-review of the facts — those are already
guaranteed identical by the byte-identical `data` block.

The remaining five (`ca`, `fr`, `de`, `it`, `pt`) publish on machine verification. A sustained
pattern of problems found in the `es` spot-check is evidence the translation prompt is wrong for all
of them, so the queue records spot-check outcomes as a signal, not just a gate.

```
en draft → provenance ✓ → human review ✓ → canonical (reference)
                                │
                                ├→ es → translation validator ✓ → human spot-check → publish
                                │                                                      ↘ hold
                                └→ ca fr de it pt → translation validator ✓ ──────────→ publish
                                                                            ↘ hold
```

Only prose is translated. The `data` block — every figure in the post — is identical across all
seven locale files, and Phoenix formats numbers at render time using the app's existing localisation
(see [rendering](rendering.md)). The translation validator therefore asserts, per locale:

- **`data` block byte-identical to the source.** No figure can drift in translation because no figure
  is translated.
- **No numerics introduced into prose.** Same rule as the source draft.
- **Same structure** — prose section count and keys, link count and targets.
- **No added claims** — length within a tolerance band of the source.

This is a stronger guarantee than the locale-aware numeric normalisation it replaces, and much less
code.

Any mismatch holds that locale only; the source and the passing locales still publish. A held locale
surfaces in the review queue with the specific assertion that failed.

Note this is a *different mechanism* from Quantic's gettext workflow. Content is per-locale markdown
files, not msgids — the existing "never edit msgids, fill msgstr" rules don't apply here. The register
conventions do: informal throughout, Brazilian Portuguese for `pt`.

Quantic resolves locale from the **request host**, not a path prefix, so a post's seven files are
keyed by locale and served on the host that carries that language — see
[rendering](rendering.md#locales-are-hosts-not-paths).

**As built (milestone 11, [`weekahead.py`](../src/quantic_agent/weekahead.py),
[decision 0013](decisions/0013-week-ahead.md)).** The Dividend Week Ahead, end to end into a folder
(`--week-ahead --out DIR`); the pull request is milestone 12. Research is the agentic loop, told
today's date and the week. Code builds the data block from the recorded results and checks it with
`provenance.check_data`; a week the research didn't cover, or a company it didn't look up, fails the
run in its research phase. The model writes two prose sections as JSON (Ollama's `format`), sent
back up to three times while they have figures. Each of the six translations is checked for figures
and for a length 0.75–1.75 times the English; one that fails is held (exit 6), the rest are written.
The data block's YAML is serialised once and is the same bytes in all seven files, and every file
is read back before it's written. The "same structure" check needs no code of its own: a reply is
parsed into the prose's model, which has exactly its sections. Spanish isn't treated differently by
the agent: the spot-check is the reviewer's, in the pull request. Measured
([benchmarks](benchmarks/2026-10-08-week-ahead/README.md)): 10 of 10 runs published, none of 114
translations held, and the Catalan had errors any reader sees. The checks are structural; whether
`ca`, `fr`, `de`, `it` and `pt` can publish on them is open (open question 12).

### 3.6 Concurrency model

The interesting shape: **one GPU, many network calls.**

- LLM inference is a serialised resource — a semaphore of capacity 1 (configurable) around the model
  client. Queued tasks wait; they do not thrash the GPU. This matters more with an agentic loop,
  since one task now makes many sequential model calls. *(As built, milestone 9: `llm.Client(...,
  slots=1)` around `generate` and `chat`; `--research` given several times runs the questions at
  once, sharing the client. Measured: three questions as one batch took 10.4s against 14.4s one
  after another, about a quarter of the saving from starting Python once and the rest from network
  work overlapping the other runs' model calls
  ([benchmarks](benchmarks/2026-10-08-worker-pool/README.md)).)*
- Tool fetches within a research step fan out, bounded so Quantic isn't hammered (Go's `errgroup`;
  Python's equivalent is chosen at milestone 9). *(As built, milestone 9,
  [decision 0011](decisions/0011-worker-pool.md): an `asyncio.TaskGroup` per model reply, four calls at
  a time behind a semaphore, each task returning its failure rather than raising it so the calls
  beside it finish and are recorded. Every MCP request in the process shares one `quantic.Pace`: at
  most 50 in any 60 seconds.)*
- Each run carries one deadline and one way to cancel it, threaded through both phases (Go's
  `context`; Python's way is milestone 4's subject).
- Translation of the six non-source locales is embarrassingly parallel in principle but serialised in
  practice by the same GPU semaphore — a good place to learn what a bottleneck actually costs.
- The daemon is opportunistic: the machine is not always on. State is checkpointed in SQLite after
  each phase so an interrupted run resumes rather than restarts.
- **The GPU is shared, not owned.** The desktop is also the author's machine, and sometimes the author
  needs most of the VRAM. Both the agent and Ollama must be easy to stop, start and restart, and neither
  may lose work when stopped. So: `SIGTERM` is a clean stop at the next checkpoint, and an unreachable
  Ollama is a reason to wait, not to fail — the run stays queued until the server is back. The
  client reports that case as an error of its own, distinct from every other failure, and the
  agent exits with status 3 for it so a scheduler knows a retry is safe. *(As built, milestone 3:
  `llm.ServerUnavailableError`, for a refused, reset or dropped connection or no route to the server;
  not for a DNS failure, which is usually a typo, nor a timeout. A missing model is
  `ModelNotFoundError`, any other refusal `APIError`.)* `SIGTERM` (or Ctrl-C)
  cancels the request in flight and exits with 130; Ollama stops generating within about a second,
  so stopping the agent gives the GPU back straight away. *(As built, milestone 4: the agent is
  async ([decision 0008](decisions/0008-async-for-deadlines-and-cancellation.md)). The model client
  has no timeout of its own; `--timeout` bounds a run with `asyncio.timeout`, default five minutes,
  and both signals cancel the main task. Measured: Ollama's log shows the cancelled generation
  stopped, and a cancelled cold load aborted.)* The runbook has the commands ([target machine §8](target-machine.md#9-freeing-the-gpu)).
- **As built in Go (milestone 8).** A run is checkpointed in SQLite when research ends (`runs.phase`:
  `research` → `write` → `done`), and every tool call is already recorded as it completes.
  `agent -resume N` continues a run that was interrupted or failed before answering: one stopped while
  writing calls no tool again; one stopped during research replays its recorded calls to the model
  as the conversation so far, and carries on within what's left of its budget. Claiming a run to
  resume is one conditional `UPDATE`, so two resumes of the same run can't both get it. Quantic's
  `429` is retried in the MCP client with exponential backoff and jitter, long enough to outlast its
  one-minute window, then reported as rate-limited (exit 3, resumable). Research with no
  successful call skips writing and ends `no_data` (exit 5, resumable): an answer about nothing isn't
  an answer. Adding that state rebuilt `runs` (migration `0003`), with foreign keys off for that one
  connection, as SQLite's own recipe requires. There is no
  scheduler yet: resuming is a command, not automatic.
- **As built (milestone 8).** The same phases, `--resume N`, exit statuses and claim. A resumed run
  keeps the model it started with and the date it started on. The `429` retry sits under the MCP SDK,
  as an HTTP transport, because the SDK has none: left alone, it turned a `429` into a JSON-RPC
  error indistinguishable from a request the server rejected, which the loop would have handed to the
  model to correct. When the retries run out, the transport answers the request itself with a
  JSON-RPC error code of the agent's own, which the SDK passes up; raising instead made the SDK
  cancel the waiting call, which reads as Ctrl-C. Only POSTs are retried. Measured on the real
  machine: Ctrl-C while the model worked took the GPU from 91% to 0% within two seconds, and the run
  resumed from its write phase with no MCP server reachable.

### 3.7 Storage

SQLite, through Python's standard-library `sqlite3` (Go used `modernc.org/sqlite`, a pure-Go driver,
to keep a static binary; Python has no binary to keep static).

- `runs` — id, task_kind, params, phase, state, budgets_used, started_at, finished_at, error
- `tool_calls` — id, run_id, tool, args, response, duration_ms, called_at *(the audit log, N3)*
- `drafts` — id, run_id, locale, role (`source` | `spot_check` | `auto`), content, state,
  validator_report, created_at
- `manifests` — draft_id → tool_call_ids *(provenance link, N1)*
- `embeddings` — id, source_kind, source_id, chunk, vector BLOB, model, created_at *(as built,
  milestone 10: with `dims`; `source_kind` is `answer`, an approved run's answer, one vector per
  model; the run's `examples` are a table of their own)*
- `reviews` — draft_id, verdict, reviewer_note, decided_at *(feeds both style memory and the
  accept-rate metric)*

Retention: `tool_calls` responses can be large; plan a compaction policy before it becomes a problem.

**As built in Go (milestone 7, [`internal/store`](https://github.com/fleveque/quantic-agent-go/tree/main/internal/store)).** `runs`, `tool_calls` and `drafts`
exist; the draft's `validator_report` is its list of provenance findings. `manifests` isn't needed yet:
a draft is checked against all its run's successful calls, so the run *is* the link. It arrives when one
run produces several drafts. Migrations are numbered SQL files embedded in the binary, each applied
once in its own transaction. Tool calls are written as they happen, so a stopped or crashed run keeps its
audit trail, and `agent -run N` re-checks a stored answer against exactly the results it was given,
whatever the tools would say today. The database lives at `$XDG_STATE_HOME/quantic-agent/agent.db`
(`~/.local/state/...` by default); `-db` or `QUANTIC_AGENT_DB` override it.

**In Go: migrations hand-written first, on purpose, with a known gap.** Go's standard library has no migration
tool; the usual choices are `pressly/goose` or `golang-migrate/migrate`. For one process, SQLite and
forward-only migrations, forty lines in `internal/store` do the job without a dependency. What they
lack: down migrations, a CLI, and **locking across processes**. Two processes opening a *new* database
at the same moment can collide: in a test of 20 simultaneous pairs, 2 of the 40 opens failed with
`database is locked (SQLITE_BUSY)` while creating `schema_migrations`. Nothing is lost, and the next
start succeeds, but that process exits with an error. Milestone 9's worker pool is one process, so it's
unaffected.

**Decision, in Go: switch to goose at the start of milestone 8.** A migration library is what most Go
applications with a SQL database use (`golang-migrate/migrate` and `pressly/goose` are the two usual
ones), and doing it by hand first, then with the library, shows both approaches. Goose brings what the
hand-written version lacks: down migrations to undo a migration that turned out wrong, locking across
processes, and a CLI. It reads SQL migrations from an `embed.FS`, so `0001` carries over, gaining the
`-- +goose Up` / `-- +goose Down` markers.

**As built in Go (milestone 8).** "Locking across processes" was wrong for SQLite: goose ships lockers for Postgres and MySQL only, whose servers offer a lock to take. Measured
with real processes, goose without a lock collided more often than the hand-written code (11–13 of
40 opens of a new database failed, against 6–7). `internal/store` takes an exclusive `flock` on
`agent.db.lock` around migrating, which made it 0 of 200, and also covers the one-time handover of a
milestone 7 database: its versions move from `schema_migrations` into goose's `goose_db_version`, in
one transaction. A test takes every migration down and back up. `0002` adds `phase`, `tokens` and
`exhausted` to `runs`.

**As built (milestone 7, [`store.py`](../src/quantic_agent/store.py)).** The same three tables as Go's
milestone 7, with the same first migration, applied by about thirty hand-written lines: numbered SQL
files shipped in the package, each applied once in its own transaction (`sqlite3` with
`autocommit=True` and an explicit `BEGIN IMMEDIATE`; its default mode's `executescript` would commit
a migration halfway). The `flock` is there from the start, not added later: measured with real
processes, 5 of 80 opens of a new database failed without it, and one of 80 still failed with the WAL
switch left outside it; with both inside, 0 of 400. Tool calls are written as they happen, through
the loop's `on_call`. The store is synchronous and the agent async: a save takes milliseconds, and
because cancellation only lands at an `await`, the save that records an interrupted run always
completes (Go needed `context.WithoutCancel`). `--runs` lists runs and `--run N` re-checks one, at
the same path and with the same `--db` / `QUANTIC_AGENT_DB` override. Whether to move to a migration
library is milestone 8's question, as it was Go's.

**As built (milestone 8).** Alembic ([decision 0010](decisions/0010-alembic-for-migrations.md)),
on a SQLAlchemy connection of its own, with `connect_args={"autocommit": False}`: measured, in
`sqlite3`'s default mode a migration that failed partway left its first table behind with the version
unchanged. The `flock` stays, and covers the one-time handover of a milestone 7 database
(`schema_migrations` → Alembic's `alembic_version`, one transaction). Alembic has no lock for SQLite
either, and without ours it collided far more than the hand-written code: 47 and 50 of 80 opens of a
new database failed, each within half a second, so SQLite refused rather than waited; with it, 0 of
400. A test takes every migration down and back up. `0002` adds `phase`, `tokens` and `exhausted`;
`0003` rebuilds `runs` to add `no_data`. The migration connection never turns foreign keys on, so
the rebuild needs no `PRAGMA` dance, and it ends with `PRAGMA foreign_key_check`.

### 3.8 Delivery

- **Review queue** — SQLite rows plus a minimal read-only HTTP view (server-rendered HTML, no JS
  framework) once there are more than a handful of drafts. Deliberately not a product.
- **Pull requests** — through GitHub's API: branch, commit one file per locale (typed frontmatter + prose,
  per the [format contract](rendering.md)), open PR against the private Quantic repo targeting
  `/insights`. Token scoped to branch and PR creation only; `main` is protected independently, so a
  bug in the agent cannot merge. NimblePublisher compiles posts at build time, so a malformed post
  fails CI rather than a request.
- **Issues** — for data-QA findings with no mechanical fix.

## 4. Stack

| Concern | Choice | Reasoning |
|---|---|---|
| Inference server | Ollama | Three model tiers behind one endpoint with load/unload on demand, embeddings on the same server, and per-model capability metadata. `llama.cpp` stays the escape hatch ([llm-kit](https://github.com/fleveque/llm-kit)) with explicit triggers — [decision 0004](decisions/0004-ollama-now-llama-cpp-on-a-trigger.md). |
| Default model | Qwen3.5-9B, Q4_K_M (6.6GB) | Measured on the target card: 100% on GPU up to 64K context (8.0GB), about 80 generated and 4,400–5,000 prompt tokens/second — [decision 0005](decisions/0005-default-model-by-measurement.md). |
| Candidates | `qwen3.6:35b` (MoE); Qwen3.8-27B `UD-IQ3_S` | The MoE writes at ~70 tokens/second even with 44% of itself in system RAM; the dense 27B fits fully only at 8K. Decided on task quality from milestone 5, not on speed or size. |
| Fast model | Qwen3.5-4B (3.4GB) | Mechanical passes — data-QA triage, classification — where a 9B is overkill. |
| Embeddings | `qwen3-embedding:0.6b` via Ollama | Chosen over `nomic-embed-text` by measurement at milestone 10 ([decision 0012](decisions/0012-style-memory.md)): 10 of 12 against 8, 2.4GB of VRAM. |
| Model I/O | JSON-schema-constrained decoding | Local models are flakier at native tool-calling than frontier models; constrained output is the reliable floor, native tool-calling an optimisation. |
| Tool schemas | Generated from Pydantic models | Single source of truth; the type *is* the schema. Go generated them from structs by reflection. |
| Persistence | `sqlite3` | Standard library. |
| GitHub | chosen at milestone 12 | Go used `go-github`. |
| Logging | chosen at milestone 13 | Structured, and feeds N3. Go used `log/slog`. |
| Config | YAML + env, flags for overrides | Secrets via env only, never committed. |
| Language and tools | Python 3.14, `uv`, `ruff`, `pyright` (strict), `pytest` | [Decision 0007](decisions/0007-continue-in-python.md). Strict type checking in CI stands in for Go's compiler. |
| HTTP and validation | `httpx`, Pydantic | Decision 0007. Pydantic validates what crosses a boundary, where Go decoded into structs. |

**Thinking models.** The Qwen3.5-era models run a reasoning pass before answering, returned in a
separate `thinking` field. Both phases send `think:false`. Reasoning text is not a source: it never
enters the manifest, never reaches a draft, and is not something N1 could validate even in principle.
It is also expensive — a thinking reply spends its token budget on reasoning first, so a truncated
one can arrive with a full `thinking` field and an empty answer. Requests carry `think:false`
explicitly rather than relying on a default, and a model with no thinking mode accepts the field and
ignores it.

**Hardware:** 64GB RAM, RTX 4070 Ti Super (16GB VRAM).

**KV cache before quantisation.** At long research contexts the KV cache outgrows the weights, so
`OLLAMA_KV_CACHE_TYPE=q8_0` (about half the cache memory, needs flash attention) is the first lever to
pull before trading model size away. It fails quietly on architectures without flash attention
support, so it is a thing to verify on the target machine rather than assume.

**Sizing the model to the card** — the reasoning before measurement; the measured outcome is in
[decision 0005](decisions/0005-default-model-by-measurement.md). The newest Qwen at this size is **Qwen3.8-27B**. Ollama's own library
publishes it only at Q4_K_M (18GB), which cannot hold weights *and* a KV cache in 16GB. But Unsloth
publishes sub-4-bit GGUFs on Hugging Face, which Ollama pulls directly
([decision 0004](decisions/0004-ollama-now-llama-cpp-on-a-trigger.md)): `UD-IQ3_S` is 12.0GB,
`UD-Q3_K_XL` 13.1GB, `UD-IQ4_XS` 14.3GB.

What makes the 27B viable at these sizes is its architecture: 64 layers arranged as 16 × (3 Gated
DeltaNet + 1 standard attention), with 4 KV heads on the attention layers. Only those 16 layers keep a
KV cache — roughly a quarter of what a conventional 64-layer model needs at the same context — and the
DeltaNet state doesn't grow with context at all.

The risk is quality, not fit. Below 4 bits per weight a model degrades, and the degradation shows up
first in exactly what this agent leans on: precise structured output and tool-call arguments. A
throughput benchmark can't see that. So the 27B is the *primary candidate*, confirmed by the benchmark on
the target card for speed and residency, and by tool-call validity once milestone 5 exists. The 9B
remains the default until both say otherwise — a default that silently fails to fit is worse than a
smaller one that works.

An earlier version of this section concluded that no 27B fits in 16GB. That was true of Ollama's
library and false once Hugging Face quants were counted — the research had only looked at models
already installed on the development laptop.

**Development is not deployment.** The agent is written on one machine and runs on another, so no
model name, host or path is baked into the code. `--model` / `QUANTIC_MODEL` and `--ollama` /
`OLLAMA_HOST` carry them ([runbook](target-machine.md)), and the agent's check prints what the server
it is pointed at actually has,
including each model's `capabilities` — the `tools` entry is what milestone 5 depends on.

Keep the target's Ollama current. Version floors per model are undocumented, and the desktop's 0.24.0
refused Qwen3.5 outright with a `412: requires a newer version of Ollama`.

## 5. Open questions

1. **MCP authentication from a headless daemon.** Quantic's MCP server uses OAuth, which assumes an
   interactive consent flow. A local daemon needs a non-interactive credential: a long-lived service
   token scoped to read-only tools, a direct internal API path, or a one-time grant with a stored
   refresh token. *Answered 2026-10-06* — [decision 0006](decisions/0006-anonymous-mcp-for-public-tools.md):
   the server already answers anonymous callers for its public reference tools and refuses them its
   portfolio tools, so the agent connects anonymously. A service token, with no user behind it, is
   the plan for when an authenticated reference tool is needed.
2. **The `/insights` section doesn't exist yet.** It's Phoenix work in the private repo: route,
   layout, markdown rendering, per-locale routing consistent with the existing language subdomains,
   sitemap and hreflang, plus the free-registration gate and its `schema.org` flexible-sampling
   markup. The agent has nowhere to open PRs against until it exists. *Prerequisite for
   milestone 12.* The only agent-side obligation is emitting the `fold_after` marker in draft
   frontmatter — see the [content plan](content.md#registration-gate). *(Milestone 11 writes the
   files into a folder, in the format [as built](rendering.md#as-built-milestone-11), so `/insights`
   can be built against real posts.)*
3. **How do we know a draft is any good?** Provenance proves it isn't *wrong*; it doesn't prove it's
   worth publishing. Track human accept/reject rate per task kind and treat it as the metric that
   matters. A task kind below some accept rate is broken — the task, not the reviewer.
4. **Idempotency.** Re-running after a crash must not produce a duplicate weekly digest. Natural key
   per run (kind + period) and an upsert.
5. **Scheduling.** Internal ticker in the daemon vs. systemd timers invoking a one-shot command. The
   one-shot model is simpler and more crash-tolerant; the daemon model makes the worker pool
   meaningful. Probably both.
6. **Prompt storage.** Prompts are code and should be reviewed like code — versioned in the repo and shipped
   inside the package (Go used `embed`; Python reads package files with `importlib.resources`), not
   stored in the database. They must contain no Quantic-internal content (N4).
7. **Chunking strategy for filings.** 10-Ks are long and structured. Naive fixed-size chunking will
   split tables badly. Deferred until milestone 10.
8. **Can a 14B model reliably write prose with no figures in it?** The format contract forbids
   numbers in prose entirely. Small models will violate this. The validator catches it and retries,
   but if the violation rate is high the writing prompt needs restructuring — possibly generating
   prose and data in separate calls. This is the likeliest place the accept-rate metric first bites.
   *(Measured, milestone 11, `qwen3.5:9b`: with retries, yes. Prose and data are already separate
   calls. The first attempt had figures in 15 to 20 of 20 writings, depending on the prompt, and
   the retry that names them removed them; 10 of 10 real runs published. Two causes, one fixable:
   the data's field names (`cagr_5y` became "five-year", gone once the writer was shown
   `long_term_growth`), and counting the companies ("two"), which no prompt stopped.
   [Benchmarks](benchmarks/2026-10-08-week-ahead/README.md).)*

9. **Which primary model, measured on the target box.** Qwen3.8-27B at `UD-IQ3_S` or `UD-Q3_K_XL`
   (best model that fits, reduced precision) against Qwen3.5-9B Q4_K_M (fits easily, most context).
   The deciding numbers are tokens/second and GPU residency at realistic research-context lengths —
   where the 27B's cache stops fitting — and, from milestone 5, tool-call validity at 3-point-something
   bits. Nothing in the code depends on the answer — it is one flag.

   The benchmark (`cmd/bench` in Go) measures it: prompt and generation rates per model and context size, plus the share of
   each model that stayed in VRAM (`/api/ps` reports `size` against `size_vram`, and anything below
   100% means layers spilled into system RAM). Run it on the deployment machine — a development
   laptop with no CUDA device reports 0% and about 10 tokens/second, which answers nothing about the
   4070 Ti Super. Two further notes the tool encodes: each measurement carries a unique nonce,
   because Ollama's prefix cache otherwise reports cached tokens as if it had processed them, and
   every request sets `num_ctx`, because the server defaults to a 4096-token window whatever the
   model supports and silently truncates a longer prompt.

   *Answered 2026-09-26 by measurement* — [decision 0005](decisions/0005-default-model-by-measurement.md).
   The 9B stays the default. The 27B fits entirely only at 8K, and a mixture-of-experts model
   (`qwen3.6:35b`) turned out to be the more interesting candidate: spilling into system RAM costs it
   little. Quality decides between them from milestone 5.

10. **Model upkeep as a task.** How the agent learns a new model exists (Ollama library, Hugging Face
    feeds, a hand-maintained list), and whether it may pull one itself. Today pulling is a deliberate
    manual step ([runbook §3](target-machine.md#3-pull-the-candidate-models-34gb)): models are
    6–50GB, and a scheduled pull would take disk space and the GPU without anyone asking. The likely
    answer is that the agent proposes candidates and a human pulls them, after which the agent runs the
    evaluation and opens the PR. Needs the milestone 5 evaluation set first.
11. **Where filing and news text comes from.** §3.4 plans to retrieve 10-K and press-release text for
    valuation write-ups, but nothing names the source. Open web browsing is ruled out: a page can carry
    instructions aimed at the model (prompt injection, which small local models resist poorly), a
    figure from an arbitrary page would look like a recorded tool call without being trustworthy
    (N1), and it would widen the research allowlist from a known set to the whole internet. The likely
    answer is a short list of trusted sources, each its own read-only tool in the allowlist — SEC
    EDGAR for filings, a company's own investor-relations releases — with fetched text treated as
    untrusted input: stored and embedded as language, never followed as instructions, never a source
    for a number. Open: which sources, whether the text comes from Quantic's MCP server rather than
    the agent fetching it, and how non-US issuers are covered. *Needed by milestone 10.*
12. **Can translations publish on machine verification?** §3.5 publishes `ca`, `fr`, `de`, `it`
    and `pt` when the translation checks pass, and those checks are structural: no figures, a length
    near the English. Milestone 11's real Catalan passed them with errors any reader sees (a word cut
    short, Spanish words, a misspelling). The options include a larger model for translation only,
    the reviewer reading Catalan as well as Spanish, or publishing fewer locales until a model
    translates well enough, which needs a way to measure translation quality. *Needed before
    milestone 12 publishes anything.*

## 6. Explicit non-goals

- Not a general-purpose agent framework. It does a handful of known jobs well.
- Not a product. No multi-user support, no auth beyond the local machine, no hosting.
- Not real-time. Everything here is batch work that tolerates minutes of latency.
- Not fine-tuning. Retrieval, not training. If the model needs to be better, use a better model.
- Not touching business logic, financial calculations, or anything involving real user money.
