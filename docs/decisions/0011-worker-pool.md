# 0011 — The worker pool: one GPU queue, bounded fan-out, a shared pace

**Status:** accepted · **Date:** 2026-10-08

## Context

Design §3.6 describes the shape: one GPU, many network calls. Model calls are a serialised
resource; tool fetches fan out, bounded so Quantic isn't hammered; Python's equivalent of Go's
`errgroup` was left to this milestone. The Week Ahead needs `get_stock` once per company, 20–40
calls, under Quantic's anonymous limit of 60 requests a minute per IP (decision 0006). Milestone 8's
429 retry waits out a refusal, but between one and two minutes each time.

Measured before deciding: a `get_stock` reply is about 1.5KB, roughly 500 tokens. Ollama's default
context window, 4096 tokens, holds a handful of them, and it drops what doesn't fit without saying so
in its reply.

## Decision

The author chose, from options put to them: parallel tool calls within a run *and* batches of runs
sharing the GPU; a client-side limiter; an explicit, measured context window.

1. **Tool calls from one model reply run at once**, in an `asyncio.TaskGroup`, at most four at a
   time behind an `asyncio.Semaphore` (`Researcher.parallel`). Each task returns a failure instead of
   raising it, so a failing call doesn't cancel the calls beside it, and every call is recorded.
2. **The model client is the GPU's queue**: `llm.Client` holds a semaphore of one slot (configurable)
   around `generate` and `chat`. Runs given together (`--research` several times) share the client,
   so their model calls take turns while their network calls overlap. Ollama has its own queue; this
   one makes the agent's behaviour independent of how the server is configured.
3. **Every MCP request is paced** by `quantic.Pace`: at most 50 in any 60 seconds, a sliding window,
   shared by every session in the process. A sliding window that never exceeds 50 in any minute can't
   exceed it in one of Quantic's fixed clock minutes. Ten of the 60 are left for anything else on the
   same address, and the 429 retry stays for that.
4. **Research and writing ask for a 32K context window** (`--num-ctx`, `QUANTIC_NUM_CTX`). Measured:
   at 4096, a question about nine companies lost most of the writer's prompt and the answer invented
   18 figures; at 32K it traced, and the default model stays wholly on a 16GB GPU.

## Consequences

- `get_stock` joins the allowlist, with a description of the agent's own; the research budget
  becomes 16 calls (the calendar and fifteen companies) and 64,000 tokens.
- A batch's exit status is the first non-zero one, in question order.
- Model calls of a batch queue in the client, so a run's `--timeout` includes its wait for the GPU.
- `--ask` and `--check` don't send `num_ctx`. Ollama reloads a model when the context window changes,
  so alternating `--ask` and `--research` reloads it each time.
- Ollama's truncation is still invisible to the agent: only its log shows it. A large enough
  `num_ctx` avoids it; detecting it is open.
