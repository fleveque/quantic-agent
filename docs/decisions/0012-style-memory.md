# 0012 — Style memory: approved answers, qwen3-embedding, brute force in plain Python

**Status:** accepted · **Date:** 2026-10-08

## Context

Design §3.4 plans retrieval for three uses: style memory (approved drafts as examples of the house
voice), not repeating what was recently written, and filing text. It fixes the mechanics: embeddings
from Ollama, stored as BLOBs in SQLite, brute-force cosine similarity, and never a number from
retrieved text. Nothing yet has been approved, since there is no review step, and filing text waits
on open question 11.

## Decision

The author chose, from options put to them: an approve step and style memory; both candidate
embedding models measured before choosing; plain Python, with numpy only if a measurement asks for it.

1. **A reviewer approves or rejects a run's answer** (`--approve N`, `--reject N`, with `--note`).
   Only an answer whose every figure traced can be approved. An approved answer is embedded and
   stored; a rejected one has its vector deleted.
2. **The writer is shown the two approved answers most similar to the question**, as examples of
   tone and structure, told that their facts and figures are out of date. Which ones, and how
   similar, is recorded per run (`examples`) and shown by `--run N`. They enter the prompt and never
   the provenance manifest, so a figure copied from one is reported like any invented figure.
3. **`qwen3-embedding:0.6b`, with its documented instruction on questions**, by measurement
   (`quantic-evalrecall`): 10 of 12 labelled questions found a fair example, against 8 for
   `nomic-embed-text` with or without its prefixes. It takes 2.4GB beside the 9B's 6.6GB at 32K.
4. **Plain Python search**: vectors stored as little-endian float32 at unit length, so a cosine is
   one `math.sumprod`. Measured: 500 vectors in about 10ms, 20,000 in about 0.4s; numpy is about a
   hundred times faster and isn't added.

## Consequences

- The embedding model must be pulled on the machine (`ollama pull qwen3-embedding:0.6b`); with
  nothing approved, research never calls it.
- `quantic-evalrecall` joins `quantic-evaltools`: changing the embedding model, or its usage, means
  measuring again.
- Style memory imitates closely: in a real run the writer reproduced an approved answer's sentence
  shapes, quirks included. What gets approved is what the agent learns to write.
- Not built: "don't repeat yourself" (recent answers about the same company) and filing text (open
  question 11). Both reuse the same table, with another `source_kind`.
