# quantic-agent

A local agent that drafts data-grounded content and data-quality reports for
[Quantic](https://quantic.finance), using local models through Ollama. Every figure traces to a real
tool call; nothing ships without a human.

> **Status: milestone 3.** The design, decisions and benchmarks are carried over from the Go version.
> The agent reaches the local model server: `quantic-agent --check` reports the server and its models,
> `--ask` sends one prompt, and `quantic-bench` measures speed and GPU residency per model. Failures
> come in kinds a caller can tell apart: a stopped Ollama exits with status 3, safe to retry. Every
> run has a deadline (`--timeout`), and Ctrl-C or `SIGTERM` cancels the request in flight, which frees
> the GPU. `--research` answers a question with the local model and Quantic's MCP server, through
> the official SDK, tracing each tool call; `quantic-evaltools` measures how reliably models call
> tools. Every research answer is checked: a number or date no tool returned is reported, and the
> run exits 4. Every research run is stored in SQLite with each tool call as it happens (`--runs`,
> `--run N` re-checks one). The deterministic calculators for derived figures are in, with their tests.
> `--week-ahead` writes the Dividend Week Ahead in seven locales into a folder: data from the tools,
> prose with no figures in it, each translation checked. `--pr N` opens a pull request with a post's
> files on Quantic's repository, as a GitHub App, and `--sync` records merges as approvals; the agent
> never merges. The agent was first built in Go, up to milestone 8:
> [quantic-agent-go](https://github.com/fleveque/quantic-agent-go), now archived. It continues here
> in Python, chosen for what comes next: retrieval, document handling, model evaluation and
> experimenting with local models ([decision 0007](docs/decisions/0007-continue-in-python.md)).
> Milestones 0–8 are ported first, one pull request each, with a lesson that compares Python with Go.

---

## The one rule

> **The LLM never invents a number.**

Every yield, valuation, dividend amount and price change in generated output must trace back to a
recorded tool call against Quantic's real data. The model is allowed to *write prose*, *summarise*,
*spot patterns* and *write code*. It is never allowed to recall a figure from its training data.

This is enforced, not asked for in a prompt. Every draft carries a **provenance manifest** of the
tool calls that fed it, and a validator rejects any draft containing a figure that doesn't appear in
that manifest. A draft that fails provenance never reaches the review queue.

The second rule follows from the first: **nothing ships without a human.** No auto-merge to `main`,
no auto-posting anywhere. Output lands as a PR or a `pending_review` row, and waits.

## Architecture

```
                    ┌───── RESEARCH (agentic, bounded) ─────┐
   ┌──────────┐     │                                       │
   │ local LLM│◄───►│   model ⇄ read-only Quantic tools  ×N  │──► manifest
   │ Qwen·GPU │     │   budgets: calls · time · tokens       │       │
   └──────────┘     └───────────────────────────────────────┘       │
        ▲                                                            ▼
        │                                              ┌──────────────────────┐
        └──────────────────────────────────────────────│  WRITE (no tools)    │
                                                       │  prose from manifest │
                                                       └──────────┬───────────┘
                                                                  ▼
                                                       ┌──────────────────────┐
                                                       │ PROVENANCE VALIDATOR │
                                                       │ every number traced  │
                                                       └──────────┬───────────┘
                                                    ┌─────────────┴────────────┐
                                                    ▼                          ▼
                                            ┌──────────────┐          ┌────────────────┐
                                            │ SQLite queue │          │  GitHub PR     │
                                            │ + 7 locales  │          │  (never merged)│
                                            └──────┬───────┘          └───────┬────────┘
                                                   └───────────┬──────────────┘
                                                               ▼
                                                       human review — always
```

**Research is a real agentic loop**: the model picks tools and follows threads, bounded by
call/time/token budgets over a read-only allowlist. **Writing has no tools at all**: it receives the
accumulated manifest and nothing else, so it cannot wander into invention. Delivery lives outside the
loop entirely. See [decision 0001](docs/decisions/0001-agentic-research-constrained-writing.md) and
the [design](docs/design.md).

## Roadmap

Each milestone ships working code *and* a lesson in [`docs/lessons`](docs/lessons), comparing
Python with Go. Milestones 0–8 are ports of the Go version; the lessons say what changed and why.

| # | Milestone | Python ground covered |
|---|---|---|
| 0 | Layout and design | `pyproject.toml`, `uv`, packages and `sys.path`, `src/` layout, privacy by convention |
| 1 | First code and tests | modules, functions and types, `pytest`, a command entry point |
| 2 | The Ollama client | `httpx`, Pydantic models, JSON at a boundary |
| 3 | Errors the agent can tell apart | exceptions, hierarchies, chaining |
| 4 | Timeouts and cancellation | `async`/`await`, `asyncio.timeout`, cancellation, signals |
| 5 | The first tool: MCP client, schemas from types | the MCP SDK, JSON Schema from Pydantic, `typing.Protocol`, exception groups |
| 6 | Provenance | `re` with named groups, structural `match`, recursive type aliases |
| 7 | SQLite: runs, drafts, audit log | `sqlite3`, migrations, transactions, file locks |
| 8 | The research loop: budgets, retries, phases, resume | Alembic, mutable arguments, backoff with jitter, an HTTP transport |
| 9 | Worker pool: serialised GPU, parallel I/O | `TaskGroup`, semaphores, a rate limiter, measuring a bottleneck |
| 10 | Retrieval: embeddings, brute-force cosine, style memory | `array`, `math.sumprod`, `heapq`, vectors as BLOBs, measuring retrieval |
| 11 | Week Ahead end to end, 7 locales, translation validator | dates, YAML, package data |
| 12 | GitHub PR flow *(you are here)* | a GitHub client, auth |
| 13 | Ship it: logging, a systemd unit | structured logging, packaging an application |

## Working on this

`main` is protected: every change goes through a pull request, and CI must pass before merge.

Everything runs through [uv](https://docs.astral.sh/uv/), which installs the Python version the
project asks for. The checks CI runs, locally:

```sh
uv sync                      # Python 3.14, the tools, and the agent (editable) into .venv
uv run ruff format --check .
uv run ruff check .
uv run pyright               # strict
uv run pytest
uv run quantic-agent --version
uv run quantic-agent --check                 # is the model server up, and what does it have?
uv run quantic-agent --ask "say hello"       # one prompt, one reply
uv run quantic-agent --research "What goes ex-dividend this week?"   # model + Quantic's tools
uv run quantic-agent --research "..." --research "..."   # several questions at once
uv run quantic-agent --runs                  # past runs; --run N shows one, --resume N carries it on
uv run quantic-agent --approve N             # a reviewed answer becomes style memory
uv run quantic-agent --week-ahead --out DIR  # next week's post, one file per locale
uv run quantic-agent --pr N                  # a pull request with run N's post, for review
uv run quantic-agent --sync                  # merged pull requests approve, closed ones reject
uv run quantic-bench                         # tokens/second and GPU residency per model
uv run quantic-evaltools                     # how reliably each model calls tools
uv run quantic-evalrecall                    # how well each embedding model finds an example
```

`--ollama` / `OLLAMA_HOST` and `--model` / `QUANTIC_MODEL` choose the server and the model; nothing
about the machine is baked in.

CI also checks that relative links in the docs resolve. Setting up the machine the agent runs on is in
the [runbook](docs/target-machine.md).

## Documents

- [`docs/design.md`](docs/design.md): architecture, provenance, retrieval, translation, open questions
- [`docs/content.md`](docs/content.md): what gets published, cadence, locales, the registration gate
- [`docs/rendering.md`](docs/rendering.md): the format contract, typed data plus prose rendered by Quantic
- [`docs/target-machine.md`](docs/target-machine.md): runbook for the desktop the agent runs on
- [`docs/decisions/`](docs/decisions/README.md): architecture decision records
- [`docs/benchmarks/`](docs/benchmarks/README.md): measurements behind the model decisions
- [`docs/lessons/`](docs/lessons/README.md): the Python lessons

## License

[MIT](LICENSE). The agent is MIT; Quantic itself is private and proprietary. This repo only talks to it.
