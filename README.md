# quantic-agent

A local, autonomous content and QA agent for [Quantic](https://quantic.es), written in Go.

It runs on my own hardware, drives a **local LLM** (no API bills, no data leaving the machine),
pulls **real financial data** from Quantic's MCP server, and turns it into draft content, data-quality
reports and small code changes — delivered as **pull requests and review-queue entries, never as
anything published automatically**.

> **Status: day 0.** The repo exists, the design is written, no Go code yet. This is deliberate — the
> project doubles as my way of learning Go in public, so the commit history *is* the learning record.
> See the [roadmap](#roadmap) for where it's going and [docs/lessons](docs/lessons) for what each step taught me.

---

## The one rule

> **The LLM never invents a number.**

Every yield, valuation, dividend amount and price change in generated output must trace back to a
recorded tool call against Quantic's real data. The model is allowed to *write prose*, *summarise*,
*spot patterns* and *write code*. It is never allowed to recall a figure from its training data.

This isn't a guideline in a prompt — it's enforced. Every draft the agent produces carries a
**provenance manifest** of the tool calls that fed it, and a validator rejects any draft containing a
numeric token that doesn't appear in that manifest. A draft that fails provenance never reaches the
review queue.

The second rule follows from the first: **nothing ships without a human.** No auto-merge to `main`,
no auto-posting to Telegram or Reddit. Output lands as a PR or a `pending_review` row, and waits.

---

## Why this exists

Quantic is a dividend-portfolio tracker (Elixir/Phoenix, real users, real money decisions). It needs a
steady stream of data-grounded content — valuation write-ups, dividend digests, stock comparisons — and
it needs someone watching for bad data in ~thousands of instruments. Both jobs are repetitive, both
benefit from an LLM, and neither can tolerate hallucinated figures.

A local model on my own GPU makes the economics work: the agent can run all day, burn as many tokens as
it likes, and never send a user's portfolio to a third party.

## Why Go

Honest answer: **I want to learn Go**, and this is a problem shaped exactly like Go's strengths.

- **Concurrency that matters.** One GPU means LLM inference is a strictly serialised resource, while
  tool calls against Quantic are I/O-bound and want to fan out. That tension — a semaphore of one
  around the model, an `errgroup` around the data fetches, `context` cancellation threading through
  both — is a real concurrency design, not a toy example.
- **Static types for an untyped boundary.** LLM tool-calling is JSON soup. Go's type system plus
  explicit schema definitions turn that boundary into something that fails loudly at the edge instead
  of silently three layers in.
- **A single static binary.** Drop it on the machine, point systemd at it, done. No runtime, no venv.
- **Mature libraries** for exactly this: `go-github`, `modernc.org/sqlite` (pure Go, no cgo),
  `log/slog`, and `net/http` good enough that an LLM client needs no framework.

I write Elixir and Ruby daily. Go's explicit error handling, structural interfaces and share-memory
concurrency are genuinely different models, which is the point.

---

## Architecture

```
┌──────────────┐      ┌──────────────────────────────────────┐      ┌─────────────┐
│ local LLM    │◄────►│           quantic-agent (Go)         │◄────►│ Quantic MCP │
│ Qwen · GPU   │ tool │  scheduler · worker pool · provenance │ data │ (real data) │
└──────────────┘ calls└──────────────────────────────────────┘      └─────────────┘
                                    │           │
                        drafts +    │           │  code changes
                        provenance  ▼           ▼
                              ┌──────────┐  ┌──────────────┐
                              │  SQLite  │  │  GitHub PR   │
                              │  review  │  │  (never      │
                              │  queue   │  │   merged)    │
                              └──────────┘  └──────────────┘
                                    │              │
                                    └──────┬───────┘
                                           ▼
                                   human review — always
```

### Components

| Package | Responsibility |
|---|---|
| `cmd/agent` | Entrypoint, flag/config parsing, daemon loop and graceful shutdown |
| `internal/llm` | Local model client (Ollama HTTP API), tool-call schema, structured-output decoding |
| `internal/mcp` | Client for Quantic's MCP server — the only source of financial facts |
| `internal/tools` | Tool registry exposed to the model: Quantic data tools + `create_pr` + `enqueue_for_review` |
| `internal/provenance` | Records every tool call; validates that generated numbers trace back to one |
| `internal/tasks` | Task definitions (weekly digest, valuation write-up, data QA) and their schedules |
| `internal/store` | SQLite: review queue, task history, full tool-call audit log |
| `internal/ghpr` | `go-github` helper: branch, commit, open PR — no push to `main`, ever |

### Stack decisions

- **Inference: Ollama** over raw `llama.cpp server`, for its tool-calling API and model management.
  (I already maintain [llm-kit](https://github.com/fleveque/llm-kit) for the llama.cpp path if I need
  more control later.)
- **Model: Qwen2.5-14B-Instruct** at Q4/Q5 — fits comfortably in 16GB VRAM with room for context, and
  has genuine tool-calling support. Fallback to Qwen3-8B for latency-sensitive tasks; 32B at Q3 with
  partial RAM offload for occasional heavy batch work.
- **Structured output over native tool-calling.** Local models are noticeably flakier at tool-calling
  than frontier models. The plan is to lean on JSON-schema-constrained decoding and treat native
  tool-calling as an optimisation, not a foundation.
- **SQLite via `modernc.org/sqlite`** — pure Go, no cgo, keeps the static-binary property.

### Hardware

Ryzen-class desktop, 64GB RAM, NVIDIA RTX 4070 Ti Super (16GB VRAM). The agent is designed to run
opportunistically: work while the machine is on, checkpoint state, resume cleanly.

---

## Use cases, ordered by how safe they are

1. **Data-grounded content drafts** — valuation analyses, dividend summaries, stock comparisons built
   from `get_valuation`, `dividend_calendar`, `screen_stocks`, `compare_stocks`. Output: a PR adding a
   markdown file. *(Safest: worst case is a bad draft nobody merges.)*
2. **Periodic digests** — what went ex-dividend, notable yield moves, new radar entries. Output: a
   review-queue row with text ready for Telegram/Reddit. *(A human presses publish.)*
3. **Data QA / enrichment** — nulls, outliers, impossible dates, suspicious dividend histories across
   the instrument universe. Output: GitHub issues, or small mechanical PRs against parsers/seeds.
4. **Low-risk code work** — mechanical refactors, new tests, fixture updates, docs.
   *Never:* business logic, financial calculations, or anything touching real user money.

---

## Guardrails

- No automatic merge to `main`. The agent's GitHub token is scoped to branch + PR creation.
- No automatic publishing to any external channel.
- Every numeric claim traces to a logged tool call, or the draft is rejected.
- Every tool call is logged with inputs and outputs, so any output can be audited after the fact.
- Token and wall-clock budgets per task; a runaway task is cancelled, not left running.
- No user portfolio data in logs, fixtures, prompts, or anything committed to this repo.

---

## Roadmap

Each milestone ships working code *and* a lesson write-up in [`docs/lessons`](docs/lessons), because
the point is learning Go, not just having an agent.

| # | Milestone | Go ground covered |
|---|---|---|
| 0 | Repo, design, README | — *(you are here)* |
| 1 | Hello, module: layout, `cmd/` vs `internal/`, first test | modules, packages, visibility, `go test` |
| 2 | Ollama client: send a prompt, decode the response | structs, JSON tags, interfaces, `net/http` |
| 3 | Error handling across the LLM boundary | `error` values, wrapping, `errors.Is/As`, sentinels |
| 4 | Timeouts and cancellation for slow generations | `context`, deadlines, graceful shutdown |
| 5 | First real tool: `dividend_calendar` end to end | encoding/json edge cases, schema definition |
| 6 | Provenance validator + table-driven tests | slices/maps, `testing`, `httptest`, fakes |
| 7 | SQLite review queue | `database/sql`, migrations, transactions |
| 8 | Worker pool: serialised GPU, parallel I/O | goroutines, channels, `sync`, `errgroup`, semaphores |
| 9 | Weekly digest task, scheduled | time, tickers, config, `embed` |
| 10 | GitHub PR flow | `go-github`, auth, third-party module ergonomics |
| 11 | Ship it: binary, `log/slog`, systemd unit | build flags, cross-compilation, structured logging |

## Lessons

Written as I go, in [`docs/lessons`](docs/lessons). They're notes from someone coming to Go from
Elixir and Ruby — what surprised me, what I got wrong first, and why Go does it that way.

## Design document

The full design and its open questions live in [`docs/design.md`](docs/design.md).

## Licence

[MIT](LICENSE). The agent is MIT; Quantic itself is private and proprietary — this repo only talks to it.
