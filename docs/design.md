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

The calculators return **full `float64` precision and never round**. 1.50 → 1.55 is
`3.333333333333336`, and that is the value the manifest records and the data block carries. Rounding
is presentation, so the template does it — which means the figure the validator compares is exactly
the figure the tool returned, with no rounding rule duplicated between Go and Elixir. A calculator
also refuses inputs it can't answer honestly: `pct_change` from a zero or negative base returns an
error rather than `Inf` or a percentage whose sign reads backwards. Implemented in
[`internal/tools`](../internal/tools/calc.go), milestone 1.

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
- `drafts` — id, run_id, locale, role (`source` | `spot_check` | `auto`), content, state,
  validator_report, created_at
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
| Inference server | Ollama | Three model tiers behind one endpoint with load/unload on demand, embeddings on the same server, and per-model capability metadata. `llama.cpp` stays the escape hatch ([llm-kit](https://github.com/fleveque/llm-kit)) with explicit triggers — [decision 0004](decisions/0004-ollama-now-llama-cpp-on-a-trigger.md). |
| Primary model | Qwen3.5-9B, Q4_K_M (6.6GB) | Fits entirely in 16GB with ~9GB left for KV cache, so long research contexts stay on the GPU. Advertises `tools` and `thinking`. |
| Quality option | Qwen3.5-9B, Q8_0 (11GB) | Same model, near-lossless quantisation, still fully resident — trades context headroom for fidelity. Choose by measurement, not by argument. |
| Heavy model | Qwen3.6-27B, Q4_K_M (17GB) | Over the 16GB line, so some layers spill to RAM. Reserved for occasional deep work where slow is acceptable. |
| Fast model | Qwen3.5-4B (3.4GB) | Mechanical passes — data-QA triage, classification — where a 9B is overkill. |
| Embeddings | `nomic-embed-text` via Ollama | Small, fast, good enough for a few thousand chunks. |
| Model I/O | JSON-schema-constrained decoding | Local models are flakier at native tool-calling than frontier models; constrained output is the reliable floor, native tool-calling an optimisation. |
| Tool schemas | Generated from Go structs by reflection | Single source of truth; the Go type *is* the schema. |
| Persistence | `modernc.org/sqlite` | Pure Go, no cgo. |
| GitHub | `go-github` | Mature, well-typed. |
| Logging | `log/slog` | Stdlib structured logging; feeds N3. |
| Config | YAML + env, flags for overrides | Secrets via env only, never committed. |

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

**Sizing the model to the card.** The Qwen3.5 line runs 0.8B, 2B, 4B, 9B, then jumps to 27B — there is
no 14B any more, which is what the original Qwen2.5-14B plan assumed. At Q4_K_M the 27B needs about
17GB, so on a 16GB card it cannot hold the weights *and* a KV cache; a few layers spill to system RAM
and throughput drops. That leaves two honest candidates for the primary model, the 9B at Q4_K_M and
the same 9B at Q8_0, and one open question: whether a partially offloaded 27B is fast enough to be
worth its quality on this specific card. That is a measurement on the target machine, not a judgement
call — see [open question 9](#5-open-questions).

**Development is not deployment.** The agent is written on one machine and runs on another, so no
model name, host or path is baked into the binary. `-model` / `QUANTIC_MODEL` and `-ollama` /
`OLLAMA_HOST` carry them, and `agent -check` prints what the server it is pointed at actually has,
including each model's `capabilities` — the `tools` entry is what milestone 5 depends on.

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
9. **Which primary model, measured on the target box.** Qwen3.5-9B Q4_K_M (fully resident, most
   context), the same 9B at Q8_0 (fully resident, best fidelity for its size), or Qwen3.6-27B Q4_K_M
   with partial RAM offload (best model, unknown speed). The deciding numbers are tokens/second at a
   realistic research-context length and whether a 27B run finishes inside the loop's wall-clock
   budget. Nothing in the code depends on the answer — it is one flag.

   `cmd/bench` measures it: prompt and generation rates per model and context size, plus the share of
   each model that stayed in VRAM (`/api/ps` reports `size` against `size_vram`, and anything below
   100% means layers spilled into system RAM). Run it on the deployment machine — a development
   laptop with no CUDA device reports 0% and about 10 tokens/second, which answers nothing about the
   4070 Ti Super. Two further notes the tool encodes: each measurement carries a unique nonce,
   because Ollama's prefix cache otherwise reports cached tokens as if it had processed them, and
   every request sets `num_ctx`, because the server defaults to a 4096-token window whatever the
   model supports and silently truncates a longer prompt.
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
