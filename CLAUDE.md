# quantic-agent — notes for Claude Code

A local agent that drafts data-grounded content for Quantic using local models through Ollama, in
Python. It is also how the author, who writes Elixir and Ruby daily and has just learned Go, comes to
understand Python. The first version was Go, up to milestone 8: `../quantic-agent-go` (archived,
`github.com/fleveque/quantic-agent-go`). Its design, ADRs, benchmarks, fixtures and lessons are the
starting point here.

## Status — 2026-10-07

- **Milestone 0 merged** (#1): design, ADRs 0001–0007 and benchmarks carried over; lesson 00.
- **Milestone 1 merged** (#2): `quantic_agent/cli.py`, `quantic_agent/tools.py`; lesson 01.
- **Milestone 2 merged** (#3): `quantic_agent/llm.py` (httpx + Pydantic), `--check`/`--ask`,
  `quantic-bench`. Tests run against a real local fake server (`tests/conftest.py`) answering with
  `tests/fixtures/ollama/`; lesson 02.
- **Milestone 3 in review** (branch `m3-errors-you-can-tell-apart`): `LLMError` with subclasses
  `ServerUnavailableError` (refused, reset, dropped, no route; not DNS, not timeouts), `APIError`
  (status, message) and `ModelNotFoundError(APIError)`. `quantic-agent` exits 3 when unavailable;
  `quantic-bench` stops and keeps what it measured. The dead address in tests is `127.0.0.1:1`;
  lesson 03.
- design.md's "As built in Go" notes link to quantic-agent-go's code: turn each into an "As built"
  note about this repository's code as its milestone is ported (§3.3's calculators done). The
  runbook's run history is the Go version's until milestones 7 and 8 port it.
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

1. **Port milestones 4–8 from quantic-agent-go**, in order, one PR each, each with its lesson and
   walkthrough: 4 timeouts and cancellation, 5 the first
   tool (MCP client, schemas from types), 6 provenance, 7 SQLite, 8 the research loop (the Go
   version's findings PRs included: numbers in words, today's date, `no_data`).
2. **Milestone 9 — the worker pool**: serialised GPU, parallel I/O. The Week Ahead needs
   `get_stock` per company (amounts, yields), 20–40 calls paced under Quantic's 60/min limit.
3. `num_ctx` is Ollama's default 4096 for chat; fine for one calendar, not for the Week Ahead's data.

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
- The server's code is in `../quantic` on `main` (`lib/quantic_web/mcp/`). Fetch first: the local
  checkout lagged `origin/main` by three months.

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
- Cancelling a request mid-generation stops the GPU work within about a second; cancelling while a
  model is loading aborts the load. Deadlines must allow for a cold start (up to ~31s measured).

## SQLite, learned the hard way

- Per-connection settings (`foreign_keys`, `busy_timeout`, WAL) must apply to every connection.
- Migrating from several processes at once collides; a file lock (`flock`) around migrating fixes it.
- Adding a value to a `CHECK` constraint means rebuilding the table, with foreign keys off for that
  connection, outside a transaction (SQLite's documented recipe).
