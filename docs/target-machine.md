# Running on the target machine

The agent is developed on a laptop and runs on the desktop: Ryzen, 64GB RAM, RTX 4070 Ti Super
(16GB VRAM). This is the runbook for that machine — setup, the model benchmark behind design
[open question 9](design.md#5-open-questions), and the failures already met once.

Nothing in the binary is machine-specific (see [design §4](design.md#4-stack)), so the same checkout
works on both machines; only the models pulled and the numbers measured differ.

---

## 1. Prerequisites

- **NVIDIA driver.** `nvidia-smi` should list the 4070 Ti Super. Without it Ollama runs on the CPU
  and every measurement below is meaningless.
- **Ollama, current.** Per-model minimum versions are undocumented, and 0.24.0 refused Qwen3.5 with
  `412: requires a newer version of Ollama`. 0.34.4 is known good.

  ```sh
  curl -fsSL https://ollama.com/install.sh | sh    # installs or upgrades in place, keeps models
  ollama --version
  ```

- **Go 1.27 or newer** (`go.mod` declares `go 1.27`): `mise use -g go@1.27`, or a release from
  [go.dev/dl](https://go.dev/dl/).
- **git** with access to the repository.

## 2. Clone and verify

```sh
git clone git@github.com:fleveque/quantic-agent.git
cd quantic-agent
go test -race ./...
```

`-race` builds with cgo, so it needs a C compiler. If it complains, install `gcc` or run
`go test ./...` without it — CI runs the race build either way.

## 3. Pull the candidate models (~32GB)

The agent never downloads models itself. That's deliberate: these are 6–13GB each, and model choice is
explicit configuration, so pulling is an explicit step.

```sh
ollama pull qwen3.5:9b                                   # 6.6 GB  — the safe default
ollama pull hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S      # 12.0 GB — primary candidate, ~3.45 bits/weight
ollama pull hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL    # 13.1 GB — quality step, less room for context
```

## 4. Check what the server has

```sh
go run ./cmd/agent -check
go run ./cmd/agent -check -model hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S
```

Each line ends with the model's **capabilities**. Two matter:

- `tools` — milestone 5's research loop calls tools. For `hf.co` pulls, Ollama derives capabilities
  from the chat template embedded in the GGUF rather than from its own library metadata, so this is
  not guaranteed. If it's missing, note it: milestone 5 would then use structured-output parsing,
  which the design already treats as the reliable floor.
- `thinking` — the agent always sends `think:false`; this says whether that's doing anything.

`-check` exits 1 if the selected model isn't pulled. Names match case-insensitively, the way Ollama
resolves them.

## 5. Run the benchmark

```sh
go run ./cmd/bench                    # table, for reading
go run ./cmd/bench -json > bench.json # the same, for keeping
```

Defaults: the three models above at 8K, 32K and 64K context. Expect several minutes — each 64K row
processes a ~52,000-token prompt — and keep other GPU work off the machine while it runs.

Reading the table:

| Column | Meaning |
|---|---|
| `PROMPT tok/s` | How fast the context is read. Dominates a research loop that accumulates a long manifest. |
| `GEN tok/s` | How fast the answer is written. |
| `ON GPU` | Share of the loaded model in VRAM. **100%** fits. Below 100%, layers spilled into system RAM — expect a large slowdown. **0% (CPU)** means Ollama isn't using the GPU at all; see troubleshooting. |
| `(stopped after N of M tokens)` | The model finished early, so the generation rate is a small sample. |

Every measurement uses a unique prompt prefix (Ollama's prefix cache would otherwise report cached
tokens as processed) and sets `num_ctx` explicitly (the server defaults to a 4096-token window and
truncates anything longer).

## 6. Does KV cache quantisation engage?

At long contexts the KV cache outgrows the weights, and `q8_0` roughly halves it. The setting belongs
to the Ollama **server**, and it only works where flash attention is active — otherwise it silently
falls back to f16. So run the benchmark a second time with it on and compare:

```sh
sudo systemctl edit ollama
#   [Service]
#   Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
sudo systemctl restart ollama
go run ./cmd/bench -json > bench-kvq8.json
```

Compare the 64K rows of the two files. If `size_bytes` and `fraction_on_gpu` don't move, quantisation
isn't engaging for that model. To undo: `sudo systemctl revert ollama && sudo systemctl restart ollama`.

## 7. What the results decide

Keep both files as evidence — `docs/benchmarks/YYYY-MM-DD-bench.json` — and use them to:

1. **Answer open question 9**: Qwen3.8-27B at `UD-IQ3_S` or `UD-Q3_K_XL`, or stay on the 9B. The 27B
   wins only if it stays at 100% on GPU at the context sizes the research loop needs, at a usable
   speed.
2. **Record the choice in design §4**, and change `defaultModel` in `cmd/agent` if the 27B wins.
3. **Set milestone 8's budgets** (design §3.2) from measured tokens/second rather than guesses.

Speed and fit are only half the answer for a sub-4-bit model: tool-call accuracy is the other half,
and that gets measured once milestone 5 exists.

---

## Optional: use the desktop's GPU from the laptop

```sh
sudo systemctl edit ollama
#   [Service]
#   Environment="OLLAMA_HOST=0.0.0.0"
sudo systemctl restart ollama
```

Then, from the laptop: `go run ./cmd/agent -ollama http://<desktop>:11434 -check`.

Ollama has **no authentication**. Binding to `0.0.0.0` exposes it to the whole network, so only do
this on a trusted LAN, ideally with a firewall rule limiting port 11434 to the laptop.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `412: requires a newer version of Ollama` on pull | Ollama too old for that model | Upgrade (section 1) |
| `X is not on this server` | Model not pulled | `ollama list`, then `ollama pull X` |
| `ON GPU 0% (CPU)` on the desktop | Ollama not using the GPU | `nvidia-smi`; `journalctl -u ollama -b \| grep -iE 'cuda\|gpu'` |
| 64K row much slower than 32K, `ON GPU` below 100% | Cache no longer fits beside the weights | Expected at the limit — that's the measurement. Try section 6. |
| `go test -race` fails on cgo | No C compiler | Install `gcc`, or drop `-race` locally |
