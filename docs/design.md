# quantic-agent — design

Living document. Records decisions, the reasoning behind them, and the questions still open.
Originates from a Spanish-language idea sketch; this is the refined English version the
implementation follows.

Companion documents: [content plan](content.md) · [format & rendering](rendering.md) · [decisions](decisions/)

---

## 1. Problem

Quantic (quantic.finance) is a dividend-portfolio tracker: Elixir/Phoenix monolith, real users, real
money decisions. Two recurring jobs are repetitive, LLM-shaped, and intolerant of hallucination:

1. **Content.** Recurring, data-grounded publishing — a weekly dividend digest, raise/cut notes,
   valuation write-ups — across seven locales. See the [content plan](content.md).
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

**Hard case — false positives.** Years, list positions, "top 10", version numbers. Needs a small
ignore-list and a notion of "numbers that are not claims". Table-driven tests will earn their keep.

**Solved by the format contract.** Numbers live in typed frontmatter fields, not in prose (see
[rendering](rendering.md)), so validation is field-by-field comparison against the manifest rather
than regex extraction — and the prose is validated by the simpler assertion that it contains *no*
unaccounted numerics at all. This also removes the locale number-format problem entirely: figures
never appear in translated text.

### 3.4 Retrieval (RAG)

Retrieval does not make the model *learn* — the weights never change; it puts relevant text in the
context window at call time. Framed honestly, it earns its place in three specific spots:

1. **Style memory.** Retrieve past **approved** drafts so new output matches the house voice. The
   review queue *is* the corpus, so every human approval improves the next draft. This is the closest
   honest version of "the agent gets better at what it does", and it's a real feedback loop.
2. **Don't-repeat-yourself.** Retrieve what was recently written about a ticker so week 4's digest
   doesn't rehash week 1's angle.
3. **Filings and news text.** Chunked 10-K and press-release text makes valuation write-ups richer.

**The hard line: never retrieve a number.** Retrieved text is quotable as *language*; every figure
still comes from a live tool call. Vector stores have no freshness guarantee, and this is precisely
the crack hallucination would get back in through. Retrieved chunks enter the prompt but **not** the
provenance manifest — they can't authorise a number.

**Implementation: no vector database.** Embeddings stored as BLOBs in SQLite, brute-force cosine
similarity over `[]float32` in Go. At this corpus size — hundreds to low thousands of chunks — that's
microseconds and zero dependencies. It is the correct engineering choice at this scale, not a
shortcut; revisit only if the corpus grows two orders of magnitude. Embeddings from Ollama
(`nomic-embed-text` or a Qwen3 embedding model) alongside the chat model.

### 3.5 Translation

All seven Quantic locales are in scope from the first content milestone. The review burden is the
thing to design around: **the human reviews the source once; translations are machine-verified, not
human-reviewed.**

```
source draft → provenance ✓ → human review ✓ → canonical
                                    │
                                    ├→ translate (model, no tools) → translation validator → publish
                                    ├→ …                                                      ↘ hold
                                    └→ ×6 locales
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

### 3.6 Concurrency model

The interesting shape: **one GPU, many network calls.**

- LLM inference is a serialised resource — a semaphore of capacity 1 (configurable) around the model
  client. Queued tasks wait; they do not thrash the GPU. This matters more with an agentic loop,
  since one task now makes many sequential model calls.
- Tool fetches within a research step fan out via `errgroup`, bounded so Quantic isn't hammered.
- A `context` per run carries the deadline and cancellation, threading through both phases.
- Translation of the six non-source locales is embarrassingly parallel in principle but serialised in
  practice by the same GPU semaphore — a good place to learn what a bottleneck actually costs.
- The daemon is opportunistic: the machine is not always on. State is checkpointed in SQLite after
  each phase so an interrupted run resumes rather than restarts.

### 3.7 Storage

SQLite via `modernc.org/sqlite` (pure Go, no cgo — preserves the static-binary property).

- `runs` — id, task_kind, params, phase, state, budgets_used, started_at, finished_at, error
- `tool_calls` — id, run_id, tool, args, response, duration_ms, called_at *(the audit log, N3)*
- `drafts` — id, run_id, locale, content, state, validator_report, created_at
- `manifests` — draft_id → tool_call_ids *(provenance link, N1)*
- `embeddings` — id, source_kind, source_id, chunk, vector BLOB, model, created_at
- `reviews` — draft_id, verdict, reviewer_note, decided_at *(feeds both style memory and the
  accept-rate metric)*

Retention: `tool_calls` responses can be large; plan a compaction policy before it becomes a problem.

### 3.8 Delivery

- **Review queue** — SQLite rows plus a minimal read-only HTTP view (`net/http` + `html/template`,
  no JS framework) once there are more than a handful of drafts. Deliberately not a product.
- **Pull requests** — `go-github`: branch, commit one file per locale (typed frontmatter + prose,
  per the [format contract](rendering.md)), open PR against the private Quantic repo targeting
  `/insights`. Token scoped to branch and PR creation only; `main` is protected independently, so a
  bug in the agent cannot merge. NimblePublisher compiles posts at build time, so a malformed post
  fails CI rather than a request.
- **Issues** — for data-QA findings with no mechanical fix.

## 4. Stack

| Concern | Choice | Reasoning |
|---|---|---|
| Inference server | Ollama | Simplest to operate; model management and a tool-calling API out of the box. `llama.cpp server` remains the escape hatch ([llm-kit](https://github.com/fleveque/llm-kit)). |
| Primary model | Qwen2.5-14B-Instruct (Q4/Q5) | Fits 16GB VRAM with usable context; real tool-calling support. |
| Fast model | Qwen3-8B | Translation passes and latency-sensitive work; "thinking" mode useful for QA reasoning. |
| Heavy model | 32B @ Q3, partial RAM offload | Occasional batch work where slow is acceptable. |
| Embeddings | `nomic-embed-text` via Ollama | Small, fast, good enough for a few thousand chunks. |
| Model I/O | JSON-schema-constrained decoding | Local models are flakier at native tool-calling than frontier models; constrained output is the reliable floor, native tool-calling an optimisation. |
| Tool schemas | Generated from Go structs by reflection | Single source of truth; the Go type *is* the schema. |
| Persistence | `modernc.org/sqlite` | Pure Go, no cgo. |
| GitHub | `go-github` | Mature, well-typed. |
| Logging | `log/slog` | Stdlib structured logging; feeds N3. |
| Config | YAML + env, flags for overrides | Secrets via env only, never committed. |

**Hardware:** 64GB RAM, RTX 4070 Ti Super (16GB VRAM).

## 5. Open questions

1. **MCP authentication from a headless daemon.** Quantic's MCP server uses OAuth, which assumes an
   interactive consent flow. A local daemon needs a non-interactive credential: a long-lived service
   token scoped to read-only tools, a direct internal API path, or a one-time grant with a stored
   refresh token. *First blocker — needed by milestone 5.*
2. **The `/insights` section doesn't exist yet.** It's Phoenix work in the private repo: route,
   layout, markdown rendering, per-locale routing consistent with the existing language subdomains,
   sitemap and hreflang, plus the free-registration gate and its `schema.org` flexible-sampling
   markup. The agent has nowhere to open PRs against until it exists. *Prerequisite for
   milestone 11.* The only agent-side obligation is emitting the `fold_after` marker in draft
   frontmatter — see the [content plan](content.md#registration-gate).
3. **How do we know a draft is any good?** Provenance proves it isn't *wrong*; it doesn't prove it's
   worth publishing. Track human accept/reject rate per task kind and treat it as the metric that
   matters. A task kind below some accept rate is broken — the task, not the reviewer.
4. **Idempotency.** Re-running after a crash must not produce a duplicate weekly digest. Natural key
   per run (kind + period) and an upsert.
5. **Scheduling.** Internal ticker in the daemon vs. systemd timers invoking a one-shot binary. The
   one-shot model is simpler and more crash-tolerant; the daemon model makes the worker pool
   meaningful. Probably both.
6. **Prompt storage.** Prompts are code and should be reviewed like code — versioned in the repo via
   `embed`, not stored in the database. They must contain no Quantic-internal content (N4).
7. **Chunking strategy for filings.** 10-Ks are long and structured. Naive fixed-size chunking will
   split tables badly. Deferred until milestone 10.
8. **Can a 14B model reliably write prose with no figures in it?** The format contract forbids
   numbers in prose entirely. Small models will violate this. The validator catches it and retries,
   but if the violation rate is high the writing prompt needs restructuring — possibly generating
   prose and data in separate calls. This is the likeliest place the accept-rate metric first bites.

## 6. Explicit non-goals

- Not a general-purpose agent framework. It does a handful of known jobs well.
- Not a product. No multi-user support, no auth beyond the local machine, no hosting.
- Not real-time. Everything here is batch work that tolerates minutes of latency.
- Not fine-tuning. Retrieval, not training. If the model needs to be better, use a better model.
- Not touching business logic, financial calculations, or anything involving real user money.
