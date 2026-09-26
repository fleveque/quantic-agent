# quantic-agent — notes for Claude Code

A local Go agent that drafts data-grounded content for Quantic using a local model through Ollama.
It doubles as the author's way of learning Go in public: the commit history and `docs/lessons` are the
learning record. Start with [README.md](README.md) and [docs/design.md](docs/design.md).

## Status — 2026-09-24

- Milestones 0–2 merged (PRs #1–#4): repo and design, first binary and calculator tools, the Ollama
  client (`internal/llm`), `agent -check`/`-ask`, and `cmd/bench`.
- Work has moved from the development laptop (no NVIDIA GPU) to the target desktop (RTX 4070 Ti
  Super, 16GB). Setup and the benchmark are in [docs/target-machine.md](docs/target-machine.md).

## Next, in order

1. **Benchmark results → open question 9.** If `bench.json` / `bench-kvq8.json` exist or the user
   pastes results: decide the primary model (Qwen3.8-27B `UD-IQ3_S` / `UD-Q3_K_XL` vs `qwen3.5:9b`),
   record it in design §4 and §5, change `defaultModel` in `cmd/agent/main.go` only if the 27B wins,
   note the `tools` capability each model reports, and keep the raw files under `docs/benchmarks/`.
   Milestone 8's budgets (design §3.2) should come from these numbers.
2. **Milestone 3 — errors across the LLM boundary**: sentinel errors, `%w` wrapping, `errors.Is`/`As`.
   `internal/llm` returns plain `fmt.Errorf` values on purpose; that's the "before" picture.

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
