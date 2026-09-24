# 0004 — Ollama now, llama.cpp on a trigger

**Status:** accepted · **Date:** 2026-09-24 · **Revisit at:** any trigger below

## Context

The agent generates through Ollama (milestone 2 implements the client). The fair challenge: far more
models are available for `llama.cpp` than Ollama's own library, and picking the runtime for
convenience would be a poor reason to accept a smaller pool of models.

## What the comparison actually showed

**Model availability is mostly a non-issue.** Ollama runs any GGUF on the Hugging Face Hub directly —
`ollama run hf.co/{user}/{repo}:{QUANT}` — which is the same ~45k checkpoints `llama.cpp` can load.
Two real exceptions: a *sharded* GGUF has to be merged first with `llama-gguf-split --merge`, and a
local `.gguf` file needs a Modelfile and `ollama create` rather than being run in place. So the gap
isn't catalogue size; it's day-0 support for a brand-new architecture, where `llama.cpp` lands support
first and Ollama's engine follows.

**The VRAM lever exists on both.** KV cache quantisation is the setting that matters most on a 16GB
card, because at long contexts the cache outgrows the weights. Ollama exposes it as
`OLLAMA_KV_CACHE_TYPE=q8_0|q4_0` (roughly −50% and −75% cache memory), requiring flash attention,
which recent versions enable automatically where the backend supports it. Layer offload is per
request via the `num_gpu` option. The caveat is honest: on architectures where flash attention isn't
supported, quantisation silently falls back to f16, and some combinations abort instead of degrading.

**What `llama.cpp` has that Ollama doesn't**, ordered by relevance here:

1. **Speculative decoding** with a draft model — a genuine throughput multiplier on a single GPU, and
   the most plausible way to make a 27B usable on 16GB.
2. **Exact control**: `-ngl` as a number, independent K and V cache types, `--parallel` slots.
3. **GBNF grammars** — constraint beyond JSON-schema-shaped output.
4. Day-0 architectures, as above.

**What Ollama has that `llama.cpp` doesn't**, same ordering:

1. **Multi-model lifecycle.** The design runs three tiers (4B mechanical, 9B primary, 27B heavy)
   behind one endpoint, loading and unloading on demand with `keep_alive`. `llama-server` is one
   process per model, so tiering means supervising several processes or putting a swap proxy in front
   of them.
2. **Embeddings on the same endpoint**, which milestone 10 needs.
3. **Capability metadata.** `/api/tags` reports `tools` and `thinking` per model, so milestone 5 can
   check that the model it's pointed at can actually tool-call instead of assuming.
4. A service that systemd already supervises, and model pulls that don't need a file layout.

## Decision

Stay on Ollama. Keep `llama.cpp` as the named escape hatch it already was
([llm-kit](https://github.com/fleveque/llm-kit) is the path).

The deciding factor is the tiering: three model sizes behind one endpoint with automatic load and
unload is the thing this design leans on, and it's the thing `llama-server` makes into an operations
problem.

## Triggers to revisit

1. The 27B needs speculative decoding to be viable on 16GB — measure first (design open question 9).
2. A model worth using isn't supported by Ollama's engine on day 0.
3. KV quantisation silently falls back to f16 on the model we settle on, and the cache won't fit.
4. Structured output needs grammar-level constraint that `format` can't express.

## Why this is cheap to get wrong

`internal/llm` is about 200 lines behind a concrete `*Client`, and `llama-server` speaks an
OpenAI-compatible API, so a second implementation is comparable in size. Following the convention from
[lesson 02](../lessons/02-structs-tags-and-one-http-call.md) the *consumer* declares the interface it
needs, so a swap is a construction choice at the call site, not a refactor of the agent.
