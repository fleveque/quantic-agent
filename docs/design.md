# quantic-agent — design

Living document. Records decisions, the reasoning behind them, and the questions still open.
Originates from a Spanish-language idea sketch (`quantic-local-agent-idea.md`); this is the refined,
English version that the implementation follows.

---

## 1. Problem

Quantic (quantic.es) is a dividend-portfolio tracker: Elixir/Phoenix monolith, real users, real
money decisions. Two recurring jobs are repetitive, LLM-shaped, and intolerant of hallucination:

1. **Content.** Data-grounded write-ups — valuations, dividend digests, stock comparisons — that feed
   SEO and community channels.
2. **Data quality.** Watching a large instrument universe for nulls, outliers, impossible dates and
   suspicious dividend histories.

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

## 3. Architecture

### 3.1 Data flow

A task runs as a pipeline, not as an open-ended agent loop:

```
schedule → plan → fetch (tools) → generate (LLM) → validate (provenance) → deliver (PR | queue)
```

The deliberate constraint: **the model does not decide which data to fetch on its own for content
tasks.** A task declares its data dependencies up front; the agent fetches them; the model receives
facts and writes prose. This trades autonomy for the N1 guarantee, and it is the right trade for
content. Open-ended tool-calling loops are reserved for the QA and code tasks, where the output is a
report or a diff that a human reads anyway.

### 3.2 Provenance

The hard part, and the most interesting piece of engineering here.

Each task run accumulates a **manifest**: an ordered list of `{tool, args, response, timestamp}`
records. After generation, the validator:

1. Extracts every numeric token from the draft (currency amounts, percentages, ratios, dates, counts).
2. Normalises them (thousands separators, currency symbols, decimal commas vs points, `1.2M` forms).
3. Checks each against the set of values present in the manifest's responses.
4. Rejects the draft if any token is unaccounted for.

**Known hard case: derived figures.** "Yield rose from 3.1% to 3.4%, a 0.3pp increase" — the `0.3` is
correct but appears in no tool response. Options under consideration:

- **(a) Ban derivation.** The prompt forbids arithmetic; any derived figure must be computed by a tool.
  Add small deterministic Go "calculator" tools (`pct_change`, `diff`) that the model calls, so
  derived numbers enter the manifest legitimately. *Currently favoured — it keeps the invariant total
  and the tools are trivial to write and test.*
- **(b) Allow a whitelist of derivations** the validator can recompute and verify itself.
- **(c) Flag-not-reject:** unaccounted numbers downgrade the draft to `needs_close_review` instead of
  rejecting it.

Start with (a), fall back to (c) if it proves too strict in practice.

**Second hard case: false positives.** Years, list positions, "top 10", version numbers. Needs a
small ignore-list and a notion of "numbers that are not claims". Table-driven tests will earn their
keep here.

### 3.3 Concurrency model

The interesting shape: **one GPU, many network calls.**

- LLM inference is a serialised resource — a semaphore of capacity 1 (configurable) around the model
  client. Queued tasks wait; they do not thrash the GPU.
- Tool/data fetches are I/O-bound and fan out per task via `errgroup`, bounded so Quantic isn't
  hammered.
- A `context` per task carries the deadline and cancellation, threading through both.
- The daemon is opportunistic: the machine is not always on. State is checkpointed in SQLite after
  each pipeline stage so an interrupted run resumes rather than restarts.

### 3.4 Storage

SQLite via `modernc.org/sqlite` (pure Go, no cgo — preserves the static-binary property).

Tables, roughly:

- `tasks` — id, kind, params, state, scheduled_for, started_at, finished_at, error
- `drafts` — id, task_id, content, state (`pending_review` | `approved` | `rejected` | `published`), created_at
- `tool_calls` — id, task_id, tool, args, response, duration_ms, called_at *(the audit log, N3)*
- `manifests` — draft_id → tool_call_ids *(provenance link, N1)*

Retention: `tool_calls` responses can be large; plan a compaction policy before this becomes a problem.

### 3.5 Delivery

- **Review queue** — SQLite rows. A minimal read-only HTTP view (`net/http` + `html/template`, no JS
  framework) is probably worth it once there are more than a handful of drafts. Deliberately not a
  product.
- **Pull requests** — `go-github`: create branch, commit file(s), open PR against the private Quantic
  repo. The token is scoped to allow branch and PR creation and nothing more. `main` is protected
  independently, so a bug in the agent cannot merge.
- **Issues** — for data-QA findings where there's no mechanical fix.

## 4. Stack

| Concern | Choice | Reasoning |
|---|---|---|
| Inference server | Ollama | Simplest to operate; model management and a tool-calling API out of the box. `llama.cpp server` remains the escape hatch for finer control (see [llm-kit](https://github.com/fleveque/llm-kit)). |
| Primary model | Qwen2.5-14B-Instruct (Q4/Q5) | Fits 16GB VRAM with usable context; real tool-calling support. |
| Fast model | Qwen3-8B | Latency-sensitive tasks; "thinking" mode useful for QA reasoning. |
| Heavy model | 32B @ Q3, partial RAM offload | Occasional batch work where slow is acceptable. |
| Model I/O | JSON-schema-constrained decoding | Local models are flakier at native tool-calling than frontier models; constrained output is the reliable floor, native tool-calling an optimisation. |
| Persistence | `modernc.org/sqlite` | Pure Go, no cgo. |
| GitHub | `go-github` | Mature, well-typed. |
| Logging | `log/slog` | Stdlib structured logging; feeds the audit requirement. |
| Config | YAML + env, flags for overrides | Secrets via env only, never committed. |

**Hardware:** 64GB RAM, RTX 4070 Ti Super (16GB VRAM).

## 5. Open questions

1. **MCP authentication from a headless daemon.** Quantic's MCP server uses OAuth, which assumes an
   interactive consent flow. A local daemon needs a non-interactive credential. Options: a
   long-lived service token scoped to read-only tools; a direct internal API path that bypasses MCP;
   or a one-time OAuth grant with a stored refresh token. *Needs deciding before milestone 5.*
2. **How do we know a draft is any good?** Provenance proves it isn't *wrong*; it doesn't prove it's
   *worth publishing*. Proposal: track human accept/reject rate per task kind in SQLite and treat it
   as the metric that matters. If a task kind sits below some accept rate, the task is broken, not
   the reviewer.
3. **Idempotency.** Re-running after a crash must not produce a duplicate weekly digest. Needs a
   natural key per task run (kind + period) and an upsert.
4. **Scheduling.** Internal ticker in the daemon vs. systemd timers invoking a one-shot binary. The
   one-shot model is simpler and more crash-tolerant; the daemon model makes the worker pool
   meaningful. Possibly both: daemon for continuous work, one-shot for scheduled tasks.
5. **Prompt storage.** Prompts are code and should be reviewed like code — versioned in the repo via
   `embed`, not stored in the database. But they must contain no Quantic-internal content (N4).
6. **Cost of being wrong in public.** The repo is public; the Quantic repo it opens PRs against is
   private. Confirm nothing in agent logs, test fixtures or example output leaks private schema or
   user data before each commit.

## 6. Explicit non-goals

- Not a general-purpose agent framework. It does a handful of known jobs well.
- Not a product. No multi-user support, no auth beyond the local machine, no hosting.
- Not real-time. Everything here is batch work that tolerates minutes of latency.
- Not touching business logic, financial calculations, or anything involving real user money.
