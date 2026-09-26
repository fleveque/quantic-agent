# quantic-agent — notes for Claude Code

A local Go agent that drafts data-grounded content for Quantic using a local model through Ollama.
It doubles as the author's way of learning Go in public: the commit history and `docs/lessons` are the
learning record. Start with [README.md](README.md) and [docs/design.md](docs/design.md).

## Status — 2026-09-26

- Milestones 0–2 merged (PRs #1–#4): repo and design, first binary and calculator tools, the Ollama
  client (`internal/llm`), `agent -check`/`-ask`, and `cmd/bench`.
- Running on the target desktop (RTX 4070 Ti Super 16GB, 64GB RAM); runbook in
  [docs/target-machine.md](docs/target-machine.md).
- Open question 9 answered by measurement ([ADR 0005](docs/decisions/0005-default-model-by-measurement.md)):
  `qwen3.5:9b` stays the default; `qwen3.6:35b` (MoE) and Qwen3.8-27B `UD-IQ3_S` are candidates, decided
  on task quality from milestone 5. Raw results in `docs/benchmarks/`.

## Next, in order

1. **Milestone 3 — errors across the LLM boundary**: sentinel errors, `%w` wrapping, `errors.Is`/`As`.
   `internal/llm` returns plain `fmt.Errorf` values on purpose; that's the "before" picture. Include a
   distinguishable "Ollama unreachable" error: design §3.6 requires the agent to wait, not fail, when
   the server is stopped.
2. Milestone 5 must leave behind an evaluation set that runs against any model name (ADR 0005), the
   basis of the model-upkeep task (design §1, open question 10).

## Conventions

- **Every milestone ships code and a lesson**: `docs/lessons/NN-*.md` (NN = milestone number), written
  in the author's first person — someone coming to Go from Elixir and Ruby — plus a formatted page
  published as an artifact and linked from the lesson and `docs/lessons/README.md`. The existing pages
  share one stylesheet; reuse it.
- **…and a code walkthrough** (from milestone 2): a second artifact that goes through every file the
  milestone's PR added or changed, in reading order, as a tech lead mentoring someone new to Go: what
  each part does, why it's written that way, what the standard library is doing, and why each pointer
  is a pointer. Excerpts are copied verbatim from a named commit; "try it" experiments show real
  outputs. Compare with Ruby or Elixir only where it genuinely helps. Linked from the lesson and the
  lessons README.
- **Decisions are ADRs** in `docs/decisions/NNNN-*.md`.
- **`main` is protected.** Branch → PR → CI green → the user merges. Never merge. Before pushing to an
  existing branch, check its PR isn't already merged — a commit once landed on a merged branch and
  never reached `main`.
- **Verify CI on the exact commit SHA** (`gh run list --json headSha`), not the PR's check list, which
  can still show the previous commit's run.
- **Gate before every commit**: `gofmt -l .` prints nothing, `go vet ./...`, `go test -race ./...`,
  and the relative-link check in `.github/workflows/ci.yml`.
- **Claims are verified by running them.** Test fixtures are payloads captured from a real Ollama
  (`internal/llm/testdata`). Lesson outputs are real outputs.
- **Nothing machine-specific in the binary**: `-model`/`QUANTIC_MODEL`, `-ollama`/`OLLAMA_HOST`.
- **Models are used as published** (Ollama library or `hf.co` pulls). No hand-built variants via
  `ollama create`; new models arrive too often to maintain them.
- **The GPU is shared with the author.** Anything long-running must stop cleanly and tolerate a stopped
  Ollama (design §3.6, runbook §8).
- The design's non-negotiables (design §2) — no invented numbers, no autonomous publishing — are not
  up for convenience trade-offs.

## Ollama, learned the hard way

- `stream` must be sent as `false` explicitly; the server streams by default.
- `num_ctx` defaults to 4096 whatever the model supports; longer prompts are truncated.
- Qwen3.5+ are thinking models: send `think:false`. Reasoning text never enters a draft.
- The prefix cache reports cached tokens as processed; benchmarks need a unique prompt prefix.
- Model names resolve case-insensitively; compare with `strings.EqualFold`.
- `hf.co/{user}/{repo}:{QUANT}` pulls any Hub GGUF. Per-model version floors are undocumented.
- Error bodies are `{"error": ...}` JSON, except a bad path, which is plain text.
