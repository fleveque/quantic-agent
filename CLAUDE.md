# quantic-agent — notes for Claude Code

A local agent that drafts data-grounded content for Quantic using local models through Ollama, in
Python. It is also how the author, who writes Elixir and Ruby daily and has just learned Go, comes to
understand Python. The first version was Go, up to milestone 8: `../quantic-agent-go` (archived,
`github.com/fleveque/quantic-agent-go`). Its design, ADRs, benchmarks, fixtures and lessons are the
starting point here.

## Status — 2026-10-08

- **Milestone 0 merged** (#1): design, ADRs 0001–0007 and benchmarks carried over; lesson 00.
- **Milestone 1 merged** (#2): `quantic_agent/cli.py`, `quantic_agent/tools.py`; lesson 01.
- **Milestone 2 merged** (#3): `quantic_agent/llm.py` (httpx + Pydantic), `--check`/`--ask`,
  `quantic-bench`. Tests run against a real local fake server (`tests/conftest.py`) answering with
  `tests/fixtures/ollama/`; lesson 02.
- **Milestone 3 merged** (#4): `LLMError` with `ServerUnavailableError`, `APIError`,
  `ModelNotFoundError(APIError)`; exit 3 when unavailable; lesson 03.
- **Milestone 4 merged** (#5): async (ADR 0008), `asyncio.timeout`, Ctrl-C/SIGTERM exit 130; async
  tests through anyio's plugin; lesson 04.
- **Milestone 5 merged** (#6): the official MCP SDK (ADR 0009) behind
  `quantic_agent/quantic.py`; `llm.Client.chat` with tools; `tools.Tool` whose Pydantic arguments
  model is the schema (strict, extra forbidden); `agent.Researcher` with `typing.Protocol`s and an
  `on_call` callback per tool call; `--research`, `--mcp`/`QUANTIC_MCP_URL`; `quantic-evaltools`
  (cases in `src/quantic_agent/eval_cases.json`); `network.unreachable` shared by both clients. The
  fake MCP server (`quantic_mcp` fixture) replays `tests/fixtures/mcp/` for the real SDK; lesson 05.
  Go's `QUANTIC_MCP_TOKEN` isn't ported: nothing authenticated is needed yet (ADR 0006).
- **Milestone 6 merged** (#7): `quantic_agent/provenance.py` (`Manifest`,
  `check_data`, `check_prose`, `no_figures`); `--research` exits 4 for figures with no source.
  Booleans are never numbers in the manifest (`True == 1`). Go's later fixes (numbers in words,
  "16 and 17", list lengths, the question's and today's figures) come with milestone 8; lesson 06.
- **Milestone 7 merged** (#8): `quantic_agent/store.py` (stdlib `sqlite3`, sync, `autocommit=True` +
  `BEGIN IMMEDIATE`, `flock` around WAL switch and migrating); `--research` records runs and calls as
  they happen; `--runs`, `--run N`, `--db`. Tests are isolated from the real state directory by an
  autouse fixture (`isolated_state`); lesson 07.
- **Milestone 8 merged** (#9): migrations with Alembic (ADR 0010,
  `migrations/env.py` + `versions/0001..0003`, a M7 database handed over once); `agent.Research` /
  `Researcher.research` (budgets, replay of recorded calls, continued in place) and `agent.Writer`
  (no tools, told the run's start date); `quantic.py` retries 429 in an httpx2 transport under the
  SDK; phases, checkpoints, `--resume N`, `no_data` (exit 5); provenance with Go's later fixes plus
  weekdays next to a date and "Oct 8-10" ranges; real runs in `docs/benchmarks/2026-10-08-python-writer/`
  (4/9 traced); lesson 08. The Python version is now where the Go version stopped.
- **Milestone 9 merged** (#10), the first with no Go version (ADR 0011):
  `tools.GET_STOCK`; a reply's tool calls run at once in a `TaskGroup` (4 at a time, failures
  returned, not raised); `llm.Client(slots=1)` is the GPU queue; `--research` given several times
  runs a batch; `quantic.Pace` (50 requests in any 60s, shared) in the MCP transport; `--num-ctx`
  (default 32768, measured: at 4096 the writer's prompt was cut to 2,050 of 6,945 tokens); budget 16
  calls / 64,000 tokens; provenance indexes numeric and date keys and year-months; evaltools offers
  both tools (45/50). The author decided: "today" stays the agent's local date; lesson 09.
- **Milestone 10 merged** (#11, ADR 0012): style memory. `--approve N` /
  `--reject N` / `--note` / `--recall Q`; migration 0004 (reviews, embeddings, examples);
  `quantic_agent/memory.py` (float32 little-endian BLOBs at unit length, `math.sumprod`, `heapq`);
  `llm.Client.embed` (`truncate: false`, takes its GPU turn); the writer is shown the 2 nearest
  approved answers, recorded per run, never in the manifest; `qwen3-embedding:0.6b` with its query
  instruction, measured by `quantic-evalrecall` (`recall_cases.json`): 10/12 vs nomic's 8/12.
  Plain Python, no numpy (500 vectors ~10ms). Only answered (traced) runs can be approved; lesson 10.
- **Milestone 11 merged** (#12, ADR 0013): the Dividend Week Ahead into a
  folder, `--week-ahead --out DIR`. The author chose: public data only (no amounts, raises, radar;
  content.md lists the gaps), and the agentic loop for research. `quantic_agent/weekahead.py`:
  `week_after` (ISO week names the post), `question` (tells today's date: without it the 9B asked
  for 7 days from a Thursday), `gather` (data built by code from the recorded calls, checked with
  `check_data`; `IncompleteError` keeps the run in research), `write` (JSON prose via Ollama
  `format`, no figures, 3 attempts, `WRITER_NAMES` hide `cagr_5y`-style names), `translate` +
  `check_translation` (figures, length 0.75–1.75), YAML with every string double-quoted, files read
  back before writing. Prompts and `locales.json` are package data (`importlib.resources`); PyYAML.
  Migration 0005 (`posts`); exit 6 when a locale is held; a run is recorded before its files are
  written; week-ahead runs can't be `--approve`d. Real runs: 10/10 published, 0 of 114 translations
  held, Catalan visibly wrong (design open question 12); lesson 11.
- **Milestone 12 in review** (branch `m12-pull-requests`, ADR 0014): `--pr N` and `--sync`. The
  author chose: a GitHub App; PRs on the Quantic repo now (path `priv/insights/`, `--repo-path`);
  every ready locale in the PR, reviewed by the author; `--sync` (merged = approved, closed =
  rejected). Quantic's `main` can't be protected (private repo, free plan), so the author chose the
  agent's guard plus a deploy check (quantic#486). `quantic_agent/github.py`: App JWT (PyJWT, RS256)
  → installation token, cached; the only ref write is creating `refs/heads/agent/...`; no PATCH,
  PUT or DELETE. `quantic_agent/publish.py` builds branch, files and description from the run as
  stored. Migration 0006 (`pull_requests`, one per run, one open per week). Settings:
  `QUANTIC_AGENT_GITHUB_APP_ID`, key file `~/.config/quantic-agent/github-app.pem` (refused unless
  600), `QUANTIC_AGENT_REPO`; runbook §8b; lesson 12.
- design.md keeps Go's "As built in Go" notes next to this repository's "As built" notes.
- PRs are squash-merged, so a walkthrough built from a branch commit cites a SHA `main` won't have.
  After merge, rebuild the walkthrough page from the merge commit and republish the artifact. That
  updates the published page only: no commit, nothing pushed.
- `ruff format --check` also formats ```` ```python ```` blocks in Markdown: lesson snippets must be
  valid, formatted Python, or use an unlabelled fence for verbatim quotes and fragments.
- Break-it experiments: a same-size edit within the same second runs stale bytecode. Run them with
  `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider`.
- `uv` comes from mise (`mise use -g uv@latest`); in a non-login shell, `eval "$(mise env -s bash)"`
  first.
- `docs/lessons/pages/build.py` is in the gate (ruff, strict pyright). Its `^` end marker takes a
  top-level Python block; marker text can't contain `]` or `|`.

## Next, in order

1. **Milestone 13 — ship it**: logging, a systemd unit (README roadmap). The timer would run
   `--week-ahead`, `--pr` and `--sync`. Quantic's `/insights` section (design open question 2) is
   still unbuilt: merged posts land in `priv/insights/` with nothing rendering them.
2. Ollama's truncation is invisible in its replies (only its log says `truncating input prompt`);
   detecting it from the agent is open.
3. Seen in real runs, not caught: counts of a filtered subset ("four companies") are flagged though
   right; a wrong statement whose figures all trace ("no companies in the next 10 days") passes; the
   9B sometimes reasons out loud in an answer despite `think: false`.
4. Seen in milestone 11's real runs, not caught: prose that's wrong without a figure ("recent
   acceleration" for a slowing dividend; "safety remains strong" for one on watch), and phrasing
   that leans towards advice ("a stable alternative"). Numbers in words are recognised in English
   only, so a translation's "dues" passes.
5. Ratios in get_stock (`cagr_5y` 0.1023) written as percentages ("10.23%") are flagged as
   converted figures, correctly by N1; a percentage calculator tool would let them through.

## Conventions

- **Every milestone ships code and a lesson**: `docs/lessons/NN-*.md` (NN = milestone number), written
  in the author's first person — someone who writes Elixir and Ruby, has just learned Go, and is
  coming to understand Python — plus a formatted page published as an artifact and linked from the
  lesson and `docs/lessons/README.md`. Every page uses the stylesheet in `docs/lessons/pages/` (see
  its README); reuse it, don't redesign it.
- **…and a code walkthrough** for every milestone with code: a second artifact that goes through
  every file the milestone's PR added or changed, in reading order, as a tech lead mentoring someone
  new to Python: what each part does, why it's written that way, what the standard library and each
  dependency are doing. Excerpts are copied verbatim from a named commit with
  `docs/lessons/pages/build.py`; "try it" experiments show real outputs, usually by breaking the code
  on purpose and showing the test that catches it. **Compare with Go** (the author knows it now,
  from quantic-agent-go), and with Elixir or Ruby where that helps more. Linked from the lesson and
  the lessons README.
- **Ported milestones say what changed.** When the Python version differs from the Go one (a library
  instead of hand-written code, a different design because the language suggests it), the lesson
  says so and why.
- **Milestones are worked one at a time**, each on its own branch and PR. The author says when to
  start the next one.
- **Decisions are ADRs** in `docs/decisions/NNNN-*.md`, numbered on from quantic-agent-go's.
- **`main` is protected.** Branch → PR → CI green → the author merges. Never merge. Before pushing to
  an existing branch, check its PR isn't already merged.
- **Verify CI on the exact commit SHA** (`gh run list --json headSha`), not the PR's check list, which
  can still show the previous commit's run.
- **Gate before every commit**: `uv run ruff format --check .`, `uv run ruff check .`,
  `uv run pyright` (strict), `uv run pytest`, and the relative-link check in
  `.github/workflows/ci.yml`.
- **Claims are verified by running them.** Test fixtures are payloads captured from a real Ollama and
  Quantic (quantic-agent-go's `testdata` carry over). Lesson outputs are real outputs. Every guarantee
  a test claims is checked by breaking the code and watching the test fail.
- **Nothing machine-specific in the code**: `--model`/`QUANTIC_MODEL`, `--ollama`/`OLLAMA_HOST`.
- **Models are used as published** (Ollama library or `hf.co` pulls). No hand-built variants via
  `ollama create`; new models arrive too often to maintain them.
- **The GPU is shared with the author.** Anything long-running must stop cleanly and tolerate a stopped
  Ollama.
- **Questions are not decisions.** When the author asks something, answer it; ask before turning it
  into a design change.
- The design's non-negotiables — no invented numbers, no autonomous publishing, full auditability, no
  user data leaving the machine, informational never advisory — are not up for convenience
  trade-offs. The agent must never be given a personal access token (decision 0006).

## Quantic MCP, learned the hard way

- `https://quantic.finance/mcp`, Streamable HTTP. Replies are SSE when the client accepts it, JSON
  otherwise; clients must accept both. `initialize` returns `Mcp-Session-Id`.
- No `Authorization` header = anonymous: public reference tools answer (60 req/min/IP), portfolio
  tools return `isError: true`. A bad token is `401`, never a fallback to anonymous.
- A `429` comes from fixed one-minute windows with no `Retry-After`: back off for at least a minute
  in all, with jitter.
- A tool's output is a JSON document *inside* `content[0].text`: decode twice.
- Tool refusals are results (`isError`); protocol mistakes are JSON-RPC errors (`-32602`).
- With the SDK: use `mode="legacy"` (the default "auto" wastes a `server/discover` request per
  session). Connection failures arrive as `ExceptionGroup`s around `httpx2` errors (flatten before
  classifying); cancellation is not wrapped. The SDK's HTTP library is `httpx2`, not `httpx`.
- The SDK has no 429 retry: it turns a 429 into JSON-RPC error -32603 ("Server returned an error
  response") and drops a refused notification silently. An exception raised in its HTTP transport
  cancels the waiting call (`CancelledError`) and surfaces only at session exit; answer with a
  JSON-RPC error instead. The SDK sends `tools/list` once per session, before the first `tools/call`.
- The server's code is in `../quantic` on `main` (`lib/quantic_web/mcp/`). Fetch first: the local
  checkout lagged `origin/main` by three months.

## GitHub, learned the hard way

- Branch protection and rulesets are refused (403, "Upgrade to GitHub Pro") for a private repo on
  the free plan. Quantic is one; quantic-agent, public, has its `main` protected.
- An App's Contents write covers every branch, `main` included. Creating a ref that exists is a
  422 ("Reference already exists"): creating, never updating, is what keeps `main` out of reach.
- An App authenticates with a JWT (RS256, `iss` = App ID, at most 10 minutes) only to get an
  installation token (1 hour) from `/repos/{repo}/installation` then
  `/app/installations/{id}/access_tokens`; everything else uses the token.
- `workflow_run.actor` is who pushed; `triggering_actor` who started the run, which a re-run
  changes. A person's merge shows `type: User` in both.

## Ollama, learned the hard way

- `stream` must be sent as `false` explicitly; the server streams by default.
- `num_ctx` defaults to 4096 whatever the model supports; longer prompts are truncated.
- Qwen3.5+ are thinking models: send `think:false`. Reasoning text never enters a draft.
- The prefix cache reports cached tokens as processed; benchmarks need a unique prompt prefix.
- Model names resolve case-insensitively; compare them case-insensitively.
- `hf.co/{user}/{repo}:{QUANT}` pulls any Hub GGUF. Per-model version floors are undocumented.
- Error bodies are `{"error": ...}` JSON, except a bad path, which is plain text.
- `/api/chat` takes `tools`; a reply asking for one has empty `content` and `tool_calls` whose
  `arguments` is a JSON object (not a string). Send the tool result back as `role: "tool"` with
  `tool_name`.
- Changing `num_ctx` between requests reloads the model. Overflowing it truncates silently: the
  reply's `prompt_eval_count` is just smaller; the log says `truncating input prompt`.
- Cancelling a request mid-generation stops the GPU work within about a second; cancelling while a
  model is loading aborts the load. Deadlines must allow for a cold start (up to ~31s measured).

## SQLite, learned the hard way

- Per-connection settings (`foreign_keys`, `busy_timeout`, WAL) must apply to every connection.
- Migrating from several processes at once collides; a file lock (`flock`) around migrating fixes it.
- Adding a value to a `CHECK` constraint means rebuilding the table, with foreign keys off for that
  connection, outside a transaction (SQLite's documented recipe).
- Alembic on `sqlite3` needs `connect_args={"autocommit": False}`, or a failed migration leaves its
  tables behind. Without the `flock`, Alembic migrating a new database from 4 processes failed 47–50
  of 80 opens, with or without `autocommit=False` (different errors, same count).
