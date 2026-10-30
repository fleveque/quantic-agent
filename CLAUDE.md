# quantic-agent — notes for Claude Code

A local agent that drafts data-grounded content for Quantic using local models through Ollama, in
Python. It is also how the author, who writes Elixir and Ruby daily and has just learned Go, comes to
understand Python. The first version was Go, up to milestone 8: `../quantic-agent-go` (archived,
`github.com/fleveque/quantic-agent-go`). Its design, ADRs, benchmarks, fixtures and lessons are the
starting point here.

## Status — 2026-10-14

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
- **Milestone 12 merged** (#13, ADR 0014): `--pr N` and `--sync`. The author chose: a GitHub App
  (`quantic-agent-fleveque`, installed on `fleveque/quantic` only); PRs on the Quantic repo (path
  `priv/insights/`, `--repo-path`); every ready locale, reviewed by the author; `--sync` (merged =
  approved, closed = rejected). Quantic's `main` can't be protected (private repo, free plan), so the
  agent's guard plus a deploy check (quantic#486). `quantic_agent/github.py`: App JWT (PyJWT, RS256)
  → installation token, cached; the only ref write is creating `refs/heads/agent/...`; no PATCH, PUT
  or DELETE. `quantic_agent/publish.py` builds branch, files and description from the run as stored.
  Migration 0006 (`pull_requests`, one per run, one open per week). Settings:
  `QUANTIC_AGENT_GITHUB_APP_ID`, key file `~/.config/quantic-agent/github-app.pem` (refused unless
  600), `QUANTIC_AGENT_REPO`; runbook §8b. First real PR: quantic#487, closed, synced as rejected.
  The Week Ahead question says how many days away Sunday is (from a Friday the 9B asked for 7);
  lesson 12.
- **Default model, 2026-10-09** (branch `week-ahead-two`, decision 0005's update): Qwen3.8-27B
  `UD-IQ3_S` replaces `qwen3.5:9b`, chosen on the agent's work
  (`docs/benchmarks/2026-10-09-models/`): 20/20 Week Aheads against ~24/35, better research
  (evaltools 48/50 vs 45/50; provenance 12/15 vs 8/15). 14GB, 86% on the GPU, 102–174s per Week
  Ahead; `--timeout` default 600s. The author: background work can be slow. Prompt rewordings for
  "two" made it worse and weren't merged.
- **The Week Ahead's new data, 2026-10-14** (branch `week-ahead-new-data`, ADR 0013's update), after
  quantic#490/#491: `dividend_rate`, `currency`, `dividend_yield` (the calendar's percentage / 100,
  `check_data(percentages=...)`), `pay_date`; `earnings` (the week only) and `dividend_changes` (7
  days). The author chose: **code calls `earnings_calendar` and `dividend_changes`**
  (`weekahead.look_up`), after research is known complete, not the model (up to ~30 KB of earnings
  in season). Files at `<out or priv/insights>/<ISO year>/week-ahead-WNN/`. No lesson (like #14).
  Real runs: `docs/benchmarks/2026-10-14-week-ahead-data/`, 3/3, all files pass Quantic's checks.
- The week-ahead CLI tests pin the run's start date: the PR tests took the week from the real
  clock and failed on `main` from Monday 2026-10-12.
- **Milestone 13 merged** (#18, ADR 0015): `--weekly`, the scheduled job: `--sync`, then
  next week's post (a week with any pull request, open/merged/closed, is done; a stopped run is
  resumed; none, one starts), then `--pr`. Idempotent. `gpu.py`: `nvidia-smi` total less Ollama's
  runners (`llama-server` under Ollama's path); over 4096 MiB (`--gpu-max-others`) exit 3.
  `logs.py`: stdlib logging; terminal output unchanged; under systemd (`JOURNAL_STREAM` = stderr's
  dev:inode) `<N>` priority prefix + `key=value` fields. `contrib/systemd/` user service + timer
  (Sun 07:00, Persistent, Restart on exit 3 every 30min for 12h, SuccessExitStatus 4 5 6,
  PYTHONUNBUFFERED). The author chose all four. The first real `--weekly` opened a duplicate PR
  (quantic#494, closed) by taking the week's newest answered run: fixed, tested. A oneshot has no
  start timeout by default (systemd.service(5)); lesson 13.
- **Milestone 14 merged** (#21, ADR 0016): the reviewer's corrections captured.
  The author chose capture only (glossary and retrieval later). `--sync` reads a merged pull
  request's files back from its merge commit (contents API, GET; `github.Client.file`) and
  `corrections.compare` stores each changed section (prose by key, `data`, `frontmatter`, or the
  whole `file`) with the drafted and published text; migration 0007 (`corrections`,
  `pull_requests.merge_commit`, set in the same transaction: NULL = not read yet, so old merges
  and failed reads are read on the next sync). `--run N` shows word diffs (`difflib`; not minimal,
  unlike git's Myers). Real quantic#492: 8 sections in 6 locales, English untouched; lesson 14.
  Reinstalled 2026-10-14; the real database is at 0007 and has quantic#492's corrections.
- **Milestone 15** (branch `m15-prose-checks`, ADR 0017): wording rules for the English prose
  (`wording.py`: audience, advice, market, count, duration; whole words, any case). A match is a
  `provenance.Finding` of `Kind.PHRASE` (value = the rule), sent back to the writer like a figure
  (`weekahead.check_prose`, `_again`), held after 3 attempts (exit 4), re-checked by `--run N`.
  Rules come from reading their matches in 120 real 27B writings
  (`docs/benchmarks/2026-10-14-prose-checks/`): 22 of 60 baseline writings had such wording; with
  the check 60/60 published, 33/23/4 attempts, 13 s vs 9 s. Each measurement round found new
  wordings ("readers should note"): it's a list, not a meaning check. English only; lesson 15.
- **`--week YYYY-Www`, 2026-10-26** (branch `week-option`, no lesson): `--week-ahead` for a
  given week, starting today or later (the calendar counts from today, so a week already under
  way would miss its first days). Migration 0008 records every new Week Ahead run's week
  (`runs.week_start`); `weekahead.week_of(run)` is the one place a run's week is read, and runs
  recorded before keep the week after their start date. Why: the W43 and W44 posts had dates
  Quantic's demo invented (quantic#506), and W44 had to be written on its own Monday.
- **Code looks the companies up, 2026-10-26** (branch `code-looks-up`, ADR 0013's second update):
  a Week Ahead's research offers the model only `dividend_calendar`; code calls `get_stock` for
  each of the week's companies (`weekahead.look_ups`). With real ex-dates W44 has 31, more than
  the call budget and the 32k context held. The author chose this; speed doesn't matter (minutes,
  not hours). A larger `--num-ctx` (the 27B supports 262,144) is unmeasured.
- **Tests never see the machine's settings** (2026-10-26): with the GitHub App's settings
  exported in the shell and its key at the default path, the `--weekly` tests that don't set up
  the fake GitHub opened a real pull request (quantic#507, closed). The autouse fixture now
  removes every `QUANTIC_*`/`OLLAMA_*` variable and points `XDG_CONFIG_HOME` at the test's own
  directory. Before running tests with such a shell, check `tests/conftest.py` still does.
- **The X post draft, 2026-10-26** (branch `x-post-draft`, ADR 0018, no lesson): `xpost.draft`
  builds the week's X post from the data block (a fixed template; cashtags for the two US listings
  with the longest streaks; raises and cuts of 1% or more), `x_length` counts as X does (link 23,
  emoji 2) and lines are dropped in order to fit 280. It goes in the pull request's description;
  the author posts it. English, quantic.finance link.
- **The X posts experiment, 2026-10-28** (#26, `docs/benchmarks/2026-10-28-x-posts/`): code
  gathering facts beats the model researching; field meanings in the writer's prompt took wrong
  claims from 19/95 posts to 2/96; a 27B verifier caught 9/11 major errors given the post's own
  facts, 0 given all of them. The author posted a Claude-written Nike post on X (@quantic_es).
- **Milestone 16 merged** (#27, ADR 0019): `--daily`, weekdays 07:30 (its own units,
  `contrib/systemd/quantic-agent-daily.*`). `quantic_agent/daily.py`: code makes the day's calls
  (`dividend_changes` 3, `dividend_calendar` 5, one `screen_stocks`), picks one company per angle
  (change, ex-dividend, yield) not proposed in 7 days, looks up until one is accepted (a cut next to
  a running streak is rejected as contradictory data), computes facts (copied, checked by
  `check_data`; derived, incl. `why_the_yield_is_high` when the price explains most), units guard
  (BAE: pounds vs pence). The model writes 3 versions per company; `check_version` traces figures to
  the company's own facts and checks wording (names masked, "price" allowed), causes, "trades at",
  glued units, emojis at paragraph starts, cashtag, length with the link. One issue a day on Quantic
  (create and read only; Issues: write on the App, the author must add it); `--sync` reads the ticks.
  Migration 0009 (`proposals`, `issues`). `wording.check(names=, allow=)` fixes "Best Buy" as
  advice in the Week Ahead too. Project skill `.claude/skills/review-posts/`. First real run: 51 s,
  BAE, Realty Income, Nike, 8 versions; lesson 16.
- **A change's basis, 2026-10-29** (branch `change-basis`, after quantic#526): Quantic's
  `dividend_changes` rows carry `basis`, "annual" (a rate) or "payment" (a semi-annual payer's
  payment against the same one a year earlier). The Week Ahead's data writes `basis` only for
  payment rows (`exclude_if`), so annual rows and old runs trace as before; the daily facts name
  them `new_payment` / `same_payment_a_year_earlier`. Absent = annual (Quantic before #526).
- **Ex-dividend months, 2026-10-30** (branch `ex-months`, after quantic#533): Quantic's
  `payment_months` have always been ex-dividend months, which is how "Hitachi pays in March" was
  written (quantic#521). The daily facts are now `goes_ex_dividend_in` / `next_ex_dividend_month`,
  and `pays_in` / `next_payment_month` only when `payment_months_basis` says real payments.
  Absent = ex-dividend (Quantic before #533).
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

0. **Daily posts on, 2026-10-29**: Issues: Read and write added to `quantic-agent-fleveque` and
   accepted; reinstalled from `main` after #27's merge; `quantic-agent-daily.timer` enabled. The
   first run is Friday 2026-10-30 07:30: check its journal and its issue then. The data issues
   from the experiment were filed and fixed on Quantic (#524–#531), except real pay months
   (quantic#521, in progress). The first real issue, quantic#515, was reviewed on the
   issue: Hitachi's "annual rate" was its interim times two, Realty Income's streak 28 for 31+.
   The author chose: `review-posts` always comments on the issue and checks the data against
   outside sources. **ADR 0020 is proposed, not decided**: capture what was posted (a `posted SYM
   version N` comment with the text) and the review; its open questions are the author's.

1. **Installed and on, 2026-10-14**: `uv tool install` from `main` after #18's merge;
   `~/.config/quantic-agent/env` (App ID, `QUANTIC_AGENT_REPO`, `QUANTIC_AGENT_OUT=~/insights`,
   mode 600); the units in `~/.config/systemd/user/`; `quantic-agent.timer` enabled. A manual start
   synced and exited 0. Sunday 2026-10-18 targets 2026-W43, already published (quantic#492), so it
   only syncs; the first real write is Sunday 2026-10-25, for 2026-W44. Check its journal and its
   pull request then. After merging agent changes: `uv tool install --reinstall
   git+https://github.com/fleveque/quantic-agent`. The author suggested Claude review a PR's
   translations and claims before merging; it did for quantic#492 (a review with suggested
   changes), not yet a standing decision. Quantic's `/insights` renders merged posts.
2. Ollama's truncation is invisible in its replies (only its log says `truncating input prompt`);
   detecting it from the agent is open.
3. Seen in real runs, not caught: counts of a filtered subset ("four companies") are flagged though
   right; a wrong statement whose figures all trace ("no companies in the next 10 days") passes; the
   9B sometimes reasons out loud in an answer despite `think: false`.
4. Prose that's wrong without a figure, seen in real runs and not caught: "recent acceleration"
   for a slowing dividend, "safety remains strong" or "each name carries a safe profile" for one
   on watch, false growth comparisons ("Coca-Cola's recent growth outpaced its average"). A claim
   check against the data (direction words vs `growth_ttm`/`cagr_5y`, safety words vs `safety`) is
   open. Milestone 15 checks wording, not claims. Numbers in words are recognised in English only,
   so a translation's "dues" passes, and the wording rules don't read translations. The 27B's
   Catalan still has visible errors (design open question 12). With the 9B, the prose step alone
   held 1 of 40 writings but 7 of 35 inside full runs; the difference wasn't found.
5. Ratios in get_stock (`cagr_5y` 0.1023) written as percentages ("10.23%") are flagged as
   converted figures, correctly by N1; a percentage calculator tool would let them through.
6. **Learning from the reviewer's corrections** (raised 2026-10-14 reviewing quantic#492). Capture
   is milestone 14: `--sync` stores each section changed before merging. On quantic#492 the 27B's
   translations had errors no check sees: Catalan "divisió" for dividend and "per davant" (ahead)
   for behind, Italian "dello stesso periodo" for "in the same week", Portuguese "lucros"
   (profits) for results. Still open, the author's to choose: a per-locale glossary in
   `locales.json` with a check that holds a known-wrong term (the only option that guarantees
   anything), and past corrections retrieved as examples for the translator (RAG, design §3.4's
   style memory extended to Week Aheads). §3.4's other planned uses have no milestone yet: don't-repeat-yourself (what was
   recently written about a ticker) and filings and news text (open questions 7 and 11).

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
