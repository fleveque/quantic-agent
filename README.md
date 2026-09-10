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

The split is the whole design: **research is a real agentic loop** where the model picks tools and
follows threads, bounded by call/time/token budgets over a read-only allowlist. **Writing has no tools
at all** — it receives the accumulated manifest and nothing else, so it cannot wander into invention.
Delivery tools live outside the loop entirely. See
[decision 0001](docs/decisions/0001-agentic-research-constrained-writing.md).

### Components

| Package | Responsibility |
|---|---|
| `cmd/agent` | Entrypoint, flag/config parsing, daemon loop and graceful shutdown |
| `internal/llm` | Local model client (Ollama HTTP API), tool-call schema, structured-output decoding |
| `internal/mcp` | Client for Quantic's MCP server — the only source of financial facts |
| `internal/agent` | The research loop: tool dispatch, budget accounting, retries, phase state machine |
| `internal/tools` | Tool registry and JSON schemas generated from Go structs; read-only allowlist vs delivery tools |
| `internal/rag` | Embeddings in SQLite BLOBs, brute-force cosine similarity, style memory over approved drafts |
| `internal/provenance` | Records every tool call; validates that generated numbers trace back to one |
| `internal/tasks` | Task definitions (Week Ahead, raise/cut notes, valuation write-up, data QA) and schedules |
| `internal/i18n` | Translation pass and the locale-aware translation validator across 7 locales |
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

## What it publishes

The flagship format, built and proved first:

**The Dividend Week Ahead** — weekly, ~600 words. *N companies go ex-dividend this week* (table:
ticker, ex-date, amount, yield), *raises declared* with old → new, *cuts and at-risk flags* from the
existing dividend-safety work, *radar movers*, and one short "what to watch" paragraph that is the
only freely written prose and contains no figures. Published to `/insights` across all seven locales
from one human review, plus a social variant sharing the same manifest.

Then, in order: **raise & cut notes** (event-driven, a raise is news the day it's declared),
**valuation deep-dives** (evergreen, where retrieval over filings earns its place), and a **monthly
dividend health report**.

Deliberately weekly, not daily — Google's scaled-content-abuse policy targets bulk machine-generated
pages, and quantic.es is a real domain with ranking pages already earning traffic. Full reasoning,
formats and the registration-gate design in the [content plan](docs/content.md).

Alongside the content: **data QA** (nulls, outliers, impossible dates across the instrument universe →
GitHub issues or small mechanical PRs) and **low-risk code work** (refactors, tests, fixtures, docs).
*Never:* business logic, financial calculations, or anything touching real user money.

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
| 0 | Repo, design, decisions | — *(you are here)* |
| 1 | Hello, module: layout, `cmd/` vs `internal/`, first test | modules, packages, visibility, `go test` |
| 2 | Ollama client: send a prompt, decode the response | structs, JSON tags, interfaces, `net/http` |
| 3 | Error handling across the LLM boundary | `error` values, wrapping, `errors.Is/As`, sentinels |
| 4 | Timeouts and cancellation for slow generations | `context`, deadlines, graceful shutdown |
| 5 | First real tool: `dividend_calendar` end to end | schema from structs, reflection, MCP auth |
| 6 | Provenance validator + table-driven tests | slices/maps, `testing`, `httptest`, fakes |
| 7 | SQLite: runs, drafts, audit log | `database/sql`, migrations, transactions |
| 8 | **The agentic research loop** — dispatch, budgets, retries | state machines, backoff, `context` in a loop |
| 9 | Worker pool: serialised GPU, parallel I/O | goroutines, channels, `sync`, `errgroup`, semaphores |
| 10 | **Retrieval**: embeddings, brute-force cosine, style memory | `[]float32` math, `testing.B`, BLOBs |
| 11 | Week Ahead end to end, 7 locales, translation validator | time, `embed`, `x/text`, locale number formats |
| 12 | GitHub PR flow | `go-github`, auth, third-party module ergonomics |
| 13 | Ship it: binary, `log/slog`, systemd unit | build flags, cross-compilation, structured logging |

## Lessons

Written as I go, in [`docs/lessons`](docs/lessons). They're notes from someone coming to Go from
Elixir and Ruby — what surprised me, what I got wrong first, and why Go does it that way.

## Documents

- [`docs/design.md`](docs/design.md) — architecture, provenance, retrieval, translation, open questions
- [`docs/content.md`](docs/content.md) — what gets published, cadence, locales, the registration gate
- [`docs/decisions/`](docs/decisions) — architecture decision records
- [`docs/lessons/`](docs/lessons) — the Go lessons

## Licence

[MIT](LICENSE). The agent is MIT; Quantic itself is private and proprietary — this repo only talks to it.
