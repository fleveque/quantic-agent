# Benchmarks

Raw `cmd/bench -json` output from the target machine, kept as the evidence behind model decisions.
Read with [decision 0005](../decisions/0005-default-model-by-measurement.md); how to run a new one is
in the [runbook](../target-machine.md#5-run-the-benchmark).

| File | What | Conditions |
|---|---|---|
| [`2026-09-24-bench.json`](2026-09-24-bench.json) | The default three models at 8K, 32K, 64K | f16 KV cache |
| [`2026-09-26-moe-vs-dense.json`](2026-09-26-moe-vs-dense.json) | `qwen3.6:35b` (MoE) vs `qwen3.6:27b` (dense) at 8K, 32K | f16 KV cache |

Common to both: RTX 4070 Ti Super 16GB (driver 610.57.04), Ryzen 7 7800X3D, 64GB RAM, Ollama 0.34.4,
flash attention on, one parallel slot. The desktop was in normal use, holding about 1.2GB of VRAM
(Hyprland, a browser, Steam) — the condition the agent actually runs in.

`generated_tokens` below `generated_tokens_requested` means the model stopped early and that row's
generation rate is a small sample. The first row of a run also includes a cold start; treat
`qwen3.5:9b` at 8K in the first file as unreliable for generation speed.
